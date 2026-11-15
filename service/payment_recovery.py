"""Seven-day grace after a failed subscription renewal, anchored to the first failure.

The window opens when Stripe first reports a failed renewal for the business and
never moves while the failure lasts, so repeated retries cannot extend it. It
closes when Stripe reports the subscription paid again. Every write follows a
fresh read of Stripe's own objects, so delayed or out-of-order webhooks settle on
the current state. This module never charges, refunds or deletes anything.
"""
from __future__ import annotations

import time
from typing import Any

GRACE_SECONDS = 7 * 86400
FAILED_STATUSES = frozenset({'past_due', 'unpaid'})


def _schema(db: Any) -> None:
    from service import session_store
    if session_store._using_postgres():
        return
    db.execute('CREATE TABLE IF NOT EXISTS billing_payment_recovery (tenant TEXT PRIMARY KEY, '
               'subscription TEXT NOT NULL, started INTEGER NOT NULL, reminded INTEGER NOT NULL DEFAULT 0)')


def record_failure(db: Any, tenant: str, subscription: str, *, now: float | None = None) -> None:
    """Open the window if none is open. An open window keeps its original start."""
    _schema(db)
    started = int(time.time() if now is None else now)
    db.execute('INSERT INTO billing_payment_recovery (tenant,subscription,started,reminded) VALUES (?,?,?,0) '
               'ON CONFLICT(tenant) DO NOTHING', (tenant, subscription, started))


def clear(db: Any, tenant: str) -> None:
    _schema(db)
    db.execute('DELETE FROM billing_payment_recovery WHERE tenant=?', (tenant,))


def current(tenant: str) -> dict[str, Any] | None:
    """The open window, or None. A storage fault reads as no grace (fails closed)."""
    from service.subscriptions import connection
    try:
        with connection(tenant) as db:
            _schema(db)
            row = db.execute('SELECT subscription,started,reminded FROM billing_payment_recovery WHERE tenant=?',
                             (tenant,)).fetchone()
    except Exception as exc:  # Includes PostgreSQL before its migration is applied.
        from service.chat_diagnostics import emit
        emit('chat_optional_failure', phase='payment_recovery', error_type=type(exc).__name__)
        return None
    if not row:
        return None
    return {'subscription': row['subscription'], 'started': int(row['started']),
            'ends': int(row['started']) + GRACE_SECONDS, 'reminded': int(row['reminded'])}


def observe(db: Any, tenant: str, subscription: str, status: str) -> None:
    """Apply one verified Stripe subscription status to the recovery window."""
    if status in FAILED_STATUSES:
        record_failure(db, tenant, subscription)
    elif status in {'active', 'trialing'}:
        clear(db, tenant)


def mark_reminded(tenant: str, stage: int, *, previous: int | None = None) -> bool:
    """Claim reminder ``stage``; False if it was already claimed (no duplicates).

    ``previous`` puts a claim back after a failed send so the next run retries it.
    """
    from service.subscriptions import connection
    with connection(tenant) as db:
        _schema(db)
        if previous is not None:
            cursor = db.execute('UPDATE billing_payment_recovery SET reminded=? WHERE tenant=? AND reminded=?',
                                (previous, tenant, stage))
        else:
            cursor = db.execute('UPDATE billing_payment_recovery SET reminded=? WHERE tenant=? AND reminded<?',
                                (stage, tenant, stage))
        return bool(getattr(cursor, 'rowcount', 0))


# Stage 1: payment failed. Stage 2: two days left. Stage 3: service paused.
NOTICES = {
    1: ("Your Vertex Seven payment didn't go through",
        "Your subscription payment didn't go through. Please update your payment method by {date} "
        "to avoid interruption. Your AI assistants keep working until then."),
    2: ('2 days left to update your Vertex Seven payment',
        "We still haven't received your subscription payment. Please update your payment method by {date}. "
        "After that, your AI assistants will stop answering customers."),
    3: ('Your Vertex Seven AI services are paused',
        "Your subscription payment wasn't received within 7 days, so your AI assistants have stopped answering "
        "customers. Your business information is safe. Update your payment method to switch them back on."),
}


def due_stage(window: dict[str, Any], now: float) -> int:
    if now >= window['ends']:
        return 3
    if now >= window['ends'] - 2 * 86400:
        return 2
    return 1


def owner_email(tenant: str) -> str:
    """The registered owner's sign-in email for this business only, or ''."""
    import json
    from service import tenant_access
    with tenant_access._database() as db:
        tenant_access._schema(db)
        row = tenant_access._execute(db, 'SELECT owner FROM managed_businesses WHERE tenant=?', (tenant,)).fetchone()
    try:
        owner = json.loads(row[0]) if row and row[0] else None
    except (TypeError, ValueError):
        return ''
    return owner[1] if isinstance(owner, list) and len(owner) == 3 and owner[2] == tenant and isinstance(owner[1], str) else ''


def remind_all(container: Any, *, now: float | None = None) -> int:
    """Send each due payment notice at most once per stage. Returns notices sent."""
    import hashlib
    from datetime import datetime, timezone
    from html import escape
    from urllib.parse import urlencode
    from service import registration_mail, tenant_access
    now = time.time() if now is None else now
    with tenant_access._database() as db:
        tenant_access._schema(db)
        tenants = [row[0] for row in tenant_access._execute(db, 'SELECT tenant FROM managed_businesses')]
    sent = 0
    for tenant in tenants:
        window = current(tenant)
        if not window:
            continue
        stage = due_stage(window, now)
        email = owner_email(tenant)
        if stage <= window['reminded'] or not email or not mark_reminded(tenant, stage):
            continue
        subject, body = NOTICES[stage]
        body = body.format(date=datetime.fromtimestamp(window['ends'], timezone.utc).strftime('%d %B %Y'))
        url = container.settings.BASE_URL.rstrip('/') + '/console/subscription?' + urlencode({'tenant': tenant})
        text = f'{body}\n\nUpdate payment: {url}\n\nVertex Seven\n'
        html = ('<!doctype html><html lang="en"><body style="font-family:Arial,sans-serif;color:#18392f">'
                '<main style="max-width:560px;margin:24px auto"><p><strong>Vertex Seven</strong></p><h1 style="font-size:22px">'
                + escape(subject) + '</h1><p style="line-height:1.6">' + escape(body) + '</p><p><a href="'
                + escape(url, quote=True) + '">Update payment</a></p></main></body></html>')
        key = hashlib.sha256(f"{tenant}\0{window['started']}\0{stage}".encode()).hexdigest()
        try:
            registration_mail.send_transactional(email, subject, text, html, idempotency_key='v7-payment-' + key)
            sent += 1
        except Exception as exc:
            mark_reminded(tenant, stage, previous=window['reminded'])
            from flask import current_app
            current_app.logger.warning('Payment notice failed error_type=%s', type(exc).__name__)
    return sent
