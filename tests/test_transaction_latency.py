"""Fewer round trips must retain fresh authority and complete prompt facts."""
import copy
import json
from types import SimpleNamespace

import pytest

from service import analytics_db, api_usage, grounded_conversation, session_store
from service.message_handler import MessageHandler
from tests import test_api_usage
from tests.test_grounded_conversation import client_for

ledger = test_api_usage.ledger


def valid_scope():
    return [True, False, False, False, False, True, False, False,
            ['v7_backend'], [['login_attempts', True, True, False],
                             ['management_sessions', True, True, False]],
            'pg_catalog,v7_private', 'ALPHA']


def test_fresh_scope_and_local_settings_use_one_database_exchange():
    queries = []

    def execute(sql, params):
        queries.append((sql, params))
        return SimpleNamespace(fetchone=lambda: valid_scope())

    session_store._prepare_postgres_scope(SimpleNamespace(execute=execute), 'ALPHA', False)
    assert len(queries) == 1
    assert queries[0][1] == ('ALPHA',)
    assert 'pg_catalog.pg_roles' in queries[0][0]


@pytest.mark.parametrize('defect', [
    'changed_identity', 'superuser', 'bypass_rls', 'create_database', 'create_role',
    'missing_backend', 'schema_create', 'database_create', 'extra_membership',
    'missing_membership', 'missing_table', 'disabled_rls', 'unforced_rls',
    'owned_table', 'wrong_tenant', 'wrong_path', 'missing_role',
])
def test_combined_exchange_still_rejects_every_invalid_security_scope(defect):
    row = valid_scope()
    flags = {'changed_identity': 0, 'superuser': 1, 'bypass_rls': 2,
             'create_database': 3, 'create_role': 4, 'missing_backend': 5,
             'schema_create': 6, 'database_create': 7}
    if defect in flags:
        index = flags[defect]
        row[index] = not row[index]
    elif defect == 'extra_membership':
        row[8].append('anon')
    elif defect == 'missing_membership':
        row[8] = []
    elif defect == 'missing_table':
        row[9].pop()
    elif defect in {'disabled_rls', 'unforced_rls', 'owned_table'}:
        row[9][0][{'disabled_rls': 1, 'unforced_rls': 2, 'owned_table': 3}[defect]] ^= True
    elif defect == 'wrong_tenant':
        row[11] = 'OTHER'
    elif defect == 'wrong_path':
        row[10] = 'public'
    elif defect == 'missing_role':
        row = None
    db = SimpleNamespace(execute=lambda *args: SimpleNamespace(fetchone=lambda: row))
    with pytest.raises(RuntimeError, match='not restricted'):
        session_store._prepare_postgres_scope(db, 'ALPHA', False)


def test_combined_sqlite_lead_session_preserves_contact_and_tenant(tmp_path, monkeypatch):
    monkeypatch.setenv('V7_STORAGE_BACKEND', 'sqlite')
    monkeypatch.setattr(analytics_db, 'DB_PATH', str(tmp_path/'analytics.db'))
    monkeypatch.setattr(analytics_db, '_INIT_DONE', False)
    analytics_db.upsert_lead(tenant='ALPHA', lead_id='same', name='Customer', phone='synthetic-phone')
    analytics_db.set_lead_session(tenant='ALPHA', lead_id='same', session_id='old')
    analytics_db.upsert_lead_session(tenant='ALPHA', lead_id='same', session_id='new')
    analytics_db.upsert_lead_session(tenant='BETA', lead_id='same', session_id='other', name='Other')
    with analytics_db._conn() as db:
        assert tuple(db.execute('SELECT name,phone,last_session_id FROM leads WHERE tenant=? AND lead_id=?',
                                ('ALPHA', 'same')).fetchone()) == ('Customer', 'synthetic-phone', 'new')
        assert tuple(db.execute('SELECT name,last_session_id FROM leads WHERE tenant=? AND lead_id=?',
                                ('BETA', 'same')).fetchone()) == ('Other', 'other')


def test_prompt_prefix_is_stable_without_removing_or_reordering_facts(ledger):
    knowledge = {'product:basic': {'name': 'Basic', 'price': 99, 'currency': 'GBP',
                                 'features': ['First published feature', 'Second published feature']},
                 'faq:returns': {'question': 'Returns?', 'answer': 'Unused goods within 14 days.'}}
    original = copy.deepcopy(knowledge)
    client = client_for('Basic is £99.', ['product:basic'])
    captures = []
    for rows, history in ((knowledge, []),
                          ({key: dict(reversed(list(value.items()))) for key, value in reversed(list(knowledge.items()))},
                           [{'role': 'user', 'content': 'I am comparing options.'}])):
        with api_usage.usage_context('EXAMPLE', 'test', 'v7'):
            assert grounded_conversation.answer(client, 'gpt-4o-mini', 'How much is Basic?',
                                                 rows, history, 'professional')
        captures.append(client.chat.completions.create.call_args.kwargs)
    first, second = [row['messages'][1]['content'] for row in captures]
    assert first.split(',"recent_conversation":')[0] == second.split(',"recent_conversation":')[0]
    payload = json.loads(second)
    assert payload['knowledge']['product:basic'] == knowledge['product:basic']
    assert payload['knowledge']['product:basic']['features'] == knowledge['product:basic']['features']
    assert payload['recent_conversation'] == [{'role': 'user', 'content': 'I am comparing options.'}]
    assert knowledge == original
    assert captures[0]['response_format'] == captures[1]['response_format']


@pytest.mark.parametrize('combined', [True, False])
def test_crm_uses_combined_writer_and_preserves_custom_adapter_fallback(combined):
    calls = []
    adapter = SimpleNamespace(upsert_lead=lambda **kw: calls.append(('lead', kw)),
                              set_lead_session=lambda **kw: calls.append(('session', kw)))
    if combined:
        adapter.upsert_lead_session = lambda **kw: calls.append(('combined', kw))
    handler = MessageHandler.__new__(MessageHandler)
    handler.crm = SimpleNamespace(upsert_lead=lambda *args, **kwargs: None)
    handler.analytics = adapter
    handler._log_crm(SimpleNamespace(tenant='ALPHA', channel='web', session_id='chat'),
                     'A question', {'reply': 'An answer', 'entities': {'name': 'Synthetic'}})
    assert [name for name, _ in calls] == (['combined'] if combined else ['lead', 'session'])
    assert all(row['tenant'] == 'ALPHA' and row['lead_id'] == 'web:chat' for _, row in calls)
    assert calls[0][1]['name'] == 'Synthetic'
