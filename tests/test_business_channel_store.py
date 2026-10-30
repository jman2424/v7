"""Durable queues preserve tenant isolation, decisions, leases and spend limits."""
import time

import pytest

from service import business_operations as operations, business_channels as channels


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setenv('V7_STORAGE_BACKEND', 'sqlite')
    monkeypatch.setenv('SECURITY_DB_PATH', str(tmp_path/'operations.db'))


def enqueue(tenant='ALPHA', key='message-1', channel='email', source='customer@example.com', **kwargs):
    return operations.enqueue(tenant, channel, key, 'conversation-'+key, source,
                              {'recipient': 'business@example.com', 'text': 'Synthetic question'}, **kwargs)


def test_queue_is_idempotent_and_tenant_scoped(database):
    first, created = enqueue()
    assert created
    duplicate, created = enqueue()
    assert not created and duplicate['id'] == first['id']
    other, _ = enqueue('BETA')
    assert other['id'] != first['id']
    assert operations.get('BETA', first['id']) is None
    assert len(operations.listing('ALPHA')) == 1
    with pytest.raises(ValueError, match='operation_event_conflict'):
        enqueue(source='different@example.com')


def test_claims_are_exclusive_and_stale_workers_cannot_finish(database):
    first, _ = enqueue()
    claimed = operations.claim('ALPHA')
    assert claimed['id'] == first['id'] and claimed['state'] == 'processing'
    assert operations.claim('ALPHA') is None
    assert not operations.finish('ALPHA', first['id'], 'wrong-lease', 'completed', reply='Wrong worker')
    assert operations.finish('ALPHA', first['id'], claimed['lease'], 'needs_review', reply='A verified draft')
    assert operations.get('ALPHA', first['id'])['reply'] == 'A verified draft'


def test_approval_requires_matching_version_and_cannot_change_envelope(database):
    first, _ = enqueue()
    claimed = operations.claim('ALPHA')
    operations.finish('ALPHA', first['id'], claimed['lease'], 'needs_review', reply='A draft')
    row = operations.get('ALPHA', first['id'])
    with pytest.raises(ValueError, match='operation_changed'):
        operations.decide('ALPHA', first['id'], row['version']-1, 'approve', reply='Stale edit')
    approved = operations.decide('ALPHA', first['id'], row['version'], 'approve', reply='Approved reply')
    assert approved['state'] == 'approved' and approved['source_address'] == 'customer@example.com'
    assert operations.claim('ALPHA')['state'] == 'sending'


def test_interrupted_send_is_uncertain_and_not_repeated(database):
    first, _ = enqueue()
    claim = operations.claim('ALPHA')
    operations.finish('ALPHA', first['id'], claim['lease'], 'approved', reply='Reply')
    operations.claim('ALPHA')
    with operations.connection('ALPHA', write=True) as db:
        db.execute('UPDATE business_operations SET lease_until=? WHERE tenant=? AND id=?', (time.time()-1, 'ALPHA', first['id']))
    assert operations.claim('ALPHA') is None
    assert operations.get('ALPHA', first['id'])['state'] == 'uncertain'


def test_limits_survive_worker_runs_and_new_conversation_ids(database):
    for index in range(2):
        enqueue(key='m'+str(index), daily_limit=2)
    with pytest.raises(ValueError, match='channel_daily_limit'):
        enqueue(key='new-conversation', daily_limit=2)
    assert len(operations.listing('ALPHA')) == 2


def test_modes_grants_and_routes_fail_closed(monkeypatch):
    assert not channels.validate({})['email']['enabled']
    with pytest.raises(ValueError):
        channels.validate({'email': {'enabled': True}})
    with pytest.raises(ValueError):
        channels.validate({'email': {'enabled': True, 'privacy_confirmed': True, 'api_key': 'not-allowed'}})
    with pytest.raises(ValueError):
        channels.validate_grants({'email': True, 'phone': 'true'})
    monkeypatch.setenv('V7_EMAIL_ROUTES_JSON', '{"support@example.com":"ALPHA"}')
    assert channels.bindings('email') == {'support@example.com': 'ALPHA'}
    monkeypatch.setenv('V7_EMAIL_ROUTES_JSON', '{"support@example.com":"../BETA"}')
    assert channels.bindings('email') == {}


def test_phone_review_cannot_be_approved_as_an_email_send(database):
    first, _ = enqueue(channel='phone')
    claim = operations.claim('ALPHA')
    operations.finish('ALPHA', first['id'], claim['lease'], 'needs_review')
    with pytest.raises(ValueError, match='operation_requires_manual_followup'):
        operations.decide('ALPHA', first['id'], operations.get('ALPHA', first['id'])['version'], 'approve', reply='Send this')


def test_retention_removes_content_but_delayed_deliveries_cannot_resend(database):
    first,_=enqueue()
    with operations.connection('ALPHA',write=True) as db:
        db.execute('UPDATE business_operations SET created=? WHERE tenant=? AND id=?',(time.time()-2*86400,'ALPHA',first['id']))
    assert operations.purge('ALPHA','email',1)==1
    assert not operations.listing('ALPHA')
    duplicate,created=enqueue()
    assert not created and duplicate['id']==first['id']
    assert duplicate['payload']=={} and duplicate['source_address']==duplicate['conversation_id']==duplicate['reply']==''
    assert 'message-1' not in duplicate['event_key']
    assert operations.claim('ALPHA') is None
