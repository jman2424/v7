"""Live service controls: a business pausing its AI and the platform kill switch, enforced on the server."""
from __future__ import annotations

import re
import time
from typing import Any

from service import session_store

CHANNELS = ('web', 'whatsapp', 'email', 'phone')
# Every worker re-reads the controls at least this often; a write clears this worker's copy at once.
TTL_SECONDS = 5
_cache: dict[str, Any] = {'at': 0.0, 'rows': None}
_TENANT = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}')


def _schema(db: Any) -> None:
    if not session_store._using_postgres():
        db.execute('CREATE TABLE IF NOT EXISTS service_controls (scope TEXT PRIMARY KEY, reason TEXT NOT NULL, '
                   'actor TEXT NOT NULL, updated INTEGER NOT NULL)')


def _ready(db: Any) -> bool:
    if not session_store._using_postgres():
        return True
    return bool(db.execute("SELECT to_regclass('v7_private.service_controls') IS NOT NULL").fetchone()[0])


def key(level: str, tenant: str | None = None, channel: str | None = None) -> str:
    """``platform`` (optionally one business and/or one channel) or ``business`` (one business)."""
    if level not in {'platform', 'business'} or (channel is not None and channel not in CHANNELS):
        raise ValueError('invalid_service_control')
    if tenant is not None and not (isinstance(tenant, str) and _TENANT.fullmatch(tenant)):
        raise ValueError('invalid_service_control')
    if level == 'business' and tenant is None:
        raise ValueError('invalid_service_control')
    parts = [level] + (['tenant', tenant] if tenant else []) + (['channel', channel] if channel else [])
    return ':'.join(parts)


def _rows() -> dict[str, dict[str, Any]]:
    now = time.monotonic()
    if _cache['rows'] is not None and now - _cache['at'] < TTL_SECONDS:
        return _cache['rows']
    from service.tenant_access import _database, _execute
    with _database() as db:
        _schema(db)
        if not _ready(db):
            rows: dict[str, dict[str, Any]] = {}  # Before the migration nothing can be paused.
        else:
            rows = {row[0]: {'reason': row[1], 'actor': row[2], 'updated': int(row[3])}
                    for row in _execute(db, 'SELECT scope,reason,actor,updated FROM service_controls')}
    _cache.update(at=now, rows=rows)
    return rows


def invalidate() -> None:
    _cache.update(at=0.0, rows=None)


def _check(tenant: str, channel: str | None, *, business: bool) -> str | None:
    try:
        rows = _rows()
    except Exception as exc:
        # A control that cannot be read is treated as on: the kill switch must not fail open.
        from service.chat_diagnostics import emit
        emit('chat_optional_failure', phase='service_controls', error_type=type(exc).__name__)
        return 'service_controls_unavailable'
    channel = channel if channel in CHANNELS else None
    platform = ['platform', f'platform:tenant:{tenant}']
    if channel:
        platform += [f'platform:channel:{channel}', f'platform:tenant:{tenant}:channel:{channel}']
    if any(scope in rows for scope in platform):
        return 'suspended_by_platform'
    if business:
        owned = [f'business:tenant:{tenant}'] + ([f'business:tenant:{tenant}:channel:{channel}'] if channel else [])
        if any(scope in rows for scope in owned):
            return 'paused_by_business'
    return None


def blocked(tenant: str, channel: str | None = None) -> str | None:
    """Why customers of ``tenant`` on ``channel`` get no AI right now, or None."""
    return _check(tenant, channel, business=True)


def platform_blocked(tenant: str) -> str | None:
    """Only the platform's own switches (the owner's management tools ignore a business pause)."""
    return _check(tenant, None, business=False)


def set_control(scope: str, paused: bool, actor: str, reason: str = '') -> None:
    if not isinstance(paused, bool) or not isinstance(reason, str) or len(reason) > 500:
        raise ValueError('invalid_service_control')
    from service.tenant_access import _database, _execute
    with _database() as db:
        _schema(db)
        if not _ready(db):
            raise ValueError('service_controls_unavailable')
        if paused:
            _execute(db, 'INSERT INTO service_controls (scope,reason,actor,updated) VALUES (?,?,?,?) '
                         'ON CONFLICT(scope) DO UPDATE SET reason=excluded.reason,actor=excluded.actor,updated=excluded.updated',
                     (scope, reason.strip(), actor, int(time.time())))
        else:
            _execute(db, 'DELETE FROM service_controls WHERE scope=?', (scope,))
    invalidate()


def business_state(tenant: str) -> dict[str, Any]:
    """What the owner sees: their own pauses and anything the platform has suspended."""
    rows = _rows()
    channels = {}
    for channel in CHANNELS:
        channels[channel] = {
            'paused': key('business', tenant, channel) in rows,
            'suspended_by_platform': any(scope in rows for scope in (
                f'platform:channel:{channel}', f'platform:tenant:{tenant}:channel:{channel}')),
        }
    return {'all_paused': key('business', tenant) in rows,
            'suspended_by_platform': 'platform' in rows or key('platform', tenant) in rows,
            'channels': channels}


def platform_state() -> list[dict[str, Any]]:
    """Every active platform switch, newest first (platform administrators only)."""
    return sorted(({'scope': scope, **row} for scope, row in _rows().items() if scope.startswith('platform')),
                  key=lambda row: -row['updated'])
