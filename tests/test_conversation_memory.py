"""Conversation recall is bounded, tenant scoped and shared by independent workers."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from service import conversation_memory as memory
from tests.test_platform_security import platform as platform_fixture, login

platform = platform_fixture


class Documents:
    def __init__(self):
        self.data = {}

    def read_json(self, tenant, filename):
        try:
            return copy.deepcopy(self.data[tenant])
        except KeyError:
            raise FileNotFoundError from None


@pytest.fixture
def shared(tmp_path, monkeypatch):
    monkeypatch.setenv('V7_STORAGE_BACKEND', 'sqlite')
    monkeypatch.setenv('SECURITY_DB_PATH', str(tmp_path / 'shared.db'))
    return Documents()


def test_memory_survives_workers_but_never_crosses_tenant_or_conversation(shared):
    first = memory.ConversationMemory(shared, 'ALPHA')
    with first.turn('conversation-one'):
        first.set('conversation-one', 'sales_agent', {'requirements': ['under £40']})
        first.set('conversation-one', 'last_sku', 'bottle')
    second = memory.ConversationMemory(shared, 'ALPHA')
    assert second.get('conversation-one', 'last_sku') == 'bottle'
    assert second.get('conversation-one', 'sales_agent')['requirements'] == ['under £40']
    assert second.get('conversation-two', 'last_sku') is None
    assert memory.ConversationMemory(shared, 'BETA').get('conversation-one', 'last_sku') is None


def test_memory_expires_and_shorter_lifetime_takes_effect_immediately(shared, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(memory.time, 'time', lambda: clock[0])
    current = memory.ConversationMemory(shared, 'ALPHA')
    current.set('same', 'last_sku', 'bottle')
    clock[0] += 301
    shared.data['ALPHA'] = {'memory': {**memory.DEFAULTS, 'retention_minutes': 5}}
    assert current.get('same', 'last_sku') is None


def test_disabling_and_clearing_never_resurrects_old_context(shared):
    current = memory.ConversationMemory(shared, 'ALPHA')
    current.set('same', 'last_sku', 'bottle')
    shared.data['ALPHA'] = {'memory': {**memory.DEFAULTS, 'enabled': False}, 'memory_generation': 'disabled'}
    assert current.get('same', 'last_sku') is None
    current.set('same', 'last_sku', 'ignored')
    shared.data['ALPHA']['memory']['enabled'] = True
    assert current.get('same', 'last_sku') is None
    current.set('same', 'last_sku', 'new')
    current.clear('same')
    assert current.get('same', 'last_sku') is None


def test_inflight_old_generation_cannot_repopulate_cleared_context(shared):
    current = memory.ConversationMemory(shared, 'ALPHA')
    with current.turn('same'):
        current.set('same', 'last_sku', 'old')
        shared.data['ALPHA'] = {'memory': memory.DEFAULTS, 'memory_generation': 'cleared'}
    assert current.get('same', 'last_sku') is None


def test_cached_and_pending_values_expire_inside_an_active_turn(shared, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(memory.time, 'time', lambda: clock[0])
    current = memory.ConversationMemory(shared, 'ALPHA')
    current.set('same', 'last_sku', 'old', ttl=1)
    with current.turn('same'):
        current.set('same', 'last_category', 'short', ttl=1)
        clock[0] += 2
        assert current.get('same', 'last_sku') is None
        assert current.get('same', 'last_category') is None
    assert current.get('same', 'last_category') is None


def test_concurrent_workers_merge_distinct_keys_without_lost_updates(shared):
    ready = Barrier(2)
    def write(key):
        worker = memory.ConversationMemory(shared, 'ALPHA')
        with worker.turn('same'):
            ready.wait(timeout=10)
            worker.set('same', key, key)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(write, ['last_sku', 'last_category']))
    current = memory.ConversationMemory(shared, 'ALPHA')
    assert current.get('same', 'last_sku') == 'last_sku'
    assert current.get('same', 'last_category') == 'last_category'


def test_buffer_cannot_be_reused_for_another_conversation(shared):
    current = memory.ConversationMemory(shared, 'ALPHA')
    with current.turn('first'):
        with pytest.raises(ValueError, match='scope_mismatch'):
            current.get('second', 'last_sku')
        with pytest.raises(ValueError):
            current.set('second', 'last_sku', 'bottle')


@pytest.mark.parametrize('settings', [{'enabled': 'yes'}, {'history_tokens': True},
    {'history_messages': 100}, {'retention_minutes': 0}, {'other_customer': True}])
def test_invalid_memory_settings_fail_closed(settings):
    with pytest.raises(ValueError):
        memory.validated(settings)


def test_history_uses_current_budget_and_message_limit_without_mutating_original():
    rows = [{'role': 'user' if index % 2 == 0 else 'assistant', 'content': f'Message {index}'} for index in range(30)]
    original = copy.deepcopy(rows)
    config = {**memory.DEFAULTS, 'history_messages': 4, 'history_tokens': 256}
    result = memory.bounded_history(rows, config)
    assert result[-1] == rows[-1] and len(result) <= 4
    assert sum(len(json.dumps(row, ensure_ascii=False).encode()) + 64 for row in result) <= 256
    assert rows == original
    assert memory.bounded_history(rows, {**config, 'enabled': False}) == []


def test_oversized_reply_does_not_erase_latest_customer_context():
    rows = [{'role': 'user', 'content': 'My budget is £25.'},
            {'role': 'assistant', 'content': 'Complete policy. ' * 200}]
    assert memory.bounded_history(rows, {**memory.DEFAULTS, 'history_tokens': 256}) == rows[:1]


def test_requirement_validation_sees_the_same_extended_history_as_the_model():
    from service import grounded_conversation
    rows = [{'role': 'user', 'content': 'for my quiet office'}]
    rows += [{'role': 'assistant', 'content': 'A different short message.'}] * 8
    state = {'requirements': ['for my quiet office'], 'requirements_update': None}
    result, _ = grounded_conversation._requirements_state(state, 'Which is suitable?', rows, {},
        {**memory.DEFAULTS, 'history_messages': 20, 'history_tokens': 8192})
    assert result == ['for my quiet office']


def test_memory_api_authorization_revision_clear_and_input_cost(platform):
    app = platform[0]
    client = app.test_client()
    url = '/admin/api/ai-model/memory'
    assert client.get(url).status_code in {401, 403}
    csrf = login(client)
    original = client.get(url).json
    settings = {**original['settings'], 'history_tokens': 4096, 'history_messages': 20}
    headers = {'X-CSRF-Token': csrf}
    assert client.put(url, json={'settings': settings, 'revision': original['revision']}).status_code == 403
    assert client.put(url + '?tenant=BETA', json={'settings': settings, 'revision': original['revision']}, headers=headers).status_code == 403
    saved = client.put(url, json={'settings': settings, 'revision': original['revision']}, headers=headers)
    assert saved.status_code == 200
    assert saved.json['settings'] == settings and saved.json['scope'] == 'conversation'
    cost = saved.json['cost']
    assert cost['history_usd_per_1000_replies'] == pytest.approx(cost['input_usd_per_million'] * 4096 / 1000)
    assert client.put(url, json={'settings': settings, 'revision': original['revision']}, headers=headers).status_code == 409
    current = app.container.for_tenant('ALPHA').memory
    current.set('same', 'last_sku', 'bottle')
    cleared = client.delete(url, json={'revision': saved.json['revision']}, headers=headers)
    assert cleared.status_code == 200 and current.get('same', 'last_sku') is None
    assert client.get(url + '?tenant=BETA').status_code == 403


def test_native_conversation_memory_is_shared_and_force_rls_scoped(pg_runtime):
    from retrieval.storage import Storage
    from service import session_store
    tenant, other = pg_runtime['tenant'], pg_runtime['other']
    first = memory.ConversationMemory(Storage(tenant), tenant)
    first.set('same', 'last_sku', 'bottle')
    assert memory.ConversationMemory(Storage(tenant), tenant).get('same', 'last_sku') == 'bottle'
    assert memory.ConversationMemory(Storage(other), other).get('same', 'last_sku') is None
    with session_store.postgres_connection(other) as db:
        assert db.execute('SELECT count(*) FROM v7_private.conversation_memory WHERE tenant=%s', (tenant,)).fetchone()[0] == 0


def test_older_customer_facts_are_relevant_bounded_and_exclude_private_or_retired_quotes():
    rows = ['My car is a Polo.', 'My previous car was a Golf.', 'I need ceramic coating.',
            'My car contact is customer@example.com', 'My car password is secret', 'Unrelated preference.']
    selected = memory.relevant_customer_facts(rows, 'What car did I tell you about?',
        recent=[{'role': 'user', 'content': 'I need ceramic coating.'}], retired=['My previous car was a Golf.'])
    assert selected == ['My car is a Polo.']
    bounded = memory.relevant_customer_facts(['Car ' + str(i) + ' ' + 'é' * 150 for i in range(32)], 'Car?')
    assert len(bounded) <= 2 and sum(len(row.encode('utf-8')) for row in bounded) <= 512
    assert memory.relevant_customer_facts(rows, 'Unmatched topic') == []


def test_older_facts_follow_tenant_scope_and_memory_disable(shared):
    alpha = memory.ConversationMemory(shared, 'ALPHA')
    alpha.set('same', 'conversation_customer_facts', ['My car is a Polo.'])
    assert alpha.get('same', 'conversation_customer_facts') == ['My car is a Polo.']
    assert memory.ConversationMemory(shared, 'BETA').get('same', 'conversation_customer_facts') is None
    from unittest.mock import patch
    with patch.object(memory, 'profile', return_value=({**memory.DEFAULTS, 'enabled': False}, 'disabled')):
        assert alpha.get('same', 'conversation_customer_facts') is None
