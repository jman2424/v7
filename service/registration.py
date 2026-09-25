"""Verified owner onboarding and owner-approved, least-privilege join requests."""
import hashlib
import hmac
import re
import secrets
import time

from flask import current_app, session
from werkzeug.security import generate_password_hash

from retrieval.storage import Storage
from service import registration_mail, session_store
from service.account_service import AccountService, _EMAIL_RE

_MAILBOX_RE = re.compile(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9.-]+")


def _schema(db):
    if session_store._using_postgres():
        return
    db.execute('''CREATE TABLE IF NOT EXISTS registration_requests (
        id TEXT PRIMARY KEY, email TEXT NOT NULL, password_hash TEXT NOT NULL,
        kind TEXT NOT NULL, tenant TEXT NOT NULL, business_name TEXT NOT NULL,
        code_hash TEXT NOT NULL, expires REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL, created REAL NOT NULL, decided_by TEXT)''')
    db.execute('CREATE INDEX IF NOT EXISTS registration_email_time ON registration_requests(email,created)')
    db.execute('CREATE INDEX IF NOT EXISTS registration_tenant_status ON registration_requests(tenant,status)')


def _database():
    return session_store.postgres_connection() if session_store._using_postgres() else session_store.connection()


def _execute(db, sql, params=()):
    return db.execute(sql.replace('?', '%s') if session_store._using_postgres() else sql, params)


def _lock_request_key(db, key):
    if session_store._using_postgres():
        lock = int.from_bytes(bytes.fromhex(session_store._digest(key))[:8], 'big', signed=True)
        db.execute('SELECT pg_advisory_xact_lock(%s)', (lock,))
    else:
        db.execute('BEGIN IMMEDIATE')


def _code_hash(request_id, code):
    return hmac.new(current_app.secret_key.encode(), f'{request_id}:{code}'.encode(), hashlib.sha256).hexdigest()


def start(data):
    if not registration_mail.configured():
        raise RuntimeError('Email verification is not configured. Contact the platform operator.')
    if not isinstance(data, dict) or any(not isinstance(data.get(k, ''), str) for k in ('email', 'password', 'kind', 'tenant', 'business_name')):
        raise ValueError('Enter valid account details.')
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    kind = data.get('kind')
    if len(email) > 254 or not _MAILBOX_RE.fullmatch(email) or not _EMAIL_RE.fullmatch(email):
        raise ValueError('Enter a valid email address.')
    if not 12 <= len(password) <= 256:
        raise ValueError('Use a password between 12 and 256 characters.')
    if kind not in {'owner', 'join'}:
        raise ValueError('Choose create a business or request to join.')
    tenant = Storage.validate_tenant_key(data.get('tenant', '').strip())
    name = data.get('business_name', '').strip()
    if kind == 'owner' and not 1 <= len(name) <= 120:
        raise ValueError('Enter a business name up to 120 characters.')
    if len(name) > 120:
        raise ValueError('Business name is too long.')
    now = time.time()
    request_id = secrets.token_urlsafe(32)
    code = f'{secrets.randbelow(1000000):06d}'
    with _database() as db:
        _schema(db)
        _lock_request_key(db, email)
        # Remove abandoned secrets, while keeping a bounded window for abuse limits.
        _execute(db, "UPDATE registration_requests SET password_hash='',code_hash='',status='expired' WHERE status='verification' AND expires<?", (now,))
        _execute(db, 'DELETE FROM registration_requests WHERE created<?', (now-30*86400,))
        recent = _execute(db, 'SELECT COUNT(*),MAX(created) FROM registration_requests WHERE email=? AND created>?', (email, now-86400)).fetchone()
        if recent[0] >= 5 or (recent[1] and recent[1] > now-60):
            raise ValueError('Please wait before requesting another verification code.')
        _execute(db, 'INSERT INTO registration_requests (id,email,password_hash,kind,tenant,business_name,code_hash,expires,status,created) VALUES (?,?,?,?,?,?,?,?,?,?)',
                   (request_id,email,generate_password_hash(password),kind,tenant,name,_code_hash(request_id,code),now+600,'verification',now))
    try:
        registration_mail.send_code(email, code)
    except Exception as exc:
        with _database() as db:
            # Failed deliveries must not consume the email cooldown or daily quota.
            _execute(db, "DELETE FROM registration_requests WHERE id=? AND status='verification'", (request_id,))
        current_app.logger.warning('Registration verification mail could not be sent (%s)', type(exc).__name__)
        raise RuntimeError('Verification email could not be sent. Try later or contact the operator.') from None
    session['registration_request'] = request_id
    return {'status': 'verification', 'email': email, 'tenant': tenant}


def status():
    with _database() as db:
        _schema(db)
        _execute(db, "UPDATE registration_requests SET password_hash='',code_hash='',status='expired' WHERE (status='verification' AND expires<?) OR (status='pending' AND created<?)", (time.time(),time.time()-30*86400))
        row = _execute(db, 'SELECT email,tenant,status,expires,attempts,created FROM registration_requests WHERE id=?', (session.get('registration_request', ''),)).fetchone()
    if not row:
        return None
    state = row[2]
    if (state == 'verification' and (row[3] < time.time() or row[4] >= 5)) or (state == 'pending' and row[5] < time.time()-30*86400):
        state = 'expired'
    return {'email': row[0], 'tenant': row[1], 'status': state}


def _reserved_email(email):
    import os
    from service.security import _registry_users
    if email == os.getenv('ADMIN_USERNAME', '').strip().lower():
        return True
    return any(str(user.get('email', '')).strip().lower() == email for user in _registry_users(current_app.container))


def confirm(code):
    if not isinstance(code, str) or len(code) != 6 or not code.isascii() or not code.isdigit():
        raise ValueError('Enter the six-digit verification code.')
    request_id = session.get('registration_request', '')
    storage = current_app.container.storage
    invalid = False
    owner_details = None
    with _database() as db:
        _schema(db)
        if not session_store._using_postgres():
            db.execute('BEGIN IMMEDIATE')
        lock = ' FOR UPDATE' if session_store._using_postgres() else ''
        row = _execute(db, "SELECT email,password_hash,kind,tenant,business_name,code_hash FROM registration_requests WHERE id=? AND status='verification' AND expires>? AND attempts<5" + lock, (request_id,time.time())).fetchone()
        if not row:
            raise ValueError('Verification expired or already used. Start again.')
        email, password_hash, kind, tenant, name, expected = row
        if not hmac.compare_digest(expected, _code_hash(request_id,code)):
            _execute(db, 'UPDATE registration_requests SET attempts=attempts+1 WHERE id=?', (request_id,))
            _execute(db, "UPDATE registration_requests SET status='expired',password_hash='',code_hash='' WHERE id=? AND attempts>=5", (request_id,))
            invalid = True
        else:
            if _reserved_email(email):
                raise ValueError('An account already exists for this email. Use the existing sign-in.')
            if kind == 'join':
                if not storage.tenant_exists(tenant):
                    raise ValueError('This company request cannot be completed. Check the company key with its owner.')
                if any(a['email'] == email for a in AccountService(storage).list_accounts(tenant)):
                    raise ValueError('An account already exists for this company. Use the existing sign-in.')
                _execute(db, "UPDATE registration_requests SET status='pending',code_hash='' WHERE id=?", (request_id,))
            else:
                owner_details = (email,password_hash,tenant,name)
                _execute(db, "UPDATE registration_requests SET status='creating',code_hash='' WHERE id=?", (request_id,))
    if owner_details:
        email,password_hash,tenant,name = owner_details
        from service.tenant_service import TenantService
        identity = {'id':'signup:'+request_id,'email':email,'tenant':tenant,'roles':['business_owner']}
        try:
            TenantService(storage).create_tenant(tenant,name,owner=identity,
                initial_account={'id':identity['id'],'email':email,'password_hash':password_hash,'roles':['business_owner'],'active':True,'permissions':[]})
        except Exception:
            with _database() as db:
                _execute(db, "UPDATE registration_requests SET status='failed',password_hash='' WHERE id=?", (request_id,))
            raise ValueError('The workspace could not be created. The company key may already be in use. Sign in if your account was created, or contact the operator.') from None
        with _database() as db:
            _execute(db, "UPDATE registration_requests SET status='approved',password_hash='' WHERE id=?", (request_id,))
    if invalid:
        raise ValueError('Code not accepted. Check your email and try again.')
    return status()


def pending(tenant):
    with _database() as db:
        _schema(db)
        rows = _execute(db, "SELECT id,email,created FROM registration_requests WHERE tenant=? AND status='pending' AND created>? ORDER BY created LIMIT 100", (tenant,time.time()-30*86400)).fetchall()
    return [{'id':r[0],'email':r[1],'created':r[2]} for r in rows]


def decide(tenant, request_id, approve, actor):
    with _database() as db:
        _schema(db)
        if not session_store._using_postgres():
            db.execute('BEGIN IMMEDIATE')
        lock = ' FOR UPDATE' if session_store._using_postgres() else ''
        row = _execute(db, "SELECT email,password_hash FROM registration_requests WHERE id=? AND tenant=? AND status='pending' AND created>?" + lock, (request_id,tenant,time.time()-30*86400)).fetchone()
        if not row:
            raise ValueError('Request not found or already processed.')
        if approve:
            service = AccountService(current_app.container.storage)
            accounts = service._accounts(tenant)
            if any(a.get('email','').lower() == row[0] for a in accounts):
                raise ValueError('An account already exists for this email in this company.')
            # Never accept client-provided roles, account IDs, activation or permissions.
            from service.account_service import ACCOUNT_FILE
            account = {'id':'signup:'+request_id,'email':row[0],'password_hash':row[1],
                       'roles':['business_staff'],'active':True,'permissions':[]}
            service.storage.write_json(tenant,ACCOUNT_FILE,[*accounts,account])
        _execute(db, "UPDATE registration_requests SET status=?,password_hash='',code_hash='',decided_by=? WHERE id=?", ('approved' if approve else 'rejected',actor,request_id))
