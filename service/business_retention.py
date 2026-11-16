"""Thirty days of kept data after a subscription ends, then a platform review; nothing is deleted automatically."""
from __future__ import annotations

import re
import time
from typing import Any

from service import session_store

RETENTION_SECONDS = 30 * 86400
DECISIONS = ('pending', 'keep')
_TENANT = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}')


def _schema(db: Any) -> None:
    if not session_store._using_postgres():
        db.execute("CREATE TABLE IF NOT EXISTS business_retention (tenant TEXT PRIMARY KEY, ended INTEGER NOT NULL, "
                   "decision TEXT NOT NULL DEFAULT 'pending', decided INTEGER, actor TEXT)")


def _ready(db: Any) -> bool:
    if not session_store._using_postgres():
        return True
    return bool(db.execute("SELECT to_regclass('v7_private.business_retention') IS NOT NULL").fetchone()[0])


def _db():
    from service.tenant_access import _database
    return _database()


def _execute(db: Any, sql: str, params: tuple = ()) -> Any:
    from service.tenant_access import _execute as execute
    return execute(db, sql, params)


def observe(tenant: str, status: str, ended_at: Any = None) -> None:
    """Apply one verified Stripe subscription status. Ended starts the clock; active stops it."""
    if not (isinstance(tenant, str) and _TENANT.fullmatch(tenant)):
        return
    with _db() as db:
        _schema(db)
        if not _ready(db):
            return  # Before the migration there is no retention record; nothing is deleted either way.
        if status == 'canceled':
            ended = ended_at if type(ended_at) is int and 0 < ended_at <= time.time() + 60 else int(time.time())
            _execute(db, "INSERT INTO business_retention (tenant,ended,decision) VALUES (?,?,'pending') "
                         'ON CONFLICT(tenant) DO NOTHING', (tenant, ended))
        elif status in {'active', 'trialing'}:
            _execute(db, 'DELETE FROM business_retention WHERE tenant=?', (tenant,))


def current(tenant: str) -> dict[str, Any] | None:
    try:
        with _db() as db:
            _schema(db)
            if not _ready(db):
                return None
            row = _execute(db, 'SELECT ended,decision FROM business_retention WHERE tenant=?', (tenant,)).fetchone()
    except Exception:
        return None
    if not row:
        return None
    return {'ended': int(row[0]), 'retention_ends': int(row[0]) + RETENTION_SECONDS, 'decision': row[1]}


def review_queue(now: float | None = None) -> dict[str, list[dict[str, Any]]]:
    """Businesses still inside their 30 days, and those past it that await your decision."""
    now = time.time() if now is None else now
    with _db() as db:
        _schema(db)
        if not _ready(db):
            return {'retained': [], 'awaiting_review': [], 'kept': []}
        rows = _execute(db, 'SELECT tenant,ended,decision,decided FROM business_retention ORDER BY ended').fetchall()
    result: dict[str, list[dict[str, Any]]] = {'retained': [], 'awaiting_review': [], 'kept': []}
    for tenant, ended, decision, decided in rows:
        item = {'tenant': tenant, 'ended': int(ended), 'retention_ends': int(ended) + RETENTION_SECONDS,
                'decided': int(decided) if decided else None}
        if decision == 'keep':
            result['kept'].append(item)
        elif now >= item['retention_ends']:
            result['awaiting_review'].append(item)
        else:
            result['retained'].append(item)
    return result


def decide(tenant: str, decision: str, actor: str) -> None:
    """Record a review decision. Deleting a business's data is not automated."""
    if decision not in DECISIONS:
        raise ValueError('invalid_retention_decision')
    with _db() as db:
        _schema(db)
        if not _ready(db):
            raise ValueError('retention_unavailable')
        cursor = _execute(db, 'UPDATE business_retention SET decision=?,decided=?,actor=? WHERE tenant=?',
                          (decision, int(time.time()) if decision != 'pending' else None, actor, tenant))
        if not getattr(cursor, 'rowcount', 0):
            raise ValueError('unknown_retention_record')
