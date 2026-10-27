"""Snapshot freshness, tenant isolation and mutation boundaries."""
from concurrent.futures import ThreadPoolExecutor
import json
from threading import Barrier

import pytest

from retrieval.storage import Storage
from service.business_read_cache import snapshot


def stores(tmp_path, monkeypatch):
    monkeypatch.setenv('V7_STORAGE_BACKEND', 'sqlite')
    for tenant, price in [('ALPHA', 20), ('BETA', 30)]:
        root = tmp_path / tenant
        root.mkdir()
        (root / 'catalog.json').write_text(json.dumps({'price': price}), encoding='utf-8')
    return Storage('ALPHA', base_dir=tmp_path)


def test_repeated_reads_and_requests_reuse_only_current_immutable_data(tmp_path, monkeypatch):
    storage = stores(tmp_path, monkeypatch)
    from retrieval import storage as module
    original = module._read_json
    reads = []

    def read(path):
        reads.append(path.name)
        return original(path)

    monkeypatch.setattr(module, '_read_json', read)
    with snapshot(storage, 'ALPHA'):
        storage.read_json('ALPHA', 'catalog.json')['price'] = 999
        assert storage.read_json('ALPHA', 'catalog.json') == {'price': 20}
        assert storage.read_json_many('ALPHA', ('catalog.json', 'faq.json')) == {'catalog.json': {'price': 20}}
    with snapshot(storage, 'ALPHA'):
        assert storage.read_json('ALPHA', 'catalog.json')['price'] == 20
    assert reads.count('catalog.json') == 1
    # An independent writer does not call this process's invalidator.
    storage.file_path('ALPHA', 'catalog.json').write_text('{"price":40}', encoding='utf-8')
    with snapshot(storage, 'ALPHA'):
        assert storage.read_json('ALPHA', 'catalog.json')['price'] == 40
    assert reads.count('catalog.json') == 2


def test_deleted_data_and_authority_are_never_served_from_public_cache(tmp_path, monkeypatch):
    storage = stores(tmp_path, monkeypatch)
    account = storage.file_path('ALPHA', 'owner_accounts.json')
    account.write_text('{"revision":1}', encoding='utf-8')
    with snapshot(storage, 'ALPHA'):
        assert storage.read_json('ALPHA', 'owner_accounts.json')['revision'] == 1
        account.write_text('{"revision":2}', encoding='utf-8')
        assert storage.read_json('ALPHA', 'owner_accounts.json')['revision'] == 2
    storage.file_path('ALPHA', 'catalog.json').unlink()
    with snapshot(storage, 'ALPHA'), pytest.raises(FileNotFoundError):
        storage.read_json('ALPHA', 'catalog.json')


def test_concurrent_tenants_and_optional_corruption_are_isolated(tmp_path, monkeypatch):
    storage = stores(tmp_path, monkeypatch)
    storage.file_path('ALPHA', 'faq.json').write_text('{broken', encoding='utf-8')
    barrier = Barrier(2)

    def read(tenant):
        with snapshot(storage, tenant):
            barrier.wait(timeout=5)
            if tenant == 'ALPHA':
                with pytest.raises(ValueError):
                    storage.read_json(tenant, 'faq.json')
            return storage.read_json(tenant, 'catalog.json')['price']

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert list(workers.map(read, ['ALPHA', 'BETA'])) == [20, 30]


def test_native_versioned_cache_detects_external_write_and_pool_resets_scope(pg_runtime, monkeypatch):
    from service import session_store, postgres_pool
    monkeypatch.setenv('V7_POSTGRES_POOL_ENABLED', 'true')
    monkeypatch.delenv('V7_PRELOAD_MASTER_PID', raising=False)
    tenant, other = pg_runtime['tenant'], pg_runtime['other']
    storage = Storage(tenant)
    try:
        with snapshot(storage, tenant):
            first = storage.read_json(tenant, 'store_info.json')
        # Simulate another worker changing the document without invalidating
        # the Python cache in this process.
        with session_store.postgres_connection(tenant) as db:
            db.execute('UPDATE v7_private.business_documents SET payload=%s '
                       "WHERE tenant=%s AND filename='store_info.json'",
                       (json.dumps({**first, 'name': 'Changed by another worker'}), tenant))
        with snapshot(storage, tenant):
            assert storage.read_json(tenant, 'store_info.json')['name'] == 'Changed by another worker'
        with session_store.postgres_connection(tenant, repeatable_read=True) as db:
            assert db.execute('SELECT current_setting(\'v7.tenant\')').fetchone()[0] == tenant
        with pytest.raises(ValueError, match='synthetic rollback'):
            with session_store.postgres_connection(other) as db:
                assert db.execute('SELECT count(*) FROM v7_private.business_documents WHERE tenant=%s', (tenant,)).fetchone()[0] == 0
                raise ValueError('synthetic rollback')
        with session_store.postgres_connection() as db:
            assert not db.execute("SELECT current_setting('v7.tenant', true)").fetchone()[0]
            assert db.execute('SHOW transaction_isolation').fetchone()[0] == 'read committed'
    finally:
        postgres_pool.close_pools()
