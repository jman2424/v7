"""Password-gated authenticator enrollment; secrets never enter session cookies."""
import base64
import hashlib
import json
import secrets
import time

import pyotp
import qrcode
import qrcode.image.svg
from flask import session

from service import session_store


def _tables(db):
    db.execute("CREATE TABLE IF NOT EXISTS account_authenticators (account TEXT PRIMARY KEY, secret TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS mfa_challenges (token TEXT PRIMARY KEY, account TEXT NOT NULL, identity TEXT NOT NULL, revision TEXT NOT NULL, secret TEXT NOT NULL, enrollment INTEGER NOT NULL, expires REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0)")


def account_key(user):
    platform = bool({'platform_admin', 'admin'}.intersection(user.get('roles', [])))
    return json.dumps([user['id'], user['email'], '' if platform else user.get('tenant')], separators=(',', ':'))


def enrolled_secret(user):
    with session_store.connection() as db:
        _tables(db)
        row = db.execute('SELECT secret FROM account_authenticators WHERE account=?', (account_key(user),)).fetchone()
    return row[0] if row else ''


def begin(user, tenant):
    from service.security import _revision
    identity = {key: user[key] for key in ('id', 'email', 'roles')}
    identity['tenant'] = user.get('tenant') or tenant
    revision = _revision(identity)
    if not revision:
        raise ValueError('account_unavailable')
    existing = user.get('totp_secret') or enrolled_secret(identity)
    secret = existing or pyotp.random_base32()
    token = secrets.token_urlsafe(32)
    session_store.revoke(session.get('management_token'))
    old = session.get('mfa_challenge', '')
    session.clear()
    session['_csrf'] = secrets.token_urlsafe(32)
    session['mfa_challenge'] = token
    with session_store.connection() as db:
        _tables(db)
        db.execute('DELETE FROM mfa_challenges WHERE expires<? OR token=?', (time.time(), _digest(old)))
        db.execute('INSERT INTO mfa_challenges (token,account,identity,revision,secret,enrollment,expires) VALUES (?,?,?,?,?,?,?)',
                   (_digest(token), account_key(identity), json.dumps(identity), revision, secret, int(not existing), time.time()+300))
    return pending()


def _digest(token):
    return hashlib.sha256(str(token).encode()).hexdigest()


def pending():
    token = session.get('mfa_challenge')
    if not token:
        return None
    with session_store.connection() as db:
        _tables(db)
        row = db.execute('SELECT identity,secret,enrollment FROM mfa_challenges WHERE token=? AND expires>? AND attempts<5',
                         (_digest(token), time.time())).fetchone()
    if not row:
        session.pop('mfa_challenge', None)
        return None
    identity, secret, enrollment = row
    result = {'enrollment': bool(enrollment), 'email': json.loads(identity)['email']}
    if enrollment:
        uri = pyotp.TOTP(secret).provisioning_uri(name=json.loads(identity)['email'], issuer_name='V7 Sales Agent')
        svg = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage).to_string()
        result.update(setup_key=secret, qr_image='data:image/svg+xml;base64,'+base64.b64encode(svg).decode())
    return result


def confirm(code):
    from service.security import _revision, verify_totp
    token = _digest(session.get('mfa_challenge', ''))
    # Read revision before the write transaction: it also opens the security DB.
    with session_store.connection() as db:
        _tables(db)
        row = db.execute('SELECT identity,revision FROM mfa_challenges WHERE token=?', (token,)).fetchone()
    if not row or _revision(json.loads(row[0])) != row[1]:
        raise ValueError('sign_in_again')
    with session_store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        challenge = db.execute('SELECT account,identity,secret,enrollment FROM mfa_challenges WHERE token=? AND expires>? AND attempts<5',
                               (token, time.time())).fetchone()
        if not challenge:
            raise ValueError('sign_in_again')
        account, identity, secret, enrollment = challenge
        if not verify_totp(secret, code):
            db.execute('UPDATE mfa_challenges SET attempts=attempts+1 WHERE token=?', (token,))
            valid = False
        else:
            if enrollment:
                # Another browser may have enrolled first. Never replace its authenticator.
                present = db.execute('SELECT secret FROM account_authenticators WHERE account=?', (account,)).fetchone()
                if present:
                    raise ValueError('sign_in_again')
                db.execute('INSERT INTO account_authenticators VALUES (?,?)', (account, secret))
            db.execute('DELETE FROM mfa_challenges WHERE token=?', (token,))
            valid = True
    if not valid:
        raise ValueError('invalid_authenticator_code')
    session.pop('mfa_challenge', None)
    return {**json.loads(identity), 'totp_secret': secret}
