"""Bounded conversation context shared by workers, scoped to one tenant/session."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import math
import re
import time

from service import session_store

DEFAULTS = {'enabled': True, 'history_messages': 12, 'history_tokens': 2048, 'retention_minutes': 60}
LIMITS = {'history_messages': (2, 40), 'history_tokens': (256, 16384), 'retention_minutes': (5, 10080)}


def validated(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError('invalid_memory_settings')
    result = {**DEFAULTS, **value}
    if type(result['enabled']) is not bool:
        raise ValueError('invalid_memory_enabled')
    for key, (low, high) in LIMITS.items():
        if type(result[key]) is not int or not low <= result[key] <= high:
            raise ValueError('invalid_memory_' + key)
    return result


def profile(storage, tenant):
    from service.model_settings import document
    raw = document(storage, tenant)
    return validated(raw.get('memory', {})), raw.get('memory_generation', 'initial')


def bounded_history(rows, settings=None):
    config = validated(settings or {})
    if not config['enabled'] or not isinstance(rows, list):
        return []
    result, used = [], 0
    for row in reversed(rows[-config['history_messages']:]):
        if not isinstance(row, dict) or row.get('role') not in {'user', 'assistant'} or not isinstance(row.get('content'), str):
            continue
        content = row['content'][:4000]
        # UTF-8/JSON bytes conservatively bound byte-based model tokens. Include
        # role/framing overhead; do not split a message to fit a remaining gap.
        cost = len(json.dumps({'role': row['role'], 'content': content}, ensure_ascii=False).encode('utf-8')) + 64
        if used + cost > config['history_tokens']:
            continue
        used += cost
        result.append({'role': row['role'], 'content': content})
    return list(reversed(result))


def status(storage, tenant, raw=None):
    from service import model_settings, usage_pricing
    raw = model_settings.document(storage, tenant) if raw is None else raw
    config = validated(raw.get('memory', {}))
    model = model_settings.parameter_status(storage, tenant, raw)['model']
    prices = usage_pricing.snapshot()
    rate = prices.rates.get(model)
    maximum = config['history_tokens'] if config['enabled'] else 0
    return {'settings': config, 'revision': model_settings.revision(raw), 'limits': LIMITS,
            'model': model, 'scope': 'conversation', 'storage': 'postgres' if session_store._using_postgres() else 'sqlite',
            'cost': {'price_version': prices.version, 'input_usd_per_million': rate[0] / 1000 if rate else None,
                     'history_usd_per_1000_replies': round(maximum * rate[0] / 1_000_000, 6) if rate else None,
                     'assumes_uncached_input': True}}


class ConversationMemory:
    """Same get/set interface as legacy Memory; one read/write batch per turn.

    SQLite shares memory across local workers. PostgreSQL uses the existing
    restricted tenant transaction and a private FORCE-RLS table across hosts.
    No cross-conversation identity matching or summarization model is used.
    """

    def __init__(self, storage, tenant):
        self.storage, self.tenant = storage, tenant
        self._active = ContextVar('conversation_memory_' + str(id(self)), default=None)

    def configuration(self):
        active = self._active.get()
        return dict(active['settings']) if active else profile(self.storage, self.tenant)[0]

    @contextmanager
    def _connection(self):
        if session_store._using_postgres():
            with session_store.postgres_connection(self.tenant) as db:
                yield db
        else:
            with session_store.connection() as db:
                db.execute('CREATE TABLE IF NOT EXISTS conversation_memory ('
                           'tenant TEXT NOT NULL, session_hash TEXT NOT NULL, generation TEXT NOT NULL, '
                           'payload TEXT NOT NULL, expires REAL NOT NULL, '
                           'PRIMARY KEY(tenant,session_hash,generation))')
                db.execute('CREATE INDEX IF NOT EXISTS conversation_memory_expiry ON conversation_memory(tenant,expires)')
                yield db

    def _execute(self, db, sql, values=()):
        return db.execute(sql.replace('?', '%s') if session_store._using_postgres() else sql, values)

    def _identity(self, sid):
        if not isinstance(sid, str) or not 1 <= len(sid) <= 512:
            raise ValueError('invalid_conversation_memory_id')
        return hashlib.sha256(sid.encode()).hexdigest()

    def _clean(self, payload, config, now):
        if not isinstance(payload, dict):
            return {}
        return {key: row for key, row in list(payload.items())[:32]
                if isinstance(key, str) and isinstance(row, dict)
                and type(row.get('expires')) in (int, float) and math.isfinite(row['expires'])
                and type(row.get('updated')) in (int, float) and math.isfinite(row['updated'])
                and now < min(row['expires'], row['updated'] + config['retention_minutes'] * 60)}

    def _read(self, sid, generation, config):
        with self._connection() as db:
            row = self._execute(db, 'SELECT payload FROM conversation_memory WHERE tenant=? AND session_hash=? AND generation=? AND expires>?',
                                (self.tenant, sid, generation, time.time())).fetchone()
        try:
            return self._clean(json.loads(row[0]), config, time.time()) if row else {}
        except (ValueError, TypeError):
            return {}

    def _write(self, active):
        if not active['pending']:
            return
        current, generation = profile(self.storage, self.tenant)
        if not current['enabled'] or generation != active['generation']:
            return
        now = time.time()
        with self._connection() as db:
            if not session_store._using_postgres():
                db.execute('BEGIN IMMEDIATE')
            else:
                lock = int.from_bytes(hashlib.sha256((self.tenant + active['sid'] + active['generation']).encode()).digest()[:8], 'big', signed=True)
                db.execute('SELECT pg_advisory_xact_lock(%s)', (lock,))
            row = self._execute(db, 'SELECT payload FROM conversation_memory WHERE tenant=? AND session_hash=? AND generation=?',
                                (self.tenant, active['sid'], active['generation'])).fetchone()
            try:
                payload = self._clean(json.loads(row[0]), active['settings'], now) if row else {}
            except (ValueError, TypeError):
                payload = {}
            payload.update(active['pending'])
            payload = self._clean(payload, current, now)
            if not payload:
                self._execute(db, 'DELETE FROM conversation_memory WHERE tenant=? AND session_hash=? AND generation=?',
                              (self.tenant, active['sid'], active['generation']))
                return
            encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
            if len(encoded.encode('utf-8')) > 131072:
                raise ValueError('conversation_memory_too_large')
            self._execute(db, 'INSERT INTO conversation_memory(tenant,session_hash,generation,payload,expires) '
                          'VALUES(?,?,?,?,?) ON CONFLICT(tenant,session_hash,generation) DO UPDATE '
                          'SET payload=excluded.payload,expires=excluded.expires',
                          (self.tenant, active['sid'], active['generation'], encoded, max(value['expires'] for value in payload.values())))
            # Bounded, indexed housekeeping; expired state is never returned.
            self._execute(db, 'DELETE FROM conversation_memory WHERE tenant=? AND expires<? AND session_hash IN '
                          '(SELECT session_hash FROM conversation_memory WHERE tenant=? AND expires<? LIMIT 100)',
                          (self.tenant, now, self.tenant, now))

    @contextmanager
    def turn(self, session_id):
        settings, generation = profile(self.storage, self.tenant)
        sid = self._identity(session_id)
        active = {'sid': sid, 'generation': generation, 'settings': settings, 'pending': {},
                  'values': self._read(sid, generation, settings) if settings['enabled'] else {}}
        token = self._active.set(active)
        try:
            yield
            if settings['enabled']:
                self._write(active)
        finally:
            self._active.reset(token)

    def get(self, session_id, key, default=None):
        active = self._active.get()
        if active is None:
            with self.turn(session_id):
                return self.get(session_id, key, default)
        if active['sid'] != self._identity(session_id):
            raise ValueError('conversation_memory_scope_mismatch')
        row = active['pending'].get(key, active['values'].get(key))
        valid = self._clean({key: row}, active['settings'], time.time()) if row else {}
        return row.get('value', default) if key in valid and active['settings']['enabled'] else default

    def set(self, session_id, key, value, ttl=None):
        active = self._active.get()
        if active is None:
            with self.turn(session_id):
                self.set(session_id, key, value, ttl)
            return
        if active['sid'] != self._identity(session_id) or not isinstance(key, str) or not re.fullmatch(r'[a-z_]{1,64}', key):
            raise ValueError('invalid_conversation_memory_key')
        if not active['settings']['enabled']:
            return
        # Values must survive JSON serialization and remain bounded per key.
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode('utf-8')) > 65536:
            raise ValueError('conversation_memory_value_too_large')
        now = time.time()
        seconds = active['settings']['retention_minutes'] * 60
        if ttl is not None:
            seconds = min(seconds, max(1, int(ttl)))
        active['pending'][key] = {'value': json.loads(encoded), 'updated': now, 'expires': now + seconds}

    def clear(self, session_id):
        sid = self._identity(session_id)
        with self._connection() as db:
            self._execute(db, 'DELETE FROM conversation_memory WHERE tenant=? AND session_hash=?', (self.tenant, sid))
        active = self._active.get()
        if active and active['sid'] == sid:
            active['values'], active['pending'] = {}, {}
