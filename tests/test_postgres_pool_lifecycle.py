"""A liveness retry must never replay business work or an uncertain commit."""
from contextlib import contextmanager
from types import SimpleNamespace

import psycopg
import psycopg_pool
import pytest

from service import postgres_pool, session_store


@pytest.fixture
def pool_driver(monkeypatch):
    observed = SimpleNamespace(leases=0, initializations=0, writes=0, commit_failure=False)

    class Database:
        broken = False
        isolation_level = None

    class Pool:
        def __init__(self, **kwargs):
            # A second SELECT 1 is unnecessary: each lease must run the fresh
            # security initializer before any caller can use the connection.
            assert 'check' not in kwargs

        @contextmanager
        def connection(self, **kwargs):
            observed.leases += 1
            db = Database()
            yield db
            if observed.commit_failure:
                db.broken = True
                raise psycopg.OperationalError('Synthetic lost commit acknowledgement')

        def close(self, **kwargs):
            pass

    monkeypatch.setenv('V7_POSTGRES_POOL_ENABLED', 'true')
    monkeypatch.delenv('V7_PRELOAD_MASTER_PID', raising=False)
    monkeypatch.setattr(postgres_pool, '_pools', {})
    monkeypatch.setattr(psycopg_pool, 'ConnectionPool', Pool)
    yield observed
    postgres_pool.close_pools()


def test_stale_socket_is_replaced_only_before_business_work(pool_driver):
    def initialize(db):
        pool_driver.initializations += 1
        if pool_driver.initializations == 1:
            db.broken = True
            raise psycopg.OperationalError('Synthetic stale idle socket')

    with postgres_pool.connection('unit-only', 'system', initialize=initialize):
        pool_driver.writes += 1
    assert (pool_driver.leases, pool_driver.initializations, pool_driver.writes) == (2, 2, 1)


def test_caller_failure_after_a_write_is_never_replayed(pool_driver):
    with pytest.raises(psycopg.OperationalError):
        with postgres_pool.connection('unit-only', 'system', initialize=lambda db: None) as db:
            pool_driver.writes += 1
            db.broken = True
            raise psycopg.OperationalError('Synthetic failure after an important write')
    assert (pool_driver.leases, pool_driver.writes) == (1, 1)


def test_uncertain_commit_is_never_replayed(pool_driver):
    pool_driver.commit_failure = True
    with pytest.raises(psycopg.OperationalError):
        with postgres_pool.connection('unit-only', 'system', initialize=lambda db: None):
            pool_driver.writes += 1
    assert (pool_driver.leases, pool_driver.writes) == (1, 1)


def test_failed_security_validation_cannot_yield_or_retry(pool_driver):
    def initialize(db):
        pool_driver.initializations += 1
        raise RuntimeError('PostgreSQL security role or tables are not restricted')

    with pytest.raises(RuntimeError, match='not restricted'):
        with postgres_pool.connection('unit-only', 'system', initialize=initialize):
            pytest.fail('An invalid security scope reached business code')
    assert (pool_driver.leases, pool_driver.initializations) == (1, 1)


def test_native_stale_idle_connection_revalidates_scope_before_reuse(pg_runtime, monkeypatch):
    # pg_runtime accepts only an explicitly named, local disposable database.
    # Terminate only this test's own idle pooled connection, never shared work.
    monkeypatch.setenv('V7_POSTGRES_POOL_ENABLED', 'true')
    monkeypatch.delenv('V7_PRELOAD_MASTER_PID', raising=False)
    postgres_pool.close_pools()
    tenant, other = pg_runtime['tenant'], pg_runtime['other']
    try:
        with session_store.postgres_connection(tenant) as db:
            previous_pid = db.info.backend_pid
        assert pg_runtime['admin'].execute('SELECT pg_terminate_backend(%s)', (previous_pid,)).fetchone()[0]
        with session_store.postgres_connection(other) as db:
            assert db.info.backend_pid != previous_pid
            assert db.execute("SELECT current_setting('v7.tenant')").fetchone()[0] == other
            assert db.execute('SELECT count(*) FROM v7_private.business_documents WHERE tenant=%s', (tenant,)).fetchone()[0] == 0
    finally:
        postgres_pool.close_pools()
