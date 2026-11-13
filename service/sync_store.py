"""Tenant-scoped data sources, sync queue, item links and change history."""
from __future__ import annotations

from base64 import urlsafe_b64encode
from contextlib import contextmanager
import hashlib
import json
import os
import re
import secrets
import sqlite3
import time

from service import session_store

ID = re.compile(r'[a-f0-9]{32}\Z')
KINDS = ('woocommerce', 'shopify', 'custom_feed', 'upload')
SOURCE_STATES = ('connected', 'attention', 'reconnect', 'disconnected')
CHANGE_STATES = ('pending', 'applied', 'rejected', 'rolled_back', 'superseded')
MAX_ATTEMPTS = 6
_SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS sync_sources (
        id TEXT PRIMARY KEY, tenant TEXT NOT NULL, kind TEXT NOT NULL, label TEXT NOT NULL,
        config TEXT NOT NULL, secret TEXT NOT NULL DEFAULT '', status TEXT NOT NULL,
        authorisation TEXT NOT NULL, auto_sync INTEGER NOT NULL DEFAULT 0,
        auto_apply INTEGER NOT NULL DEFAULT 0, interval_minutes INTEGER NOT NULL DEFAULT 60,
        last_success REAL NOT NULL DEFAULT 0, last_attempt REAL NOT NULL DEFAULT 0,
        last_error TEXT NOT NULL DEFAULT '', next_poll REAL NOT NULL DEFAULT 0,
        created REAL NOT NULL, updated REAL NOT NULL, version INTEGER NOT NULL DEFAULT 1)''',
    'CREATE INDEX IF NOT EXISTS sync_sources_tenant ON sync_sources(tenant,created)',
    '''CREATE TABLE IF NOT EXISTS sync_jobs (
        id TEXT PRIMARY KEY, tenant TEXT NOT NULL, source_id TEXT NOT NULL, kind TEXT NOT NULL,
        event_key TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0, run_after REAL NOT NULL DEFAULT 0,
        lease TEXT NOT NULL DEFAULT '', lease_until REAL NOT NULL DEFAULT 0,
        error_code TEXT NOT NULL DEFAULT '', created REAL NOT NULL, updated REAL NOT NULL,
        UNIQUE(tenant,source_id,event_key))''',
    'CREATE INDEX IF NOT EXISTS sync_jobs_due ON sync_jobs(tenant,state,run_after)',
    '''CREATE TABLE IF NOT EXISTS sync_items (
        tenant TEXT NOT NULL, source_id TEXT NOT NULL, kind TEXT NOT NULL, external_id TEXT NOT NULL,
        local_ref TEXT NOT NULL, fields TEXT NOT NULL, source_updated REAL NOT NULL DEFAULT 0,
        removed INTEGER NOT NULL DEFAULT 0, updated REAL NOT NULL,
        PRIMARY KEY(tenant,source_id,kind,external_id))''',
    '''CREATE TABLE IF NOT EXISTS sync_changesets (
        id TEXT PRIMARY KEY, tenant TEXT NOT NULL, source_id TEXT NOT NULL, origin TEXT NOT NULL,
        state TEXT NOT NULL, summary TEXT NOT NULL, changes TEXT NOT NULL,
        before_docs TEXT NOT NULL DEFAULT '', after_revisions TEXT NOT NULL DEFAULT '',
        actor TEXT NOT NULL DEFAULT '', created REAL NOT NULL, updated REAL NOT NULL,
        version INTEGER NOT NULL DEFAULT 1)''',
    'CREATE INDEX IF NOT EXISTS sync_changesets_tenant ON sync_changesets(tenant,created)',
    'CREATE TABLE IF NOT EXISTS sync_work_tenants (tenant TEXT PRIMARY KEY)',
)
_JSON_SOURCE = ('config', 'authorisation')
_JSON_CHANGE = ('summary', 'changes')


@contextmanager
def connection(tenant, *, write=False):
    if not isinstance(tenant, str) or not session_store._TENANT_KEY.fullmatch(tenant):
        raise ValueError('invalid_sync_tenant')
    if session_store._using_postgres():
        from psycopg.rows import dict_row
        from service.subscriptions import _PostgresBillingCursor
        with session_store.postgres_connection(tenant) as db:
            with db.cursor(row_factory=dict_row) as cursor:
                if write:
                    lock = int.from_bytes(hashlib.sha256(('sync:' + tenant).encode()).digest()[:8], 'big', signed=True)
                    cursor.execute('SELECT pg_advisory_xact_lock(%s)', (lock,))
                yield _PostgresBillingCursor(cursor)
    else:
        with session_store.connection() as db:
            db.row_factory = sqlite3.Row
            for statement in _SCHEMA:
                db.execute(statement)
            db.commit()
            if write:
                db.execute('BEGIN IMMEDIATE')
            yield db


def _dump(value, limit):
    encoded = json.dumps(value, allow_nan=False, separators=(',', ':'), ensure_ascii=False)
    if len(encoded.encode()) > limit:
        raise ValueError('sync_record_too_large')
    return encoded


def _identifier(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError('invalid_sync_id')
    return value


# ---- credentials: encrypted at rest, never returned to a browser ----

def _cipher():
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    material = os.getenv('V7_SYNC_ENCRYPTION_KEY', '').strip()
    if not material:
        from flask import current_app
        material = str(current_app.secret_key or '')
    if len(material) < 32:
        raise RuntimeError('A sync encryption key of at least 32 characters is required')
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
               info=b'v7 data-source credentials v1').derive(material.encode())
    return Fernet(urlsafe_b64encode(key))


def seal(tenant, credentials):
    """Bind the ciphertext to its tenant so a copied row is useless elsewhere."""
    if not credentials:
        return ''
    return _cipher().encrypt(_dump({'tenant': tenant, 'values': credentials}, 8000).encode()).decode('ascii')


def unseal(tenant, sealed):
    if not sealed:
        return {}
    from cryptography.fernet import InvalidToken
    try:
        value = json.loads(_cipher().decrypt(sealed.encode('ascii')))
    except (InvalidToken, ValueError, UnicodeError):
        raise ValueError('sync_credentials_unreadable') from None
    if not isinstance(value, dict) or value.get('tenant') != tenant or not isinstance(value.get('values'), dict):
        raise ValueError('sync_credentials_unreadable')
    return value['values']


# ---- sources ----

def _source(row):
    if row is None:
        return None
    result = dict(row)
    for key in _JSON_SOURCE:
        result[key] = json.loads(result[key])
    result['auto_sync'], result['auto_apply'] = bool(result['auto_sync']), bool(result['auto_apply'])
    return result


def create_source(tenant, kind, label, config, credentials, authorisation, *, auto_sync=False,
                  auto_apply=False, interval_minutes=60):
    if (kind not in KINDS or not isinstance(label, str) or not 1 <= len(label.strip()) <= 80
            or not isinstance(config, dict) or not isinstance(authorisation, dict)
            or type(interval_minutes) is not int or not 15 <= interval_minutes <= 1440):
        raise ValueError('invalid_data_source')
    now, identifier = time.time(), secrets.token_hex(16)
    with connection(tenant, write=True) as db:
        count = db.execute("SELECT COUNT(*) AS n FROM sync_sources WHERE tenant=? AND status<>'disconnected'",
                           (tenant,)).fetchone()['n']
        if count >= 10:
            raise ValueError('data_source_limit')
        db.execute('INSERT INTO sync_sources(id,tenant,kind,label,config,secret,status,authorisation,auto_sync,'
                   'auto_apply,interval_minutes,next_poll,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (identifier, tenant, kind, label.strip(), _dump(config, 8000), seal(tenant, credentials),
                    'connected', _dump(authorisation, 8000), int(bool(auto_sync)), int(bool(auto_apply)),
                    interval_minutes, now if auto_sync else 0, now, now))
        db.execute('INSERT INTO sync_work_tenants(tenant) VALUES(?) ON CONFLICT DO NOTHING', (tenant,))
    return get_source(tenant, identifier)


def get_source(tenant, source_id):
    with connection(tenant) as db:
        return _source(db.execute('SELECT * FROM sync_sources WHERE tenant=? AND id=?',
                                  (tenant, _identifier(source_id))).fetchone())


def list_sources(tenant):
    with connection(tenant) as db:
        return [_source(row) for row in db.execute(
            'SELECT * FROM sync_sources WHERE tenant=? ORDER BY created', (tenant,)).fetchall()]


_SOURCE_COLUMNS = {'label', 'config', 'secret', 'status', 'authorisation', 'auto_sync', 'auto_apply',
                   'interval_minutes', 'last_success', 'last_attempt', 'last_error', 'next_poll'}


def update_source(tenant, source_id, *, expected_version=None, **changes):
    if not changes or set(changes) - _SOURCE_COLUMNS:
        raise ValueError('invalid_data_source')
    for key in _JSON_SOURCE:
        if key in changes:
            changes[key] = _dump(changes[key], 8000)
    for key in ('auto_sync', 'auto_apply'):
        if key in changes:
            changes[key] = int(bool(changes[key]))
    if 'status' in changes and changes['status'] not in SOURCE_STATES:
        raise ValueError('invalid_data_source')
    names = sorted(changes)
    sql = ('UPDATE sync_sources SET ' + ','.join(name + '=?' for name in names)
           + ',updated=?,version=version+1 WHERE tenant=? AND id=?')
    params = [changes[name] for name in names] + [time.time(), tenant, _identifier(source_id)]
    if expected_version is not None:
        sql += ' AND version=?'
        params.append(expected_version)
    with connection(tenant, write=True) as db:
        if db.execute(sql, tuple(params)).rowcount != 1:
            raise ValueError('data_source_changed')
    return get_source(tenant, source_id)


def work_tenants():
    """Tenants that have ever connected a source; holds no business data."""
    if session_store._using_postgres():
        with session_store.postgres_connection() as db:
            return [row[0] for row in db.execute('SELECT tenant FROM v7_private.sync_work_tenants ORDER BY tenant').fetchall()]
    with session_store.connection() as db:
        for statement in _SCHEMA:
            db.execute(statement)
        return [row[0] for row in db.execute('SELECT tenant FROM sync_work_tenants ORDER BY tenant').fetchall()]


# ---- queue ----

def _job(row):
    if row is None:
        return None
    result = dict(row)
    result['payload'] = json.loads(result['payload'])
    return result


def enqueue(tenant, source_id, kind, event_key, payload=None, *, delay=0):
    """Returns (job, created). A repeated event key is the same job, never a second one."""
    if (kind not in {'full', 'event'} or not isinstance(event_key, str) or not 1 <= len(event_key) <= 300):
        raise ValueError('invalid_sync_job')
    key = hashlib.sha256(event_key.encode()).hexdigest()
    now, identifier = time.time(), secrets.token_hex(16)
    with connection(tenant, write=True) as db:
        existing = db.execute('SELECT * FROM sync_jobs WHERE tenant=? AND source_id=? AND event_key=?',
                              (tenant, _identifier(source_id), key)).fetchone()
        if existing:
            return _job(existing), False
        if db.execute("SELECT COUNT(*) AS n FROM sync_jobs WHERE tenant=? AND source_id=? AND created>?",
                      (tenant, source_id, now - 3600)).fetchone()['n'] >= 2000:
            raise ValueError('sync_rate_limited')
        db.execute('INSERT INTO sync_jobs(id,tenant,source_id,kind,event_key,payload,state,run_after,created,updated) '
                   "VALUES(?,?,?,?,?,?,'queued',?,?,?)",
                   (identifier, tenant, source_id, kind, key, _dump(payload or {}, 900_000), now + delay, now, now))
        row = db.execute('SELECT * FROM sync_jobs WHERE tenant=? AND id=?', (tenant, identifier)).fetchone()
    return _job(row), True


def claim(tenant, *, job_id=None):
    now, lease = time.time(), secrets.token_hex(16)
    with connection(tenant, write=True) as db:
        # An interrupted run made no partial catalogue write (writes are atomic
        # and idempotent), so it is safe to queue it again.
        db.execute("UPDATE sync_jobs SET state='queued',lease='',lease_until=0 WHERE tenant=? AND state='processing' AND lease_until<?",
                   (tenant, now))
        if job_id:
            row = db.execute("SELECT * FROM sync_jobs WHERE tenant=? AND id=? AND state='queued'",
                             (tenant, _identifier(job_id))).fetchone()
        else:
            row = db.execute("SELECT * FROM sync_jobs WHERE tenant=? AND state='queued' AND run_after<=? ORDER BY created,id LIMIT 1",
                             (tenant, now)).fetchone()
        if row is None:
            return None
        db.execute("UPDATE sync_jobs SET state='processing',lease=?,lease_until=?,attempts=attempts+1,updated=? WHERE tenant=? AND id=?",
                   (lease, now + 900, now, tenant, row['id']))
        result = _job(row)
        result.update(state='processing', lease=lease, attempts=row['attempts'] + 1)
        return result


def finish(tenant, job, *, error_code='', retry=False):
    """Done, retried with backoff, or failed for good after the last attempt."""
    if error_code and not re.fullmatch(r'[a-z_]{1,60}', error_code):
        raise ValueError('invalid_sync_job')
    now = time.time()
    if not error_code:
        state, run_after = 'done', 0
    elif retry and job['attempts'] < MAX_ATTEMPTS:
        state, run_after = 'queued', now + min(3600, 60 * 2 ** job['attempts'])
    else:
        state, run_after = 'failed', 0
    with connection(tenant, write=True) as db:
        db.execute("UPDATE sync_jobs SET state=?,run_after=?,error_code=?,payload=CASE WHEN ?='queued' THEN payload ELSE '{}' END,"
                   "lease='',lease_until=0,updated=? WHERE tenant=? AND id=? AND lease=?",
                   (state, run_after, error_code, state, now, tenant, job['id'], job['lease']))
        db.execute("DELETE FROM sync_jobs WHERE tenant=? AND state IN ('done','failed') AND updated<?",
                   (tenant, now - 14 * 86400))
    return state


def cancel_jobs(tenant, source_id):
    with connection(tenant, write=True) as db:
        db.execute("UPDATE sync_jobs SET state='failed',error_code='source_disconnected',payload='{}',updated=? "
                   "WHERE tenant=? AND source_id=? AND state='queued'", (time.time(), tenant, _identifier(source_id)))


def job_counts(tenant, source_id=None):
    with connection(tenant) as db:
        rows = db.execute('SELECT source_id,state,error_code,COUNT(*) AS n,MAX(updated) AS latest FROM sync_jobs '
                          'WHERE tenant=? GROUP BY source_id,state,error_code', (tenant,)).fetchall()
    return [dict(row) for row in rows if source_id in (None, row['source_id'])]


# ---- item links: which V7 record came from which source record ----

def items(tenant, source_id, kind='product'):
    with connection(tenant) as db:
        rows = db.execute('SELECT * FROM sync_items WHERE tenant=? AND source_id=? AND kind=?',
                          (tenant, _identifier(source_id), kind)).fetchall()
    return {row['external_id']: {**dict(row), 'fields': json.loads(row['fields']), 'removed': bool(row['removed'])}
            for row in rows}


def save_items(tenant, source_id, rows):
    """rows: dicts with kind, external_id, local_ref, fields, source_updated, removed."""
    now = time.time()
    with connection(tenant, write=True) as db:
        for row in rows:
            db.execute('INSERT INTO sync_items(tenant,source_id,kind,external_id,local_ref,fields,source_updated,removed,updated) '
                       'VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(tenant,source_id,kind,external_id) DO UPDATE SET '
                       'local_ref=excluded.local_ref,fields=excluded.fields,source_updated=excluded.source_updated,'
                       'removed=excluded.removed,updated=excluded.updated',
                       (tenant, source_id, row['kind'], row['external_id'], row['local_ref'], _dump(row['fields'], 20000),
                        float(row.get('source_updated') or 0), int(bool(row.get('removed'))), now))


def provenance(tenant):
    """local_ref -> source id, for showing where each record came from."""
    with connection(tenant) as db:
        rows = db.execute('SELECT kind,local_ref,source_id FROM sync_items WHERE tenant=? AND removed=0', (tenant,)).fetchall()
    return {(row['kind'], row['local_ref']): row['source_id'] for row in rows}


# ---- change sets: previews, history and the data needed to undo ----

def _change(row, *, with_docs=False):
    if row is None:
        return None
    result = dict(row)
    for key in _JSON_CHANGE:
        result[key] = json.loads(result[key])
    docs = result.pop('before_docs')
    revisions = result.pop('after_revisions')
    result['can_undo'] = bool(docs) and result['state'] == 'applied'
    if with_docs:
        result['before_docs'] = json.loads(docs) if docs else {}
        result['after_revisions'] = json.loads(revisions) if revisions else {}
    return result


def create_changeset(tenant, source_id, origin, summary, changes, *, actor=''):
    if origin not in {'import', 'sync'}:
        raise ValueError('invalid_changeset')
    now, identifier = time.time(), secrets.token_hex(16)
    with connection(tenant, write=True) as db:
        # Only one open review per source: a newer plan replaces the older one.
        db.execute("UPDATE sync_changesets SET state='superseded',changes='[]',updated=?,version=version+1 "
                   "WHERE tenant=? AND source_id=? AND state='pending'", (now, tenant, _identifier(source_id)))
        db.execute('INSERT INTO sync_changesets(id,tenant,source_id,origin,state,summary,changes,actor,created,updated) '
                   "VALUES(?,?,?,?,'pending',?,?,?,?,?)",
                   (identifier, tenant, source_id, origin, _dump(summary, 20000), _dump(changes, 6_000_000),
                    str(actor)[:200], now, now))
    return get_changeset(tenant, identifier)


def get_changeset(tenant, changeset_id, *, with_docs=False):
    with connection(tenant) as db:
        return _change(db.execute('SELECT * FROM sync_changesets WHERE tenant=? AND id=?',
                                  (tenant, _identifier(changeset_id))).fetchone(), with_docs=with_docs)


def list_changesets(tenant, *, limit=30):
    with connection(tenant) as db:
        rows = db.execute('SELECT id,tenant,source_id,origin,state,summary,\'[]\' AS changes,before_docs<>\'\' AS has_docs,'
                          'actor,created,updated,version FROM sync_changesets WHERE tenant=? ORDER BY created DESC LIMIT ?',
                          (tenant, limit)).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item['summary'] = json.loads(item['summary'])
        item.pop('changes')
        item['can_undo'] = bool(item.pop('has_docs')) and item['state'] == 'applied'
        result.append(item)
    return result


def pending_changeset(tenant, source_id):
    with connection(tenant) as db:
        row = db.execute("SELECT id FROM sync_changesets WHERE tenant=? AND source_id=? AND state='pending'",
                         (tenant, _identifier(source_id))).fetchone()
    return row['id'] if row else None


def update_changeset(tenant, changeset_id, expected_version, *, state=None, changes=None, summary=None,
                     before_docs=None, after_revisions=None, actor=None):
    if state is not None and state not in CHANGE_STATES:
        raise ValueError('invalid_changeset')
    sets, params = ['updated=?', 'version=version+1'], [time.time()]
    for column, value, limit in (('changes', changes, 6_000_000), ('summary', summary, 20000),
                                 ('before_docs', before_docs, 12_000_000), ('after_revisions', after_revisions, 4000)):
        if value is not None:
            sets.append(column + '=?')
            params.append(_dump(value, limit) if value != '' else '')
    if state is not None:
        sets.append('state=?')
        params.append(state)
    if actor is not None:
        sets.append('actor=?')
        params.append(str(actor)[:200])
    with connection(tenant, write=True) as db:
        if db.execute('UPDATE sync_changesets SET ' + ','.join(sets) + ' WHERE tenant=? AND id=? AND version=?',
                      (*params, tenant, _identifier(changeset_id), expected_version)).rowcount != 1:
            raise ValueError('changeset_changed')
        # Keep undo data for the ten most recent applied changes only.
        stale = db.execute("SELECT id FROM sync_changesets WHERE tenant=? AND state='applied' AND before_docs<>'' "
                           'ORDER BY updated DESC LIMIT 100 OFFSET 10', (tenant,)).fetchall()
        for row in stale:
            db.execute("UPDATE sync_changesets SET before_docs='' WHERE tenant=? AND id=?", (tenant, row['id']))
    return get_changeset(tenant, changeset_id)
