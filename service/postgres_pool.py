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
def connection(dsn, ca_file, *, initialize):
    import psycopg
    enabled = os.getenv('V7_POSTGRES_POOL_ENABLED', 'true' if os.getenv('RENDER') == 'true' else 'false') == 'true'
    # Gunicorn preloads the application in its master. Never create pool
    # threads or sockets there: workers create their own pool after the fork.
    enabled = enabled and os.getenv('V7_PRELOAD_MASTER_PID') != str(os.getpid())
    options = dict(sslmode='verify-full', sslrootcert=ca_file, connect_timeout=15, autocommit=False)
    if not enabled:
        with psycopg.connect(dsn, **options) as db:
            initialize(db)
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
                name='v7-restricted-db')
        pool = _pools[key]
    # The mandatory read-only initializer checks liveness AND every security
    # constraint on each checkout. A separate SELECT 1 adds a redundant RTT.
    started = time.monotonic()
    for attempt in range(2):
        ready, db = False, None
        try:
            with pool.connection(timeout=15) as db:
                acquired_ms = round((time.monotonic()-started)*1000, 2)
                # Transaction-local scope disappears on commit/rollback. Reset
                # isolation before running fresh validation on every borrower.
                db.isolation_level = psycopg.IsolationLevel.READ_COMMITTED
                scope_started = time.monotonic()
                initialize(db)
                from service.chat_diagnostics import emit
                emit('db_connection', outcome='pooled', elapsed_ms=acquired_ms)
                emit('chat_phase', phase='db_scope_validation', outcome='completed',
                     elapsed_ms=round((time.monotonic()-scope_started)*1000, 2))
                ready = True
                yield db
            return
        except psycopg.Error:
            # Only the read-only initializer has run. Never replay anything
            # after yield, including a lost COMMIT acknowledgement or a caller
            # error: that could duplicate a payment, audit or history write.
            if not ready and attempt == 0 and db is not None and db.broken:
                from service.chat_diagnostics import emit
                emit('db_connection', outcome='retry_before_scope')
                continue
            raise
        except Exception as exc:
            # Never log DSNs, credentials or arbitrary database error text.
            from service.chat_diagnostics import emit
            emit('db_connection', outcome='failed', error_type=type(exc).__name__)
            raise
