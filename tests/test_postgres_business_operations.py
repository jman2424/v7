"""Real private PostgreSQL migration, queue and RLS checks in disposable CI DB."""
import pytest
import json
import time
from types import SimpleNamespace

from service import business_operations as operations, session_store


def test_native_operations_and_rls(pg_runtime):
    tenant,other=pg_runtime['tenant'],pg_runtime['other']
    row,created=operations.enqueue(tenant,'email','synthetic-email','email:synthetic','visitor@example.net',{'recipient':'business@example.com'})
    assert created and operations.get(other,row['id']) is None
    claim=operations.claim(tenant)
    assert operations.claim(tenant) is None
    assert operations.finish(tenant,row['id'],claim['lease'],'needs_review',reply='Verified draft')
    version=operations.get(tenant,row['id'])['version']
    operations.decide(tenant,row['id'],version,'approve')
    assert operations.claim(tenant)['state']=='sending'
    with session_store.postgres_connection(other) as db:
        assert db.execute('SELECT id FROM v7_private.business_operations WHERE id=%s',(row['id'],)).fetchone() is None
    import psycopg
    with session_store.postgres_connection(other) as db:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            # Assert the precise RLS error within a savepoint; the outer shared
            # connection correctly sanitizes driver exceptions that escape it.
            with db.transaction():
                db.execute("INSERT INTO v7_private.business_operations(id,tenant,channel,event_key,conversation_id,source_address,payload,state,created,updated) VALUES(%s,%s,'email','forged','forged','sender','{}','queued',0,0)",('f'*32,tenant))
    admin=pg_runtime['admin']
    for role in ('anon','authenticated','service_role'):
        assert not admin.execute("SELECT has_table_privilege(%s,'v7_private.business_operations','SELECT')",(role,)).fetchone()[0]


def test_native_worker_needs_no_admin_browser_session(pg_runtime,monkeypatch):
    from retrieval.storage import Storage
    from service import business_channels as channels, channel_worker
    tenant=pg_runtime['tenant']
    storage=Storage(tenant)
    storage.write_json(tenant,channels.GRANTS_FILE,{'email':False,'phone':True})
    storage.write_json(tenant,channels.FILENAME,channels.validate({'phone':{
        'enabled':True,'privacy_confirmed':True,'mode':'review'}}))
    monkeypatch.setenv('V7_PHONE_ROUTES_JSON',json.dumps({'+447700900001':tenant}))
    monkeypatch.delenv('V7_EMAIL_ROUTES_JSON',raising=False)
    row,_=operations.enqueue(tenant,'phone','call-one','phone:synthetic','anonymous',{
        'recipient':'+447700900001','text':'Please call back','mode_at_intake':'review'})
    assert channel_worker.run_pending(SimpleNamespace(storage=storage))==1
    assert operations.get(tenant,row['id'])['state']=='needs_review'


def test_native_cleanup_receipts_and_body_retention_are_tenant_scoped(pg_runtime):
    tenant,other=pg_runtime['tenant'],pg_runtime['other']
    inbox,thread='00000000-0000-4000-8000-000000000002','00000000-0000-4000-8000-000000000003'
    row,_=operations.enqueue(tenant,'email','cleanup-test','email:cleanup','visitor@example.net',
        {'inbox_id':inbox,'thread_id':thread,'text':'Private synthetic body'})
    claim=operations.claim(tenant)
    assert operations.finish(tenant,row['id'],claim['lease'],'completed',reply='Synthetic draft')
    with operations.connection(tenant,write=True) as db:
        db.execute('UPDATE business_operations SET created=? WHERE tenant=? AND id=?',
                   (time.time()-2*86400,tenant,row['id']))
    candidate=operations.cleanup_candidates(tenant,1)[0]
    job=operations.claim_cleanup(tenant,candidate)
    job['payload'].update(cleanup_thread_hash=operations.cleanup_hash(inbox,thread),cleanup_attempted=True)
    assert operations.save_payload(tenant,job['id'],job['lease'],job['payload'])
    assert operations.cleanup_receipt(tenant,job,'trashed')
    assert operations.thread_operations(other,inbox,thread)==[]
    assert operations.cleanup_counts(other)=={}
    assert operations.purge(tenant,'email',1)==1
    result=operations.get(tenant,row['id'])
    assert result['state']=='expired' and result['reply']==result['source_address']==''
    assert 'text' not in result['payload']
    assert operations.previously_trashed(tenant,inbox,thread)
    assert not operations.previously_trashed(other,inbox,thread)
