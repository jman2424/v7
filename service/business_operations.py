"""Durable tenant-scoped inbox, draft approval and confirmed action outcomes."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import re
import secrets
import sqlite3
import time

from service import session_store

_ID = re.compile(r'[a-f0-9]{32}\Z')
_COLUMNS = ('id', 'tenant', 'channel', 'event_key', 'conversation_id', 'source_address', 'payload',
            'state', 'reply', 'provider_id', 'error_code', 'lease', 'lease_until', 'created', 'updated', 'version')
_SCHEMA = '''CREATE TABLE IF NOT EXISTS business_operations (
    id TEXT PRIMARY KEY, tenant TEXT NOT NULL, channel TEXT NOT NULL, event_key TEXT NOT NULL,
    conversation_id TEXT NOT NULL, source_address TEXT NOT NULL, payload TEXT NOT NULL,
    state TEXT NOT NULL, reply TEXT NOT NULL DEFAULT '', provider_id TEXT NOT NULL DEFAULT '',
    error_code TEXT NOT NULL DEFAULT '', lease TEXT NOT NULL DEFAULT '', lease_until REAL NOT NULL DEFAULT 0,
    created REAL NOT NULL, updated REAL NOT NULL, version INTEGER NOT NULL DEFAULT 1,
    UNIQUE(tenant,channel,event_key))'''


@contextmanager
def connection(tenant, *, write=False):
    if not isinstance(tenant, str) or not session_store._TENANT_KEY.fullmatch(tenant):
        raise ValueError('invalid_operation_tenant')
    if session_store._using_postgres():
        from psycopg.rows import dict_row
        from service.subscriptions import _PostgresBillingCursor
        with session_store.postgres_connection(tenant) as db:
            with db.cursor(row_factory=dict_row) as cursor:
                if write:
                    lock = int.from_bytes(hashlib.sha256(('operations:'+tenant).encode()).digest()[:8], 'big', signed=True)
                    cursor.execute('SELECT pg_advisory_xact_lock(%s)', (lock,))
                yield _PostgresBillingCursor(cursor)
    else:
        with session_store.connection() as db:
            db.row_factory = sqlite3.Row
            db.execute(_SCHEMA)
            db.execute('CREATE INDEX IF NOT EXISTS business_operation_due ON business_operations(tenant,state,created)')
            db.execute('CREATE INDEX IF NOT EXISTS business_operation_conversation ON business_operations(tenant,conversation_id,created)')
            db.commit()
            if write:
                db.execute('BEGIN IMMEDIATE')
            yield db


def _decode(row):
    if row is None:
        return None
    result = dict(row)
    result['payload'] = json.loads(result['payload'])
    return result


def get(tenant, operation_id):
    if not isinstance(operation_id, str) or not _ID.fullmatch(operation_id):
        raise ValueError('invalid_operation_id')
    with connection(tenant) as db:
        return _decode(db.execute('SELECT * FROM business_operations WHERE tenant=? AND id=?',
                                  (tenant, operation_id)).fetchone())


def enqueue(tenant, channel, event_key, conversation_id, source_address, payload, *, daily_limit=50):
    if (channel not in {'email', 'phone', 'workflow'} or not isinstance(event_key, str)
            or not 1 <= len(event_key) <= 200 or not event_key.isascii()
            or not isinstance(conversation_id, str) or not 1 <= len(conversation_id) <= 200
            or not isinstance(source_address, str) or len(source_address) > 254
            or not isinstance(payload, dict) or type(daily_limit) is not int or not 1 <= daily_limit <= 1000):
        raise ValueError('invalid_operation')
    encoded = json.dumps(payload, allow_nan=False, separators=(',', ':'))
    if len(encoded.encode()) > 20000:
        raise ValueError('operation_too_large')
    now, identifier = time.time(), secrets.token_hex(16)
    # The deduplication key need not retain provider message/call identifiers.
    event_key = hashlib.sha256((channel+'\0'+event_key).encode()).hexdigest()
    with connection(tenant, write=True) as db:
        existing = db.execute('SELECT * FROM business_operations WHERE tenant=? AND channel=? AND event_key=?',
                              (tenant, channel, event_key)).fetchone()
        if existing:
            stored = _decode(existing)
            if stored['state'] == 'expired':
                return stored, False
            if (stored['source_address'] != source_address or stored['conversation_id'] != conversation_id
                    or stored['payload'].get('recipient') != payload.get('recipient')):
                raise ValueError('operation_event_conflict')
            return stored, False
        count = db.execute('SELECT COUNT(*) AS n FROM business_operations WHERE tenant=? AND channel=? AND created>=?',
                           (tenant, channel, now-now%86400)).fetchone()['n']
        if count >= daily_limit:
            raise ValueError('channel_daily_limit')
        # Provider delivery proves no sender identity. This is only an abuse cap,
        # never permission to disclose private account/customer records.
        burst = db.execute('SELECT COUNT(*) AS n FROM business_operations WHERE tenant=? AND channel=? AND source_address=? AND created>?',
                           (tenant, channel, source_address, now-3600)).fetchone()['n']
        if burst >= (10 if channel == 'email' else 36):
            raise ValueError('channel_sender_limit')
        if channel == 'phone' and db.execute('SELECT COUNT(*) AS n FROM business_operations WHERE tenant=? AND conversation_id=?',
                                             (tenant, conversation_id)).fetchone()['n'] >= 12:
            raise ValueError('call_turn_limit')
        db.execute('INSERT INTO business_operations(id,tenant,channel,event_key,conversation_id,source_address,payload,state,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)',
                   (identifier, tenant, channel, event_key, conversation_id, source_address, encoded, 'queued', now, now))
    return get(tenant, identifier), True


def claim(tenant):
    now, lease = time.time(), secrets.token_hex(16)
    with connection(tenant, write=True) as db:
        # A crash after starting a send is ambiguous. Never silently send again.
        db.execute("UPDATE business_operations SET state='uncertain',error_code='send_interrupted',lease='',lease_until=0,version=version+1 WHERE tenant=? AND state='sending' AND lease_until<?", (tenant, now))
        db.execute("UPDATE business_operations SET state='needs_review',error_code='generation_interrupted',lease='',lease_until=0,version=version+1 WHERE tenant=? AND state='processing' AND lease_until<?", (tenant, now))
        db.execute("UPDATE business_operations SET state='uncertain',error_code='action_interrupted',lease='',lease_until=0,version=version+1 WHERE tenant=? AND state='executing' AND lease_until<?", (tenant, now))
        row = db.execute("SELECT * FROM business_operations WHERE tenant=? AND state IN ('queued','approved') ORDER BY created LIMIT 1", (tenant,)).fetchone()
        if row is None:
            return None
        state = 'sending' if row['state'] == 'approved' else 'processing'
        db.execute('UPDATE business_operations SET state=?,lease=?,lease_until=?,updated=?,version=version+1 WHERE tenant=? AND id=? AND version=?',
                   (state, lease, now+90, now, tenant, row['id'], row['version']))
        result = dict(row)
        result.update(state=state, lease=lease, lease_until=now+90, version=row['version']+1)
        return _decode(result)


def finish(tenant, operation_id, lease, state, *, reply='', provider_id='', error_code=''):
    if state not in {'needs_review', 'approved', 'completed', 'failed', 'uncertain', 'rejected'}:
        raise ValueError('invalid_operation_state')
    if (not isinstance(reply, str) or len(reply) > 6000 or not isinstance(provider_id, str) or len(provider_id) > 200
            or not isinstance(error_code, str) or error_code and not re.fullmatch(r'[a-z_]{1,80}', error_code)):
        raise ValueError('invalid_operation_outcome')
    with connection(tenant, write=True) as db:
        result = db.execute('UPDATE business_operations SET state=?,reply=?,provider_id=?,error_code=?,lease=\'\',lease_until=0,updated=?,version=version+1 WHERE tenant=? AND id=? AND lease=? AND lease_until>?',
                            (state, reply, provider_id, error_code, time.time(), tenant, operation_id, lease, time.time()))
        return result.rowcount == 1


def save_payload(tenant, operation_id, lease, payload):
    encoded = json.dumps(payload, allow_nan=False, separators=(',', ':'))
    if not isinstance(payload, dict) or len(encoded.encode()) > 20000:
        raise ValueError('operation_too_large')
    with connection(tenant, write=True) as db:
        return db.execute('UPDATE business_operations SET payload=?,updated=? WHERE tenant=? AND id=? AND lease=? AND lease_until>?',
                          (encoded, time.time(), tenant, operation_id, lease, time.time())).rowcount == 1


def expire_call_turn(tenant, operation_id):
    """Stop an unheard pending reply spending further queued work after timeout."""
    with connection(tenant, write=True) as db:
        return db.execute("UPDATE business_operations SET state='needs_review',error_code='call_reply_timed_out',lease='',lease_until=0,updated=?,version=version+1 WHERE tenant=? AND id=? AND channel='phone' AND state IN ('queued','processing')",
                          (time.time(), tenant, operation_id)).rowcount == 1


def decide(tenant, operation_id, version, decision, *, reply=None):
    if type(version) is not int or decision not in {'approve', 'reject', 'complete'}:
        raise ValueError('invalid_operation_decision')
    with connection(tenant, write=True) as db:
        row = db.execute('SELECT * FROM business_operations WHERE tenant=? AND id=?', (tenant, operation_id)).fetchone()
        if row is None:
            raise LookupError('operation_not_found')
        if row['version'] != version or row['state'] != 'needs_review':
            raise ValueError('operation_changed')
        text = row['reply'] if reply is None else reply
        if not isinstance(text, str) or len(text) > 6000 or '\x00' in text:
            raise ValueError('invalid_operation_reply')
        if decision == 'approve' and (row['channel'] != 'email' or not text.strip()):
            raise ValueError('operation_requires_manual_followup')
        state = {'approve': 'approved', 'reject': 'rejected', 'complete': 'completed'}[decision]
        db.execute('UPDATE business_operations SET state=?,reply=?,updated=?,version=version+1 WHERE tenant=? AND id=? AND version=?',
                   (state, text.strip(), time.time(), tenant, operation_id, version))
    return get(tenant, operation_id)


def listing(tenant, limit=50):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('invalid_operation_limit')
    with connection(tenant) as db:
        return [_decode(row) for row in db.execute("SELECT * FROM business_operations WHERE tenant=? AND state!='expired' ORDER BY created DESC LIMIT ?", (tenant, limit)).fetchall()]


def begin_action(tenant, operation_id, version, payload):
    """Freeze an owner-approved action before invoking the existing action tool."""
    if type(version) is not int or not isinstance(payload, dict):
        raise ValueError('invalid_operation_action')
    with connection(tenant, write=True) as db:
        row = db.execute('SELECT * FROM business_operations WHERE tenant=? AND id=?', (tenant, operation_id)).fetchone()
        if row is None:
            raise LookupError('operation_not_found')
        if row['state'] != 'needs_review' or row['version'] != version:
            raise ValueError('operation_changed')
        job = _decode(row)
        job['payload']['approved_action'] = payload
        encoded = json.dumps(job['payload'], allow_nan=False, separators=(',', ':'))
        if len(encoded.encode()) > 20000:
            raise ValueError('operation_too_large')
        lease, now = secrets.token_hex(16), time.time()
        db.execute("UPDATE business_operations SET payload=?,state='executing',lease=?,lease_until=?,updated=?,version=version+1 WHERE tenant=? AND id=? AND version=?",
                   (encoded, lease, now+90, now, tenant, operation_id, version))
        job.update(lease=lease, state='executing', version=version+1)
        return job


def purge(tenant, channel, retention_days):
    if channel not in {'email', 'phone'} or type(retention_days) is not int or not 1 <= retention_days <= 90:
        raise ValueError('invalid_operation_retention')
    with connection(tenant) as db:
        rows = [_decode(row) for row in db.execute("SELECT * FROM business_operations WHERE tenant=? AND channel=? AND created<? AND state NOT IN ('processing','sending','executing','retaining','expired') ORDER BY created LIMIT 100",
                                                   (tenant, channel, time.time()-retention_days*86400)).fetchall()]
    count = 0
    for row in rows:
        memory = None
        if channel == 'email' and row['conversation_id']:
            from service.conversation_memory import ConversationMemory
            memory = ConversationMemory(None, tenant)
            # Initialise the optional SQLite table before acquiring the queue
            # write transaction. Both stores use the same private database.
            with memory._connection():
                pass
        marker = {key: row['payload'][key] for key in ('cleanup_thread_hash', 'cleanup_attempted', 'cleanup_outcome')
                  if key in row['payload']}
        with connection(tenant, write=True) as db:
            changed = db.execute("UPDATE business_operations SET conversation_id='',source_address='',payload=?,reply='',provider_id='',state='expired',lease='',lease_until=0,version=version+1 WHERE tenant=? AND id=? AND version=?",
                                 (json.dumps(marker), tenant, row['id'], row['version'])).rowcount
            if changed and memory is not None:
                # Atomic with the version-bound queue expiry: a concurrent
                # generation/approval must not lose its model context. Failure
                # rolls back expiry so later maintenance can retry safely.
                db.execute('DELETE FROM conversation_memory WHERE tenant=? AND session_hash=?',
                           (tenant, memory._identity(row['conversation_id'])))
            count += changed
    with connection(tenant, write=True) as db:
        db.execute("DELETE FROM business_operations WHERE tenant=? AND channel=? AND state='expired' AND created<?", (tenant, channel, time.time()-90*86400))
        return count


def cleanup_candidates(tenant, days):
    with connection(tenant) as db:
        return [_decode(row) for row in db.execute("SELECT * FROM business_operations WHERE tenant=? AND channel='email' AND created<? AND state IN ('completed','rejected') ORDER BY created LIMIT 100",
                                                  (tenant, time.time()-days*86400)).fetchall()]


def thread_operations(tenant, inbox, thread):
    with connection(tenant) as db:
        rows = [_decode(row) for row in db.execute("SELECT * FROM business_operations WHERE tenant=? AND channel='email' AND payload LIKE ? LIMIT 101",
                                                  (tenant, '%'+thread+'%')).fetchall()]
    return [row for row in rows if row['payload'].get('inbox_id') == inbox and row['payload'].get('thread_id') == thread]


def cleanup_hash(inbox, thread):
    return hashlib.sha256((inbox+'\0'+thread).encode()).hexdigest()


def claim_cleanup(tenant, row):
    payload = {**row['payload'], 'cleanup_source_state': row['state']}
    lease, now = secrets.token_hex(16), time.time()
    with connection(tenant, write=True) as db:
        changed = db.execute("UPDATE business_operations SET state='retaining',payload=?,lease=?,lease_until=?,version=version+1 WHERE tenant=? AND id=? AND version=? AND state IN ('completed','rejected')",
                             (json.dumps(payload), lease, now+90, tenant, row['id'], row['version'])).rowcount
    return {**row, 'payload': payload, 'lease': lease} if changed else None


def cleanup_receipt(tenant, row, outcome):
    if outcome not in {'trashed', 'skipped', 'failed', 'restored'}:
        raise ValueError('invalid_cleanup_outcome')
    payload = {**row['payload'], 'cleanup_outcome': outcome}
    with connection(tenant, write=True) as db:
        return db.execute('UPDATE business_operations SET state=?,payload=?,error_code=?,lease=\'\',lease_until=0,version=version+1 WHERE tenant=? AND id=? AND lease=? AND lease_until>?',
            (payload.pop('cleanup_source_state'), json.dumps(payload), 'retention_'+outcome,
             tenant, row['id'], row['lease'], time.time())).rowcount == 1


def recover_cleanup(tenant):
    with connection(tenant, write=True) as db:
        rows = [_decode(row) for row in db.execute("SELECT * FROM business_operations WHERE tenant=? AND state='retaining' AND lease_until<?", (tenant, time.time())).fetchall()]
        for row in rows:
            payload = {**row['payload'], 'cleanup_outcome': 'failed'}
            db.execute("UPDATE business_operations SET state=?,payload=?,error_code='retention_failed',lease='',lease_until=0,version=version+1 WHERE tenant=? AND id=? AND lease=?",
                       (payload.pop('cleanup_source_state', 'completed'), json.dumps(payload), tenant, row['id'], row['lease']))


def previously_trashed(tenant, inbox, thread):
    marker = cleanup_hash(inbox, thread)
    with connection(tenant) as db:
        rows = db.execute("SELECT payload FROM business_operations WHERE tenant=? AND channel='email' AND (state='retaining' OR error_code IN ('retention_trashed','retention_failed')) AND payload LIKE ? LIMIT 101", (tenant, '%'+marker+'%')).fetchall()
    return any((payload := json.loads(row['payload'])).get('cleanup_thread_hash') == marker
               and payload.get('cleanup_attempted') is True
               and payload.get('cleanup_outcome') in {None, 'trashed', 'failed'} for row in rows)


def cleanup_counts(tenant):
    with connection(tenant) as db:
        return {row['error_code']: row['n'] for row in db.execute(
            "SELECT error_code,COUNT(*) AS n FROM business_operations WHERE tenant=? AND channel='email' AND error_code IN ('retention_trashed','retention_skipped','retention_failed','retention_restored') GROUP BY error_code", (tenant,)).fetchall()}
