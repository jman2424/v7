"""Real private PostgreSQL migration, queue and RLS checks in disposable CI DB."""
import pytest

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
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with session_store.postgres_connection(other) as db:
            db.execute("INSERT INTO v7_private.business_operations(id,tenant,channel,event_key,conversation_id,source_address,payload,state,created,updated) VALUES(%s,%s,'email','forged','forged','sender','{}','queued',0,0)",('f'*32,tenant))
    admin=pg_runtime['admin']
    for role in ('anon','authenticated','service_role'):
        assert not admin.execute("SELECT has_table_privilege(%s,'v7_private.business_operations','SELECT')",(role,)).fetchone()[0]
