"""Each business's daily cap on messages one customer can send by website chat or WhatsApp."""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

from service import session_store

CHANNELS = ('web', 'whatsapp')
DEFAULT_LIMIT = 40
MIN_LIMIT, MAX_LIMIT = 5, 200
# One internet connection can carry several real visitors (an office, a mobile
# network), so it gets several visitors' worth before it is stopped. This stops
# one person getting round the limit by restarting the chat.
CONNECTION_VISITORS = 5
_KEEP_DAYS = 2


def _schema(db: Any) -> None:
    if not session_store._using_postgres():
        db.execute('CREATE TABLE IF NOT EXISTS customer_message_limits (tenant TEXT NOT NULL, channel TEXT NOT NULL, '
                   'message_limit INTEGER, actor TEXT NOT NULL, updated INTEGER NOT NULL, PRIMARY KEY (tenant, channel))')
        db.execute('CREATE TABLE IF NOT EXISTS customer_message_counts (tenant TEXT NOT NULL, channel TEXT NOT NULL, '
                   'subject TEXT NOT NULL, day TEXT NOT NULL, count INTEGER NOT NULL, '
                   'PRIMARY KEY (tenant, channel, subject, day))')


def _ready(db: Any) -> bool:
    if not session_store._using_postgres():
        return True
    return bool(db.execute("SELECT to_regclass('v7_private.customer_message_limits') IS NOT NULL "
                           "AND to_regclass('v7_private.customer_message_counts') IS NOT NULL").fetchone()[0])


def _valid(channel: str, limit: Any) -> int | None:
    if channel not in CHANNELS:
        raise ValueError('invalid_message_limit')
    if limit is None:
        return None
    if type(limit) is not int or not MIN_LIMIT <= limit <= MAX_LIMIT:
        raise ValueError('invalid_message_limit')
    return limit


def limits(tenant: str) -> dict[str, int | None]:
    """The daily limit per channel; None means unlimited."""
    from service.tenant_access import _database, _execute
    result: dict[str, int | None] = {channel: DEFAULT_LIMIT for channel in CHANNELS}
    with _database() as db:
        _schema(db)
        if not _ready(db):
            return result
        for channel, value in _execute(db, 'SELECT channel,message_limit FROM customer_message_limits WHERE tenant=?',
                                       (tenant,)):
            if channel in result:
                result[channel] = None if value is None else int(value)
    return result


def save(tenant: str, channel: str, limit: Any, actor: str) -> dict[str, int | None]:
    value = _valid(channel, limit)
    from service.tenant_access import _database, _execute
    with _database() as db:
        _schema(db)
        if not _ready(db):
            raise ValueError('message_limits_unavailable')
        _execute(db, 'INSERT INTO customer_message_limits (tenant,channel,message_limit,actor,updated) VALUES (?,?,?,?,?) '
                     'ON CONFLICT(tenant,channel) DO UPDATE SET message_limit=excluded.message_limit,'
                     'actor=excluded.actor,updated=excluded.updated',
                 (tenant, channel, value, actor, int(time.time())))
    return limits(tenant)


def subject(kind: str, value: str) -> str:
    """A keyed digest, so raw addresses and phone numbers are never stored."""
    from flask import current_app
    secret = current_app.secret_key
    key = secret if isinstance(secret, bytes) else str(secret or '').encode()
    if not key:
        raise RuntimeError('SECRET_KEY is required')
    digest = hmac.new(key, f'{kind}\0{value}'.encode(), hashlib.sha256).hexdigest()
    return f'{kind}:{digest}'


def _day(now: float) -> str:
    return time.strftime('%Y-%m-%d', time.gmtime(now))


def allow(tenant: str, channel: str, subjects: list[tuple[str, int]], *, now: float | None = None) -> bool:
    """Count one message for every subject, or none if any has reached its limit.

    ``subjects`` pairs a :func:`subject` with how many visitors' worth it may
    send (1 for one customer). Returns False when the message must be refused.
    """
    if channel not in CHANNELS:
        raise ValueError('invalid_message_limit')
    now = time.time() if now is None else now
    try:
        limit = limits(tenant)[channel]
        if limit is None:
            return True
        from service.tenant_access import _database, _execute
        postgres = session_store._using_postgres()
        day = _day(now)
        with _database() as db:
            _schema(db)
            if not _ready(db):
                return True
            if not postgres:
                db.execute('BEGIN IMMEDIATE')  # Serialise counting across workers.
            _execute(db, 'DELETE FROM customer_message_counts WHERE tenant=? AND channel=? AND day<?',
                     (tenant, channel, _day(now - _KEEP_DAYS * 86400)))
            counts = []
            for key, visitors in subjects:
                _execute(db, 'INSERT INTO customer_message_counts (tenant,channel,subject,day,count) VALUES (?,?,?,?,0) '
                             'ON CONFLICT DO NOTHING', (tenant, channel, key, day))
                row = _execute(db, 'SELECT count FROM customer_message_counts WHERE tenant=? AND channel=? AND subject=? '
                                   'AND day=?' + (' FOR UPDATE' if postgres else ''), (tenant, channel, key, day)).fetchone()
                counts.append((key, int(row[0]), limit * visitors))
            if any(count >= cap for _, count, cap in counts):
                return False
            for key, _, _ in counts:
                _execute(db, 'UPDATE customer_message_counts SET count=count+1 WHERE tenant=? AND channel=? '
                             'AND subject=? AND day=?', (tenant, channel, key, day))
        return True
    except Exception as exc:
        # A cost control that cannot be read must not cut every customer off.
        from service.chat_diagnostics import emit
        emit('chat_optional_failure', phase='message_limits', error_type=type(exc).__name__)
        return True


def limit_reached_notice(profile: Any) -> str:
    """Fixed customer wording; it never shows the number or how it is counted."""
    from service.tenant_access import unavailable_notice
    contact = unavailable_notice(profile).removeprefix('This assistant is currently unavailable. ')
    return "You've reached today's message limit for this chat. Please try again tomorrow. " + contact
