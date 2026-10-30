"""Verified self-service email changes without changing account permissions."""
import base64
import hmac
import json
import os
import secrets
import time

from flask import current_app, session

from service import account_mfa, account_passwords, oidc_login, registration, registration_mail
from service import security, session_store, tenant_access, trusted_devices
from service.account_service import AccountService, valid_account_email

INVALID = 'Email change code is invalid, expired or already used. Start again.'
UNAVAILABLE = 'This email cannot be used for this account. Choose another address.'


def _scope(user):
    return account_passwords._tenant(user.get('tenant') or current_app.container.settings.BUSINESS_KEY)


def _find_self(user, tenant, db):
    found = account_passwords._find(user['email'], tenant, db)
    if not found or found[2]['id'] != user['id']:
        raise ValueError('This account cannot change its email here. Contact the platform operator.')
    roles = [found[1]['role']] if found[0] == 'registry' else found[1]['roles']
    platform = bool({'admin', 'platform_admin'}.intersection(roles))
    if roles != user['roles'] or (not platform and found[2]['tenant'] != user.get('tenant')):
        raise ValueError('Your account changed. Sign in again.')
    return found


def _available(email, tenant, source):
    storage = current_app.container.storage
    if (email == os.getenv('ADMIN_USERNAME', '').strip().lower()
            or any(str(row.get('email') or '').strip().lower() == email
                   for row in [*security._registry_users(current_app.container), *security._business_users()])):
        return False
    # A global registry login must not shadow an existing business login.
    tenants = storage.tenant_keys() if source == 'registry' else [tenant]
    return not any(str(row.get('email') or '').strip().lower() == email
                   for key in tenants for row in AccountService(storage)._accounts(key))


def start(user, data):
    if not registration_mail.configured():
        raise ValueError('Email changes are unavailable. Contact the platform operator.')
    if not isinstance(data, dict) or not isinstance(data.get('email'), str):
        raise ValueError('Enter a valid email address.')
    email, password = data['email'].strip().lower(), data.get('current_password')
    if len(email) > 254 or not valid_account_email(email):
        raise ValueError('Enter a valid email address.')
    if email == user['email']:
        raise ValueError('Enter a different email address.')
    if not isinstance(password, str) or not 1 <= len(password) <= 1024:
        raise ValueError('Current password was not accepted.')
    tenant = _scope(user)
    request_id, code, now = secrets.token_urlsafe(32), f'{secrets.randbelow(1000000):06d}', time.time()
    reference = json.dumps({key: user.get(key) for key in ('id', 'email', 'tenant')}, sort_keys=True)
    with registration._decision_database(tenant) as db:
        found = _find_self(user, tenant, db)
        if not security.verify_password(password, found[1].get('password_hash', '')):
            raise ValueError('Current password was not accepted.')
        if not _available(email, tenant, found[0]):
            raise ValueError(UNAVAILABLE)
        recent = registration._execute(db, "SELECT COUNT(*),MAX(created) FROM registration_requests WHERE kind='email_change' AND business_name=? AND created>?", (reference, now-86400)).fetchone()
        if recent[0] >= 5 or (recent[1] and recent[1] > now-60):
            raise ValueError('Please wait before requesting another email change code.')
        registration._execute(db, "INSERT INTO registration_requests (id,email,password_hash,kind,tenant,business_name,code_hash,expires,status,created) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (request_id, email, security._account_revision(found[1]), 'email_change', tenant, reference,
             registration._code_hash(request_id, code), now+600, 'email_pending', now))
    try:
        registration_mail.send_email_change_code(email, code)
    except Exception as exc:
        current_app.logger.warning('Email change verification delivery failed (%s)', type(exc).__name__)
        with registration._database() as db:
            registration._execute(db, "UPDATE registration_requests SET status='email_failed',password_hash='',code_hash='' WHERE id=?", (request_id,))
        raise ValueError('Verification email could not be sent. Try again later.') from None
    session['email_change_request'] = request_id


def _move_security(db, old, new, secret):
    for module in (account_mfa, trusted_devices, oidc_login):
        module._tables(db)
    tenant_access._schema(db)
    old_key, new_key = account_mfa.account_key(old), account_mfa.account_key(new)
    if registration._execute(db, 'SELECT 1 FROM account_authenticators WHERE account=?', (new_key,)).fetchone():
        raise ValueError(UNAVAILABLE)
    old_keys = {old_key}
    # Preserve SQLite directory-case enrollments accepted by the existing login.
    if not session_store._using_postgres():
        expected = json.loads(old_key)
        for saved, in db.execute('SELECT account FROM account_authenticators'):
            try:
                value = json.loads(saved)
            except (TypeError, ValueError):
                continue
            if (isinstance(value, list) and len(value) == 3 and value[:2] == expected[:2]
                    and isinstance(value[2], str) and value[2].casefold() == expected[2].casefold()):
                old_keys.add(saved)
    for previous in old_keys:
        registration._execute(db, 'DELETE FROM account_authenticators WHERE account=?', (previous,))
        registration._execute(db, 'INSERT INTO mfa_code_uses(account,secret_hash,timestep) SELECT ?,secret_hash,timestep FROM mfa_code_uses WHERE account=? ON CONFLICT DO NOTHING', (new_key, previous))
        registration._execute(db, 'DELETE FROM mfa_code_uses WHERE account=?', (previous,))
        registration._execute(db, 'DELETE FROM mfa_challenges WHERE account=?', (previous,))
        registration._execute(db, 'DELETE FROM trusted_devices WHERE account=?', (previous,))
        registration._execute(db, 'UPDATE oidc_links SET account=?,identity=? WHERE account=?',
            (new_key, json.dumps(oidc_login._reference(new), separators=(',', ':')), previous))
    if secret:
        registration._execute(db, 'INSERT INTO account_authenticators(account,secret) VALUES (?,?)', (new_key, secret))
    for saved, in registration._execute(db, 'SELECT owner FROM managed_businesses WHERE owner IS NOT NULL').fetchall():
        try:
            value = json.loads(saved)
        except (TypeError, ValueError):
            continue
        if (isinstance(value, list) and len(value) == 3 and value[:2] == [old['id'], old['email']]
                and (value[2] == old.get('tenant') or (isinstance(value[2], str) and isinstance(old.get('tenant'), str)
                     and value[2].casefold() == old['tenant'].casefold()))):
            registration._execute(db, 'UPDATE managed_businesses SET owner=? WHERE owner=?', (tenant_access.owner_key(new), saved))
    if not session_store._using_postgres():
        db.execute('CREATE TABLE IF NOT EXISTS totp_steps (account_hash TEXT PRIMARY KEY, step INTEGER NOT NULL)')
    if secret:
        normalized = secret.strip().upper().rstrip('=')
        key = base64.b32decode(normalized + '=' * (-len(normalized) % 8), casefold=True).hex()
        new_hash = session_store._digest(new_key+':'+key)
        for previous in old_keys:
            old_hash = session_store._digest(previous+':'+key)
            row = registration._execute(db, 'SELECT step FROM totp_steps WHERE account_hash=?', (old_hash,)).fetchone()
            if row:
                registration._execute(db, 'INSERT INTO totp_steps(account_hash,step) VALUES (?,?) ON CONFLICT(account_hash) DO UPDATE SET step=excluded.step WHERE totp_steps.step<excluded.step', (new_hash, row[0]))
                registration._execute(db, 'DELETE FROM totp_steps WHERE account_hash=?', (old_hash,))


def confirm(user, data):
    code = data.get('code') if isinstance(data, dict) else None
    if not isinstance(code, str) or len(code) != 6 or not code.isascii() or not code.isdigit():
        raise ValueError(INVALID)
    tenant, changed = _scope(user), None
    reference = json.dumps({key: user.get(key) for key in ('id', 'email', 'tenant')}, sort_keys=True)
    with registration._decision_database(tenant) as db:
        lock = ' FOR UPDATE' if session_store._using_postgres() else ''
        row = registration._execute(db, "SELECT email,password_hash,code_hash FROM registration_requests WHERE id=? AND kind='email_change' AND status='email_pending' AND business_name=? AND tenant=? AND expires>? AND attempts<5"+lock,
            (session.get('email_change_request', ''), reference, tenant, time.time())).fetchone()
        if row:
            registration._execute(db, 'UPDATE registration_requests SET attempts=attempts+1 WHERE id=?', (session['email_change_request'],))
            found = _find_self(user, tenant, db)
            if (hmac.compare_digest(row[2], registration._code_hash(session['email_change_request'], code))
                    and hmac.compare_digest(row[1], security._account_revision(found[1]))):
                if not _available(row[0], tenant, found[0]):
                    raise ValueError(UNAVAILABLE)
                account_mfa._tables(db)
                secret = found[1].get('totp_secret') or account_mfa._enrolled_secret(db, user)
                updated = {**found[1], 'email': row[0], 'credential_version': secrets.token_hex(16)}
                # Registry identities use their login address as ID; tenant IDs are immutable.
                changed = {**user, 'email': row[0], 'id': row[0] if found[0] == 'registry' else user['id']}
                _move_security(db, user, changed, secret)
                account_passwords._store(found, tenant, updated, db)
                registration._execute(db, "UPDATE registration_requests SET status='email_used',password_hash='',code_hash='' WHERE id=?", (session['email_change_request'],))
    if not changed:
        raise ValueError(INVALID)
    from service.audit import AuditService
    AuditService().record(user=changed['email'], role='account', ip='', action='account.email_changed', target=tenant)
