"""Accepted chat pairs persist with the lead in one tenant-scoped write."""
from contextlib import contextmanager

from service import crm_service


MESSAGES = [{'from': 'user', 'text': 'A question'},
            {'from': 'assistant', 'text': 'An answer', 'source': 'public'}]


def test_chat_pair_uses_one_snapshot_and_survives_reopen(tmp_path, monkeypatch):
    monkeypatch.setenv('V7_STORAGE_BACKEND', 'sqlite')
    path = str(tmp_path / 'crm.json')
    crm = crm_service.CRMService(snapshot_path=path)
    writes = []
    original = crm._maybe_snapshot

    def snapshot():
        writes.append(True)
        original()

    monkeypatch.setattr(crm, '_maybe_snapshot', snapshot)
    lead = crm.upsert_lead('ALPHA', name=None, phone=None, channel='web',
                           session_id='chat-one', messages=MESSAGES)
    assert len(writes) == 1
    reopened = crm_service.CRMService(snapshot_path=path)
    saved = reopened.get_lead('ALPHA', lead['id'])
    assert [row['text'] for row in saved['conversations']] == ['A question', 'An answer']
    assert saved['conversations'][1]['meta'] == {'source': 'public'}
    assert reopened.get_lead('BETA', lead['id']) is None
    again = crm.upsert_lead('ALPHA', name='Customer', phone=None, channel='web',
                            session_id='chat-one', messages=MESSAGES)
    assert again['id'] == lead['id']
    assert len(again['conversations']) == 4
    assert len(writes) == 2


def test_postgres_pair_uses_one_connection_and_one_save(monkeypatch):
    monkeypatch.setenv('V7_STORAGE_BACKEND', 'postgres')
    connections, saves, statements = [], [], []

    class Connection:
        def execute(self, query, params):
            statements.append((query, params))
            return self

        def fetchone(self):
            return None

    @contextmanager
    def connection(tenant):
        connections.append(tenant)
        yield Connection()

    monkeypatch.setattr(crm_service.session_store, 'postgres_connection', connection)
    monkeypatch.setattr(crm_service, '_pg_save', lambda con, tenant, lead: saves.append((tenant, lead)))
    crm = crm_service.CRMService()
    lead = crm.upsert_lead('ALPHA', name=None, phone=None, channel='web',
                           session_id='chat-one', messages=MESSAGES)
    assert connections == ['ALPHA']
    assert len(saves) == 1 and saves[0][0] == 'ALPHA'
    assert [row['from'] for row in lead['conversations']] == ['user', 'assistant']
    assert 'pg_advisory_xact_lock' in statements[0][0]
    assert all('tenant=%s' in query for query, _ in statements[1:])
