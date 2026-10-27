"""Durable, idempotent fan-out of noncritical pipeline telemetry only.

Payloads stay in tenant-scoped events. A private ownership index permits restart
recovery without granting the worker cross-tenant event access. Critical history,
CRM, billing and audit writes retain their synchronous paths.
"""
import atexit
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import os
from queue import Queue, Empty, Full
import re
from threading import Event, Lock, Thread
import uuid

from service import analytics_db, session_store

_batch = ContextVar('v7_pipeline_telemetry_batch', default=None)
_wake = Queue(maxsize=64)
_stop = Event()
_lock = Lock()
_thread = None
_scheduled = {}
_TYPES = {'pipeline_in', 'pipeline_out', 'pipeline_turn'}
_FIELDS = {'mode', 'rid', 'intent', 'ok', 'guarded', 'channel', 'text_len', 'reply_len'}
_JOB = re.compile(r'telemetry:[a-f0-9]{32}\Z')


def safe_meta(meta):
    return {key: value for key, value in meta.items() if key in _FIELDS and (
        type(value) is bool or (type(value) in (int, float) and 0 <= value <= 100000)
        or isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,80}', value)
        and not value.startswith(('sk-', 'sk_', 'whsec_', 'Bearer')))}


def defer(event_type, meta):
    current = _batch.get()
    if current is None or event_type not in _TYPES or len(current['rows']) >= 3:
        return False
    current['rows'].append({'event_type': event_type, 'meta': safe_meta(meta)})
    return True


def failure(phase, exc):
    from service.chat_diagnostics import emit
    emit('chat_optional_failure', phase=phase, error_type=type(exc).__name__)


@contextmanager
def collect(tenant, channel, session_id):
    enabled = os.getenv('V7_ASYNC_TELEMETRY', 'true' if os.getenv('RENDER') == 'true' else 'false') == 'true'
    if not enabled or channel == 'test':
        yield
        return
    current = {'rows': []}
    token = _batch.set(current)
    try:
        yield
    finally:
        _batch.reset(token)
        if current['rows']:
            # The same identifiers also cover an ambiguous DB commit: replay
            # and synchronous fallback cannot create duplicate original events.
            job_id = 'telemetry:' + uuid.uuid4().hex
            try:
                from service.chat_diagnostics import phase
                with phase('telemetry_enqueue'):
                    enqueue(tenant, channel, session_id, current['rows'], job_id=job_id)
            except Exception as exc:
                failure('telemetry_enqueue', exc)
                for index, row in enumerate(current['rows']):
                    try:
                        analytics_db._insert_event(tenant=tenant, channel=channel, session_id=session_id,
                            event_type=row['event_type'], message_id=job_id + ':' + str(index),
                            meta_json=json.dumps(row['meta']))
                    except Exception as fallback:
                        failure('telemetry_fallback', fallback)


@contextmanager
def connection(tenant):
    analytics_db._ensure_ready()
    tenant = analytics_db._norm_tenant(tenant)
    if not isinstance(tenant, str) or not session_store._TENANT_KEY.fullmatch(tenant):
        raise ValueError('invalid_telemetry_tenant')
    if analytics_db._using_postgres():
        with session_store.postgres_connection(tenant) as db:
            # Enqueue and drain share this transaction lock, including index
            # insertion/removal. No enqueue can be lost during an empty drain.
            lock_key = int.from_bytes(hashlib.sha256(('telemetry:' + tenant).encode()).digest()[:8], 'big', signed=True)
            db.execute('SELECT pg_advisory_xact_lock(%s)', (lock_key,))
            yield db, '%s', 'v7_private.events', 'v7_private.telemetry_pending_tenants', tenant
    else:
        with analytics_db._conn() as db:
            db.execute('BEGIN IMMEDIATE')
            yield db, '?', 'events', None, tenant


def enqueue(tenant, channel, session_id, rows, *, job_id=None):
    job_id = job_id or 'telemetry:' + uuid.uuid4().hex
    if not isinstance(job_id, str) or not _JOB.fullmatch(job_id):
        raise ValueError('invalid_telemetry_job_id')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 3 or any(
            not isinstance(row, dict) or row.get('event_type') not in _TYPES
            or not isinstance(row.get('meta'), dict) for row in rows):
        raise ValueError('invalid_telemetry_batch')
    rows = [{'event_type': row['event_type'], 'meta': safe_meta(row['meta'])} for row in rows]
    with connection(tenant) as (db, mark, table, ownership, tenant):
        if ownership:
            db.execute(f'INSERT INTO {ownership}(tenant) VALUES({mark}) ON CONFLICT DO NOTHING', (tenant,))
        db.execute(f'INSERT INTO {table}(ts_utc,tenant,channel,session_id,event_type,message_id,meta_json) '
            'VALUES(' + ','.join([mark] * 7) + ') ON CONFLICT(tenant,event_type,message_id) '
            "WHERE message_id IS NOT NULL AND message_id != '' DO NOTHING",
            (analytics_db._utc_now(), tenant, analytics_db._norm_channel(channel), str(session_id or 'unknown')[:256],
             'pipeline_pending', job_id, json.dumps({'version': 1, 'events': rows}, separators=(',', ':'))))
    # Persistence has succeeded. Scheduling failures must never cause a second
    # synchronous fallback; restart recovery will find this durable job.
    try:
        if not kick(tenant):
            drain(tenant)
    except Exception as exc:
        failure('telemetry_schedule', exc)


def drain(tenant, limit=20):
    count = 0
    with connection(tenant) as (db, mark, table, ownership, tenant):
        rows = db.execute(f'SELECT id, ts_utc, channel, session_id, message_id, meta_json FROM {table} '
            f'WHERE tenant={mark} AND event_type=\'pipeline_pending\' ORDER BY id LIMIT {mark}',
            (tenant, min(100, max(1, limit)))).fetchall()
        for identifier, timestamp, channel, session_id, job_id, encoded in rows:
            try:
                if not isinstance(encoded, str) or len(encoded) > 8192 or not isinstance(job_id, str) or not _JOB.fullmatch(job_id):
                    raise ValueError('invalid_telemetry_job')
                payload = json.loads(encoded)
                events = payload['events']
                if payload.get('version') != 1 or not isinstance(events, list) or not 1 <= len(events) <= 3 or any(
                        not isinstance(row, dict) or row.get('event_type') not in _TYPES
                        or not isinstance(row.get('meta'), dict) for row in events):
                    raise ValueError('invalid_telemetry_job')
            except (ValueError, KeyError, TypeError, AttributeError):
                db.execute(f'UPDATE {table} SET event_type=\'pipeline_dead_letter\' '
                           f'WHERE tenant={mark} AND id={mark}', (tenant, identifier))
                continue
            for index, row in enumerate(events):
                db.execute(f'INSERT INTO {table}(ts_utc,tenant,channel,session_id,event_type,message_id,meta_json) '
                    'VALUES(' + ','.join([mark] * 7) + ') ON CONFLICT(tenant,event_type,message_id) '
                    "WHERE message_id IS NOT NULL AND message_id != '' DO NOTHING",
                    (timestamp, tenant, channel, session_id, row['event_type'],
                     job_id + ':' + str(index), json.dumps(safe_meta(row['meta']))))
            db.execute(f'DELETE FROM {table} WHERE tenant={mark} AND id={mark} '
                       'AND event_type=\'pipeline_pending\'', (tenant, identifier))
            count += 1
        if ownership:
            db.execute(f'DELETE FROM {ownership} WHERE tenant={mark} AND NOT EXISTS('
                       f'SELECT 1 FROM {table} WHERE tenant={mark} AND event_type=\'pipeline_pending\')', (tenant, tenant))
    return count


def recover():
    """Keyset pagination covers every queued tenant, including legacy accounts."""
    after = ''
    while not _stop.is_set():
        if analytics_db._using_postgres():
            with session_store.postgres_connection() as db:
                tenants = db.execute('SELECT tenant FROM v7_private.telemetry_pending_tenants '
                                     'WHERE tenant>%s ORDER BY tenant LIMIT 100', (after,)).fetchall()
        else:
            analytics_db._ensure_ready()
            with analytics_db._conn() as db:
                tenants = db.execute("SELECT DISTINCT tenant FROM events WHERE event_type='pipeline_pending' "
                                     'AND tenant>? ORDER BY tenant LIMIT 100', (after,)).fetchall()
        if not tenants:
            return
        for row in tenants:
            after = row[0]
            try:
                while not _stop.is_set() and drain(after) == 20:
                    pass
            except Exception as exc:
                # A failing tenant must not prevent recovery of other tenants.
                failure('telemetry_recovery', exc)


def _run():
    # Periodic durable recovery also retries transient failures and queue
    # saturation without requiring a subsequent customer request.
    import time
    next_recovery = 0
    backoff = 1
    while not _stop.is_set():
        if time.monotonic() >= next_recovery:
            try:
                recover()
                backoff = 1
            except Exception as exc:
                failure('telemetry_recovery', exc)
                backoff = min(30, backoff * 2)
            next_recovery = time.monotonic() + (30 if backoff == 1 else backoff)
        try:
            tenant = _wake.get(timeout=1)
        except Empty:
            continue
        generation = None
        try:
            while not _stop.is_set():
                with _lock:
                    generation = _scheduled.get(tenant)
                while not _stop.is_set() and drain(tenant) == 20:
                    pass
                with _lock:
                    if _scheduled.get(tenant) == generation:
                        _scheduled.pop(tenant, None)
                        break
        except Exception as exc:
            failure('telemetry_worker', exc)
            with _lock:
                _scheduled.pop(tenant, None)
        finally:
            _wake.task_done()


def start():
    global _thread
    with _lock:
        if _stop.is_set():
            return False
        if _thread is None or not _thread.is_alive():
            _thread = Thread(target=_run, daemon=True, name='v7-telemetry')
            _thread.start()
        return True


def kick(tenant):
    if not start():
        return False
    with _lock:
        if tenant in _scheduled:
            _scheduled[tenant] += 1
        else:
            try:
                _wake.put_nowait(tenant)
                _scheduled[tenant] = 1
            except Full:
                return False
        return True


def shutdown():
    _stop.set()
    if _thread is not None:
        _thread.join(timeout=3)


atexit.register(shutdown)
