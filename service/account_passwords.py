"""Session-bound recovery using the existing private verification request store.

Only the authenticated account or the exact mailed recovery challenge can change
a password. Identity, roles, authenticator secrets and permissions are preserved.
"""
import hmac
import json
import os
import secrets
import tempfile
import time
from pathlib import Path

from flask import current_app, session

from retrieval.storage import Storage
from service import registration, registration_mail, security, session_store
from service.account_service import ACCOUNT_FILE, AccountService, _EMAIL_RE

GENERIC_NOTICE = 'If an eligible account matches, a reset code has been sent. Check your email.'
INVALID_CODE = 'Reset code is invalid, expired or already used. Request a new code.'


def _find(email, tenant, db=None):
    """Apply registry precedence and reject ambiguous, inactive or mismatched accounts."""
    container = current_app.container
    if db is not None and session_store._using_postgres():
        rows = db.execute('SELECT payload FROM operator_accounts WHERE email=%s FOR UPDATE', (email,)).fetchall()
        registry = [row[0] for row in rows]
    else:
        registry = [row for row in security._registry_users(container)
                    if str(row.get('email') or '').strip().lower() == email]
    if registry:
        if len(registry) != 1:
            return None
        record = registry[0]
        role = record.get('role')
        if record.get('disabled') or role not in security._MANAGEMENT_ROLES:
            return None
        if role in {'business_owner', 'business_staff'}:
            try:
                assigned = container.storage.canonical_tenant_key(Storage.validate_tenant_key(record.get('tenant')))
            except (TypeError, ValueError):
                return None
            if assigned != tenant:
                return None
        return 'registry', record, {'id': email, 'email': email, 'tenant': tenant if role in {'business_owner', 'business_staff'} else None}
    # Environment / legacy accounts remain operator-configured, never rewritten.
    if email == os.getenv('ADMIN_USERNAME', '').strip().lower():
        return None
    if any(str(row.get('email') or '').strip().lower() == email for row in security._business_users()):
        return None
    rows = [row for row in AccountService(container.storage)._accounts(tenant)
            if str(row.get('email') or '').strip().lower() == email]
    if len(rows) != 1:
        return None
    record = rows[0]
    if (record.get('active') is False or record.get('disabled') or not security._valid_roles(record.get('roles'))
            or not isinstance(record.get('id'), str) or not record['id']
            or {'admin', 'platform_admin'}.intersection(record['roles'])):
        return None
    return 'tenant', record, {'id': record.get('id'), 'email': email, 'tenant': tenant}


def _write(found, tenant, password, db):
    source, record, identity = found
    updated = {**record, 'password_hash': security.hash_password(password), 'credential_version': secrets.token_hex(16)}
    if source == 'tenant':
        accounts = AccountService(current_app.container.storage)._accounts(tenant)
        accounts = [updated if row.get('id') == record.get('id') else row for row in accounts]
        current_app.container.storage._write_json(tenant, ACCOUNT_FILE, accounts)
    elif session_store._using_postgres():
        db.execute('UPDATE operator_accounts SET payload=%s::jsonb WHERE email=%s', (json.dumps(updated), identity['email']))
    else:
        # Registry paths have already been validated by _registry_users.
        path = Path(os.environ['ADMIN_USERS_FILE']).expanduser().resolve()
        payload = json.loads(path.read_text(encoding='utf-8'))
        payload['users'] = [updated if str(row.get('email') or '').strip().lower() == identity['email'] else row
                            for row in payload['users']]
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(payload, handle)
            os.chmod(temporary, path.stat().st_mode & 0o777)
            os.replace(temporary, path)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()
    return identity


def _password(data, field='password'):
    value = data.get(field) if isinstance(data, dict) else None
    if not isinstance(value, str) or not 12 <= len(value) <= 256:
        raise ValueError('Use a password between 12 and 256 characters.')
    return value


def _tenant(value):
    return current_app.container.storage.canonical_tenant_key(Storage.validate_tenant_key(value))


def start(data):
    if not registration_mail.configured():
        raise RuntimeError('Password reset email is not configured. Contact the platform operator.')
    if not isinstance(data, dict) or not isinstance(data.get('email'), str) or not isinstance(data.get('tenant'), str):
        raise ValueError('Enter your company key and account email.')
    email = data['email'].strip().lower()
    if len(email) > 254 or not _EMAIL_RE.fullmatch(email):
        raise ValueError('Enter a valid email address.')
    # Unknown companies deliberately receive the same response as missing accounts.
    tenant = _tenant(data['tenant'].strip())
    now, request_id, code = time.time(), secrets.token_urlsafe(32), f'{secrets.randbelow(1000000):06d}'
    found = _find(email, tenant) if current_app.container.storage.tenant_exists(tenant) else None
    revision = security._account_revision(found[1]) if found else ''
    with registration._database() as db:
        registration._schema(db)
        registration._lock_request_key(db, 'password-reset:' + email)
        registration._execute(db, "DELETE FROM registration_requests WHERE kind='password_reset' AND created<?", (now-86400,))
        recent = registration._execute(db, "SELECT COUNT(*),MAX(created) FROM registration_requests WHERE kind='password_reset' AND email=? AND created>?", (email, now-86400)).fetchone()
        if recent[0] >= 5 or (recent[1] and recent[1] > now-60):
            raise ValueError('Please wait before requesting another reset code.')
        registration._execute(db, "INSERT INTO registration_requests (id,email,password_hash,kind,tenant,business_name,code_hash,expires,status,created) VALUES (?,?,?,?,?,?,?,?,?,?)",
                              (request_id, email, revision, 'password_reset', tenant, '', registration._code_hash(request_id, code), now+600, 'reset_pending', now))
    session['password_reset_request'] = request_id
    if found:
        try:
            registration_mail.send_reset_code(email, code)
        except Exception as exc:
            # Do not reveal account existence or provider details on delivery failure.
            current_app.logger.warning('Password reset mail failed (%s)', type(exc).__name__)
            with registration._database() as db:
                registration._execute(db, "UPDATE registration_requests SET status='reset_failed',password_hash='',code_hash='' WHERE id=?", (request_id,))
    return GENERIC_NOTICE


def _finish(identity):
    from service.trusted_devices import revoke_account
    revoke_account(identity)
    from service.audit import AuditService
    AuditService().record(user=identity['email'], role='account', ip='', action='account.password_changed', target=identity.get('tenant') or 'platform')


def confirm(data):
    password = _password(data)
    code = data.get('code')
    if not isinstance(code, str) or not code.isascii() or len(code) != 6 or not code.isdigit():
        raise ValueError(INVALID_CODE)
    request_id = session.get('password_reset_request', '')
    # Read only server-held scope, then lock that tenant and the challenge together.
    with registration._database() as db:
        registration._schema(db)
        row = registration._execute(db, "SELECT tenant FROM registration_requests WHERE id=? AND kind='password_reset'", (request_id,)).fetchone()
    if not row or not current_app.container.storage.tenant_exists(row[0]):
        raise ValueError(INVALID_CODE)
    tenant, identity = row[0], None
    with registration._decision_database(tenant) as db:
        lock = ' FOR UPDATE' if session_store._using_postgres() else ''
        row = registration._execute(db, "SELECT email,password_hash,code_hash FROM registration_requests WHERE id=? AND kind='password_reset' AND status='reset_pending' AND expires>? AND attempts<5" + lock, (request_id, time.time())).fetchone()
        if row:
            registration._execute(db, 'UPDATE registration_requests SET attempts=attempts+1 WHERE id=?', (request_id,))
            found = _find(row[0], tenant, db)
            if (found and hmac.compare_digest(row[2], registration._code_hash(request_id, code))
                    and hmac.compare_digest(row[1], security._account_revision(found[1]))):
                identity = _write(found, tenant, password, db)
                registration._execute(db, "UPDATE registration_requests SET status='reset_used',password_hash='',code_hash='' WHERE id=?", (request_id,))
    if not identity:
        raise ValueError(INVALID_CODE)
    _finish(identity)


def details(user):
    tenant = _tenant(user.get('tenant') or current_app.container.settings.BUSINESS_KEY)
    found = _find(user['email'], tenant)
    return {'email': user['email'], 'tenant': user.get('tenant'), 'password_change_available': bool(found),
            'reset_email_available': registration_mail.configured() and bool(_EMAIL_RE.fullmatch(user['email'])) and bool(found)}


def change(user, data):
    password = _password(data)
    old = data.get('current_password')
    if not isinstance(old, str) or not old or len(old) > 1024:
        raise ValueError('Current password was not accepted.')
    tenant = _tenant(user.get('tenant') or current_app.container.settings.BUSINESS_KEY)
    with registration._decision_database(tenant) as db:
        found = _find(user['email'], tenant, db)
        if not found or found[2]['id'] != user['id'] or not security.verify_password(old, found[1].get('password_hash', '')):
            raise ValueError('Current password was not accepted.')
        identity = _write(found, tenant, password, db)
    _finish(identity)
