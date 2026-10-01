"""Opt-in device proofs after MFA; passwords and normal sessions remain required."""
from datetime import datetime, timezone
import hashlib
import hmac
import math
import re
import secrets
import time

from flask import current_app, request

from service import session_store
from service.account_mfa import account_key

COOKIE_NAME = 'v7_trusted_device'
TRUST_SECONDS = 30 * 86400
_TOKEN = re.compile(r'[A-Za-z0-9_-]{43}\Z')


def _database():
    return session_store.postgres_connection() if session_store._using_postgres() else session_store.connection()


def _execute(db, sql, params=()):
    return db.execute(sql.replace('?', '%s') if session_store._using_postgres() else sql, params)


def _tables(db):
    if not session_store._using_postgres():
        db.execute('CREATE TABLE IF NOT EXISTS trusted_devices (token_hash TEXT PRIMARY KEY, account TEXT NOT NULL, revision TEXT NOT NULL, expires REAL NOT NULL)')
        db.execute('CREATE INDEX IF NOT EXISTS trusted_devices_account ON trusted_devices(account)')
        db.execute('CREATE INDEX IF NOT EXISTS trusted_devices_expires ON trusted_devices(expires)')


def _cookie_hash():
    token = request.cookies.get(COOKIE_NAME, '')
    return hashlib.sha256(token.encode()).hexdigest() if _TOKEN.fullmatch(token) else None


def issue(user, tenant):
    """Called only after a successful MFA-confirmed management login."""
    from service.security import _revision
    identity = {**user, 'tenant': user.get('tenant') or tenant}
    if not user.get('totp_secret'):
        raise ValueError('mfa_setup_required')
    revision = _revision(identity)
    if not revision:
        raise ValueError('account_unavailable')
    token = secrets.token_urlsafe(32)
    expires = time.time()+TRUST_SECONDS
    with _database() as db:
        _tables(db)
        _execute(db, 'DELETE FROM trusted_devices WHERE expires<=? OR token_hash=?',
                 (time.time(), _cookie_hash() or ''))
        _execute(db, 'INSERT INTO trusted_devices (token_hash,account,revision,expires) VALUES (?,?,?,?)',
                 (hashlib.sha256(token.encode()).hexdigest(), account_key(identity), revision, expires))
    return token, expires


def verified_first_factor_login(user, tenant):
    """After verified password/OIDC, rotate same-account proof without extending expiry."""
    from service.account_mfa import _login_limiter, cancel_pending
    from service.security import _revision, start_management_session
    token_hash = _cookie_hash()
    if not token_hash or not user.get('totp_secret'):
        return None
    identity = {**user, 'tenant': user.get('tenant') or tenant}
    revision = _revision(identity)
    if not revision:
        return None
    with _database() as db:
        _tables(db)
        if not session_store._using_postgres():
            db.execute('BEGIN IMMEDIATE')
        lock = ' FOR UPDATE' if session_store._using_postgres() else ''
        row = _execute(db, 'SELECT account,revision,expires FROM trusted_devices WHERE token_hash=?'+lock,
                       (token_hash,)).fetchone()
        _execute(db, 'DELETE FROM trusted_devices WHERE expires<=?', (time.time(),))
        if not row:
            return None
        account, saved_revision, expires = row
        if (expires <= time.time() or not hmac.compare_digest(account.encode(), account_key(identity).encode())
                or not hmac.compare_digest(saved_revision, revision)):
            _execute(db, 'DELETE FROM trusted_devices WHERE token_hash=?', (token_hash,))
            return None
        cancel_pending(transaction=db)
        authenticated = start_management_session(user, tenant, mfa_verified=True, transaction=db)
        token = secrets.token_urlsafe(32)
        _execute(db, 'DELETE FROM trusted_devices WHERE token_hash=?', (token_hash,))
        _execute(db, 'INSERT INTO trusted_devices (token_hash,account,revision,expires) VALUES (?,?,?,?)',
                 (hashlib.sha256(token.encode()).hexdigest(), account, revision, expires))
        limiter = _login_limiter()
        limiter.reset(limiter.identity_key(identity), transaction=db)
    return authenticated, token, expires


def password_login(user, tenant):
    return verified_first_factor_login(user, tenant)


def set_cookie(response, token, expires):
    response.set_cookie(COOKIE_NAME, token, max_age=max(1, math.ceil(expires-time.time())),
                        expires=datetime.fromtimestamp(expires, timezone.utc),
                        httponly=True, secure=bool(current_app.config['SESSION_COOKIE_SECURE']),
                        samesite='Lax', path='/')
    return response


def clear_cookie(response):
    response.delete_cookie(COOKIE_NAME, httponly=True,
                           secure=bool(current_app.config['SESSION_COOKIE_SECURE']), samesite='Lax', path='/')
    return response


def revoke_current():
    token_hash = _cookie_hash()
    if token_hash:
        with _database() as db:
            _tables(db)
            _execute(db, 'DELETE FROM trusted_devices WHERE token_hash=?', (token_hash,))


def revoke_account(user):
    with _database() as db:
        _tables(db)
        _execute(db, 'DELETE FROM trusted_devices WHERE account=?', (account_key(user),))


def status(user):
    from service.security import _revision
    revision = _revision(user)
    with _database() as db:
        _tables(db)
        _execute(db, 'DELETE FROM trusted_devices WHERE expires<=?', (time.time(),))
        rows = _execute(db, 'SELECT token_hash,expires FROM trusted_devices WHERE account=? AND revision=? ORDER BY expires',
                        (account_key(user), revision)).fetchall()
    current = _cookie_hash()
    return {'count': len(rows), 'devices': [
        {'expires_utc': datetime.fromtimestamp(expires, timezone.utc).isoformat(),
         'current': bool(current and hmac.compare_digest(saved, current))}
        for saved, expires in rows
    ]}
