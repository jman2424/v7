"""Background loop that runs scheduled and queued data-source synchronisation.

Jobs and leases live in the database, so a restart loses nothing and two app
processes never run the same job. Off unless V7_SYNC_WORKER is true.
"""
from __future__ import annotations

import atexit
import os
from threading import Event, Lock, Thread

from service import data_sources, sync_store

_lock, _stop, _wake = Lock(), Event(), Event()
_thread, _pid = None, None


def wake():
    _wake.set()


def run_all(container, limit=20):
    """One fair pass: a failing or busy business cannot hold the others back."""
    count = 0
    for tenant in sync_store.work_tenants():
        if count >= limit:
            break
        try:
            if container.storage.tenant_exists(tenant):
                count += data_sources.run_pending(container, tenant, limit=3)
        except Exception as exc:
            from service.chat_diagnostics import emit
            emit('chat_optional_failure', phase='business_sync_tenant', error_type=type(exc).__name__)
    return count


def _shutdown():
    _stop.set()
    _wake.set()


def start(app):
    global _thread, _pid
    if not data_sources.worker_enabled() or app.testing:
        return
    with _lock:
        if _pid == os.getpid() and _thread and _thread.is_alive():
            return
        if _pid != os.getpid():
            atexit.register(_shutdown)
        _pid = os.getpid()
        _stop.clear()

        def loop():
            while not _stop.is_set():
                _wake.clear()
                try:
                    with app.app_context():
                        run_all(app.container)
                except Exception as exc:
                    app.logger.warning('Business sync worker failed (%s)', type(exc).__name__)
                _wake.wait(30)

        _thread = Thread(target=loop, name='v7-business-sync', daemon=True)
        _thread.start()


if __name__ == '__main__':
    from app import create_app
    application = create_app()
    with application.app_context():
        print('Processed sync jobs:', run_all(getattr(application, 'container'), limit=200))
