"""Password-gated authenticator enrollment; secrets never enter session cookies."""
import base64
import hashlib
import hmac
import json
import secrets
import time

import pyotp
import qrcode
import qrcode.image.svg
from flask import current_app, session

from service import session_store


def _tables(db):
    if session_store._using_postgres():
        return
    db.execute("CREATE TABLE IF NOT EXISTS account_authenticators (account TEXT PRIMARY KEY, secret TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS mfa_challenges (token TEXT PRIMARY KEY, account TEXT NOT NULL, identity TEXT NOT NULL, revision TEXT NOT NULL, secret TEXT NOT NULL, enrollment INTEGER NOT NULL, expires REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0)")
    db.execute("CREATE TABLE IF NOT EXISTS mfa_code_uses (account TEXT NOT NULL, secret_hash TEXT NOT NULL, timestep INTEGER NOT NULL, PRIMARY KEY(account,secret_hash,timestep))")
    db.execute("CREATE INDEX IF NOT EXISTS mfa_code_uses_timestep ON mfa_code_uses(timestep)")


def _database():
    return session_store.postgres_connection() if session_store._using_postgres() else session_store.connection()


def _execute(db, sql, params=()):
    return db.execute(sql.replace('?', '%s') if session_store._using_postgres() else sql, params)


def account_key(user):
    platform = bool({'platform_admin', 'admin'}.intersection(user.get('roles', [])))
    return json.dumps([user['id'], user['email'], '' if platform else user.get('tenant')], separators=(',', ':'))


def enrolled_secret(user):
    with _database() as db:
        _tables(db)
        return _enrolled_secret(db, user)


def _enrolled_secret(db, user):
    account = account_key(user)
    if session_store._using_postgres():
        row = _execute(db, 'SELECT secret FROM account_authenticators WHERE account=?', (account,)).fetchone()
        return row[0] if row else ''
    # SQLite tenants used to accept directory aliases on Windows. Reuse their
    # protected enrollment without changing stored keys or permitting a reset.
    identity = json.loads(account)
    matches = []
    for saved, secret in _execute(db, 'SELECT account,secret FROM account_authenticators').fetchall():
        try:
            parsed = json.loads(saved)
        except json.JSONDecodeError:
            continue
        if (isinstance(parsed, list) and len(parsed) == 3 and parsed[:2] == identity[:2]
                and isinstance(parsed[2], str) and isinstance(identity[2], str)
                and parsed[2].casefold() == identity[2].casefold()):
            matches.append(secret)
    if len({secret.strip().upper().rstrip('=') for secret in matches}) > 1:
        raise ValueError('account_unavailable')
    return matches[0] if matches else ''


def begin(user, tenant):
    from service.security import _revision
    identity = {key: user[key] for key in ('id', 'email', 'roles')}
    identity['tenant'] = user.get('tenant') or tenant
    if 'permissions' in user:
        identity['permissions'] = user['permissions']
    revision = _revision(identity)
    authenticated = user.get('_credential_revision')
    if not revision or not isinstance(authenticated, str) or not hmac.compare_digest(revision, authenticated):
        raise ValueError('account_unavailable')
    identity['_account_revision'] = user['_account_revision']
    existing = user.get('totp_secret') or enrolled_secret(identity)
    secret = existing or pyotp.random_base32()
    token = secrets.token_urlsafe(32)
    session_store.revoke(session.get('management_token'))
    old = session.get('mfa_challenge', '')
    session.clear()
    session['_csrf'] = secrets.token_urlsafe(32)
    session['mfa_challenge'] = token
    with _database() as db:
        _tables(db)
        _execute(db, 'DELETE FROM mfa_challenges WHERE expires<? OR token=?', (time.time(), _digest(old)))
        _execute(db, 'INSERT INTO mfa_challenges (token,account,identity,revision,secret,enrollment,expires) VALUES (?,?,?,?,?,?,?)',
                   (_digest(token), account_key(identity), json.dumps(identity), revision, secret, int(not existing), time.time()+300))
    return pending()


def _digest(token):
    return hashlib.sha256(str(token).encode()).hexdigest()


def cancel_pending(*, transaction=None):
    """Revoke the server challenge before clearing its browser cookie."""
    token = session.get('mfa_challenge')
    if not token:
        return
    if transaction is not None:
        _execute(transaction, 'DELETE FROM mfa_challenges WHERE token=?', (_digest(token),))
    else:
        with _database() as db:
            _tables(db)
            _execute(db, 'DELETE FROM mfa_challenges WHERE token=?', (_digest(token),))
    session.pop('mfa_challenge', None)


def pending():
    from service.security import _revision
    token = session.get('mfa_challenge')
    if not token:
        return None
    with _database() as db:
        _tables(db)
        row = _execute(db, 'SELECT identity,secret,enrollment,revision FROM mfa_challenges WHERE token=? AND expires>? AND attempts<5',
                         (_digest(token), time.time())).fetchone()
    if not row:
        cancel_pending()
        return None
    identity, secret, enrollment, revision = row
    current = _revision(json.loads(identity))
    if not current or not hmac.compare_digest(current, revision):
        cancel_pending()
        return None
    result = {'enrollment': bool(enrollment), 'email': json.loads(identity)['email']}
    if enrollment:
        uri = pyotp.TOTP(secret).provisioning_uri(name=json.loads(identity)['email'], issuer_name='V7 Sales Agent')
        svg = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage).to_string()
        result.update(setup_key=secret, qr_image='data:image/svg+xml;base64,'+base64.b64encode(svg).decode())
    return result


def _login_limiter():
    from service.login_limiter import LoginAttemptLimiter
    limiter = current_app.extensions.get('auth_login_limiter')
    if limiter is not None:
        return limiter
    settings = getattr(getattr(current_app, 'container', None), 'settings', None)
    return LoginAttemptLimiter(max_attempts=getattr(settings, 'AUTH_LOGIN_MAX_ATTEMPTS', 8),
                               window_seconds=getattr(settings, 'AUTH_LOGIN_WINDOW_SECONDS', 900))


def _consume_code(db, account, secret, code):
    from service.security import totp_timestep
    timestep = totp_timestep(secret, code)
    if timestep is None:
        raise ValueError('invalid_authenticator_code')
    normalized = secret.strip().upper().rstrip('=')
    secret_hash = hashlib.sha256(normalized.encode()).hexdigest()
    # Retain the whole accepted skew window; a future-step code remains spent
    # when that step becomes current. Old rows no longer affect verification.
    _execute(db, 'DELETE FROM mfa_code_uses WHERE timestep<?', (timestep-2,))
    inserted = _execute(db, 'INSERT INTO mfa_code_uses (account,secret_hash,timestep) VALUES (?,?,?) '
                        'ON CONFLICT(account,secret_hash,timestep) DO NOTHING',
                        (account, secret_hash, timestep))
    if inserted.rowcount != 1:
        raise ValueError('authenticator_code_reused')
    key = base64.b32decode(normalized + '=' * (-len(normalized) % 8), casefold=True)
    if not session_store.consume_totp(account, key.hex(), timestep, database=db):
        raise ValueError('authenticator_code_reused')


def complete_login(user, tenant, code):
    """Consume a combined-login code and publish its session in one transaction."""
    from service.security import start_management_session
    limiter = _login_limiter()
    with _database() as db:
        _tables(db)
        if not session_store._using_postgres():
            db.execute('BEGIN IMMEDIATE')
        _consume_code(db, account_key(user), user['totp_secret'], code)
        cancel_pending(transaction=db)
        identity = start_management_session(user, tenant, mfa_verified=True, transaction=db)
        limiter.reset(limiter.identity_key(user), transaction=db)
    return identity


def confirm(code):
    from service.security import _account_tenant, _bound_revision, _revision
    token = _digest(session.get('mfa_challenge', ''))
    # Read revision before the write transaction: it also opens the security DB.
    with _database() as db:
        _tables(db)
        row = _execute(db, 'SELECT identity,revision FROM mfa_challenges WHERE token=?', (token,)).fetchone()
    current = _revision(json.loads(row[0])) if row else None
    if not current or not hmac.compare_digest(current, row[1]):
        raise ValueError('sign_in_again')
    limiter = _login_limiter()
    user = json.loads(row[0])
    user['tenant'] = _account_tenant(getattr(current_app, 'container', None), user['tenant'])
    subject = limiter.identity_key(user)
    attempt = limiter.begin(subject)
    failure = None
    try:
        with _database() as db:
            if not session_store._using_postgres():
                db.execute('BEGIN IMMEDIATE')
            lock = ' FOR UPDATE' if session_store._using_postgres() else ''
            challenge = _execute(db, 'SELECT secret,enrollment FROM mfa_challenges WHERE token=? AND expires>? AND attempts<5' + lock,
                                   (token, time.time())).fetchone()
            if not challenge:
                raise ValueError('sign_in_again')
            secret, enrollment = challenge
            account = account_key(user)
            try:
                _consume_code(db, account, secret, code)
            except ValueError as exc:
                _execute(db, 'UPDATE mfa_challenges SET attempts=attempts+1 WHERE token=?', (token,))
                limiter.fail(subject, attempt, transaction=db)
                failure = str(exc)
            else:
                if enrollment:
                    # Another browser may have enrolled first. Never replace its authenticator.
                    if _enrolled_secret(db, user):
                        raise ValueError('sign_in_again')
                    inserted = _execute(db, 'INSERT INTO account_authenticators (account,secret) VALUES (?,?) ON CONFLICT(account) DO NOTHING', (account, secret))
                    if inserted.rowcount != 1:
                        raise ValueError('sign_in_again')
                _execute(db, 'DELETE FROM mfa_challenges WHERE token=?', (token,))
                limiter.reset(subject, transaction=db)
    except ValueError:
        limiter.fail(subject, attempt)
        raise
    if failure:
        raise ValueError(failure)
    session.pop('mfa_challenge', None)
    user['_credential_revision'] = _bound_revision(user['_account_revision'], enrolled_secret(user))
    return {**user, 'totp_secret': secret}
