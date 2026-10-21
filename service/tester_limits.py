"""Durable daily limits for platform demos, never customer installations.

Reuse the private atomic reservation store with a distinct HMAC namespace.
Only opaque hashes and timestamps are persisted; login counters stay separate.
Accepted attempts count even if the provider fails. New conversations do not reset
the allowance. Existing burst limits and AI credit checks continue to apply.
"""
import hashlib
import hmac
import json
import math
from datetime import datetime, timedelta, timezone

from flask import current_app, jsonify, request, session
from werkzeug.exceptions import HTTPException

from service import session_store, subscriptions

LIMIT = 10
LIMIT_MESSAGE = "You’ve used today’s 10 free test messages. The allowance resets at 00:00 UTC. Sign in with a paid account to continue."


def _now():
    return datetime.now(timezone.utc)


def _paid(user):
    from service.tenant_access import owned_tenants
    tenants = {user.get('tenant'), *owned_tenants(user)} - {None, ''}
    for tenant in tenants:
        with subscriptions.connection(tenant) as db:
            row = db.execute(
                "SELECT 1 FROM billing_contracts c WHERE c.tenant=? AND c.kind='platform' "
                "AND c.status='active' AND c.subscription IS NOT NULL AND EXISTS "
                "(SELECT 1 FROM billing_invoices i WHERE i.tenant=c.tenant "
                "AND i.kind='platform' AND i.status='paid' AND i.paid>0)", (tenant,)).fetchone()
            if row:
                return True
    return False


def _subject(now):
    from service.security import management_user, is_platform_admin
    user = None
    if session.get('management_token'):
        try:
            user = management_user()
        except HTTPException as exc:
            if exc.code not in {401, 403}:
                raise
    if user:
        if is_platform_admin(user) or _paid(user):
            return None
        identity = ['account', user['id'], user['email'], user.get('tenant')]
    else:
        # remote_addr is normalized only by the application's trusted proxy setup.
        identity = ['network', request.remote_addr or 'unknown']
    value = json.dumps(['v7-tester-daily-v1', now.date().isoformat(), identity], separators=(',', ':'))
    secret = current_app.secret_key
    if isinstance(secret, str):
        secret = secret.encode()
    return hmac.new(secret, value.encode(), hashlib.sha256).hexdigest()


def enforce(tenant, *, console=False, consume=True):
    """Return a response when blocked; otherwise reserve one accepted message."""
    from app.config import valid_public_widget_tenant
    public = valid_public_widget_tenant(getattr(current_app.container.settings, 'PUBLIC_WIDGET_TENANT', ''))
    if not console and (not public or tenant != public):
        return None
    try:
        now = _now()
        subject = _subject(now)
        if subject is None:
            return None
        if consume:
            _, retry = session_store.reserve_login_attempt(subject, max_attempts=LIMIT, window_seconds=86400)
        else:
            retry = session_store.login_retry_after(subject, max_attempts=LIMIT, window_seconds=86400)
        if not retry:
            return None
        from service.chat_diagnostics import emit
        emit('tester_limit', outcome='daily_exhausted', status_code=429)
        reset = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        seconds = max(1, math.ceil((reset-now).total_seconds()))
        response = jsonify(error='tester_daily_limit', reply=LIMIT_MESSAGE, limit=LIMIT,
                           resets_at=reset.isoformat().replace('+00:00', 'Z'), retry_after=seconds)
        response.status_code = 429
        response.headers['Retry-After'] = str(seconds)
        return response
    except Exception as exc:
        from service.chat_diagnostics import emit
        emit('chat_optional_failure', phase='tester_daily_limit', error_type=type(exc).__name__)
        response = jsonify(error='tester_limit_unavailable', reply='Test chat is temporarily unavailable. Please try again shortly.')
        response.status_code = 503
        return response
