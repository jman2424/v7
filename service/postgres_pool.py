"""Bounded per-worker connections; each borrower still validates role and RLS."""
import atexit
from contextlib import contextmanager
import hashlib
import logging
import os
from threading import RLock
import time

_pools = {}
_lock = RLock()


def close_pools():
    with _lock:
        pools = list(_pools.values())
        _pools.clear()
    for pool in pools:
        pool.close(timeout=2)


atexit.register(close_pools)


@contextmanager
def connection(dsn, ca_file):
    import psycopg
    enabled = os.getenv('V7_POSTGRES_POOL_ENABLED', 'true' if os.getenv('RENDER') == 'true' else 'false') == 'true'
    # Gunicorn preloads the application in its master. Never create pool
    # threads or sockets there: workers create their own pool after the fork.
    enabled = enabled and os.getenv('V7_PRELOAD_MASTER_PID') != str(os.getpid())
    options = dict(sslmode='verify-full', sslrootcert=ca_file, connect_timeout=15, autocommit=False)
    if not enabled:
        with psycopg.connect(dsn, **options) as db:
            yield db
        return
    from psycopg_pool import ConnectionPool
    # No DSN, credential or provider error text is written by this helper.
    logging.getLogger('psycopg.pool').setLevel(logging.CRITICAL)
    key = (os.getpid(), hashlib.sha256((dsn + '\0' + ca_file).encode()).digest())
    with _lock:
        if key not in _pools:
            if len(_pools) >= 2:
                # Credential rotation must not grow an unbounded set of pools.
                old = next(iter(_pools))
                _pools.pop(old).close(timeout=2)
            _pools[key] = ConnectionPool(conninfo=dsn, kwargs={**options, 'prepare_threshold': None},
                min_size=0, max_size=4, max_waiting=32, timeout=15, max_idle=60,
                max_lifetime=600, num_workers=1, open=True,
                check=ConnectionPool.check_connection, name='v7-restricted-db')
        pool = _pools[key]
    started = time.monotonic()
    try:
        with pool.connection(timeout=15) as db:
            # Repeatable-read callers must not leave isolation settings for
            # the next borrower. Transaction-local tenant/search_path settings
            # disappear on commit/rollback, including exceptional exits.
            db.isolation_level = psycopg.IsolationLevel.READ_COMMITTED
            from service.chat_diagnostics import emit
            emit('db_connection', outcome='pooled', elapsed_ms=round((time.monotonic()-started)*1000, 2))
            yield db
    except psycopg.Error:
        raise
    except Exception as exc:
        # Pool exceptions can include connection metadata. Diagnostics record
        # only its class; the existing caller owns outward error handling.
        from service.chat_diagnostics import emit
        emit('db_connection', outcome='failed', error_type=type(exc).__name__)
        raise
