"""Real private PostgreSQL migration, queue and row-level-security checks for Business Sync (disposable CI database)."""
import pytest

from service import business_sync as sync, sync_store as store, session_store


def test_native_sync_tables_are_tenant_isolated(pg_runtime, monkeypatch):
    monkeypatch.setenv('V7_SYNC_ENCRYPTION_KEY', 'k' * 40)
    tenant, other = pg_runtime['tenant'], pg_runtime['other']
    source = store.create_source(tenant, 'woocommerce', 'Shop', {'host': 'shop.example.test'},
                                 {'consumer_secret': 'cs_native_test'}, {'terms_version': sync.TERMS_VERSION},
                                 auto_sync=True, auto_apply=True)
    assert 'cs_native_test' not in source['secret']
    assert store.unseal(tenant, source['secret']) == {'consumer_secret': 'cs_native_test'}
    assert store.get_source(other, source['id']) is None and store.list_sources(other) == []
    assert tenant in store.work_tenants() and other not in store.work_tenants()
    job, created = store.enqueue(tenant, source['id'], 'event', 'delivery-1', {'records': []})
    assert created and store.enqueue(tenant, source['id'], 'event', 'delivery-1')[1] is False
    assert store.claim(other) is None
    claimed = store.claim(tenant)
    assert claimed['id'] == job['id'] and store.claim(tenant) is None
    assert store.finish(tenant, claimed, error_code='source_unreachable', retry=True) == 'queued'
    store.save_items(tenant, source['id'], [{'kind': 'product', 'external_id': '1', 'local_ref': 'sku_1',
                                              'fields': {'price': 5}, 'source_updated': 1, 'removed': False}])
    assert store.items(other, source['id']) == {} and store.items(tenant, source['id'])['1']['fields'] == {'price': 5}
    change = store.create_changeset(tenant, source['id'], 'sync', {'reasons': []}, [{'n': 0, 'action': 'create'}])
    assert store.get_changeset(other, change['id']) is None
    updated = store.update_changeset(tenant, change['id'], change['version'], state='applied',
                                     before_docs={'catalog.json': {'version': 1, 'categories': []}}, after_revisions={})
    assert updated['can_undo'] and store.list_changesets(tenant)[0]['can_undo']
    with pytest.raises(ValueError):
        store.update_changeset(tenant, change['id'], change['version'], state='rejected')
    # Permission records: written with the source, ended on withdrawal, never deletable or visible elsewhere.
    site = store.create_source(tenant, 'website', 'shop.example.test', {'host': 'shop.example.test'}, {},
                               {'statement': 'I confirm', 'terms_version': sync.TERMS_VERSION, 'account': 'owner@example.test',
                                'role': 'business_owner', 'domains': ['shop.example.test'], 'data': ['public website pages']})
    store.update_source(tenant, site['id'], status='disconnected', actor='owner@example.test')
    ended = next(row for row in store.list_consents(tenant) if row['source_id'] == site['id'])
    assert ended['end_reason'] == 'withdrawn' and ended['ended_by'] == 'owner@example.test' and ended['statement'] == 'I confirm'
    assert len(store.list_consents(tenant)) == 2 and store.list_consents(other) == []
    import psycopg
    with session_store.postgres_connection(tenant) as db:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with db.transaction():
                db.execute('DELETE FROM v7_private.sync_consents')
    with session_store.postgres_connection(other) as db:
        for table in ('sync_sources', 'sync_jobs', 'sync_items', 'sync_changesets', 'sync_consents'):
            assert db.execute(f'SELECT COUNT(*) FROM v7_private.{table}').fetchone()[0] == 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with db.transaction():
                db.execute("INSERT INTO v7_private.sync_jobs(id,tenant,source_id,kind,event_key,payload,state,created,updated) "
                           "VALUES(%s,%s,%s,'full','forged','{}','queued',0,0)", ('f' * 32, tenant, source['id']))
    admin = pg_runtime['admin']
    for role in ('anon', 'authenticated', 'service_role'):
        for table in ('sync_sources', 'sync_jobs', 'sync_items', 'sync_changesets', 'sync_work_tenants', 'sync_consents'):
            assert not admin.execute('SELECT has_table_privilege(%s,%s,%s)', (role, 'v7_private.' + table, 'SELECT')).fetchone()[0]
