"""Server-owned business ownership and payment activation state."""
import json

from service import session_store


def _schema(db):
    if session_store._using_postgres():
        return
    db.execute('CREATE TABLE IF NOT EXISTS managed_businesses (tenant TEXT PRIMARY KEY, owner TEXT)')


def _database():
    return session_store.postgres_connection() if session_store._using_postgres() else session_store.connection()


def _execute(db, sql, params=()):
    return db.execute(sql.replace('?', '%s') if session_store._using_postgres() else sql, params)


def owner_key(user):
    return json.dumps([user['id'], user['email'], user.get('tenant')], separators=(',', ':'))


def register(tenant, owner=None):
    with _database() as db:
        _schema(db)
        if not session_store._using_postgres():
            # Serialize the reservation across workers before publishing a
            # workspace. Keys are ASCII; SQLite lower() matches casefold().
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM managed_businesses WHERE lower(tenant)=lower(?)', (tenant,)).fetchone():
                raise ValueError('tenant_exists')
        _execute(db, 'INSERT INTO managed_businesses VALUES (?,?)', (tenant, owner_key(owner) if owner else None))


def unregister(tenant):
    with _database() as db:
        _schema(db)
        _execute(db, 'DELETE FROM managed_businesses WHERE tenant=?', (tenant,))


def owned_tenants(user):
    if 'business_owner' not in user.get('roles', []):
        return []
    with _database() as db:
        _schema(db)
        keys = [row[0] for row in _execute(db, 'SELECT tenant FROM managed_businesses WHERE owner=?', (owner_key(user),))]
        if session_store._using_postgres():
            return keys
        # Older SQLite logins could use a directory case alias as their home
        # tenant. Canonical login must retain those existing ownership records;
        # account ID and email remain exact, and stored keys are never rewritten.
        from flask import current_app, has_app_context
        if not has_app_context() or not isinstance(user.get('tenant'), str):
            return keys
        storage = current_app.container.storage
        home = storage.canonical_tenant_key(user['tenant'])
        if not storage.tenant_exists(home):
            return keys
        for tenant, saved in db.execute('SELECT tenant,owner FROM managed_businesses WHERE owner IS NOT NULL'):
            try:
                identity = json.loads(saved)
                if (not isinstance(identity, list) or len(identity) != 3
                        or identity[:2] != [user['id'], user['email']]
                        or not isinstance(identity[2], str)
                        or storage.validate_tenant_key(identity[2]).casefold() != home.casefold()):
                    continue
            except (ValueError, TypeError):
                continue
            if tenant not in keys:
                keys.append(tenant)
        return keys


def activation(tenant):
    from service.business_applications import ApplicationError, require_eligible
    try:
        require_eligible(tenant, activation=True)
    except ApplicationError:
        return {'active': False, 'status': 'awaiting_business_approval'}
    with _database() as db:
        _schema(db)
        managed = _execute(db, 'SELECT owner FROM managed_businesses WHERE tenant=?', (tenant,)).fetchone()
    # Preserve existing businesses; newly registered commercial businesses require payments.
    if not managed:
        return {'active': True, 'status': 'active'}
    from flask import current_app, has_app_context
    if has_app_context() and managed[0] is None:
        container = getattr(current_app, 'container', None)
        settings = getattr(container, 'settings', None)
        internal_tenant = getattr(settings, 'PLATFORM_MARKETING_TENANT', '')
        if internal_tenant and tenant == internal_tenant:
            # Only one deployment-selected platform-owned business qualifies.
            # This grants access, never creates a payment or changes an invoice.
            return {'active': True, 'status': 'platform_internal'}
    from service.subscriptions import connection
    from service.subscriptions import complimentary_plan
    if complimentary_plan(tenant):
        return {'active': True, 'status': 'complimentary'}
    with connection(tenant) as db:
        row = db.execute("SELECT status FROM billing_contracts WHERE tenant=? AND kind='platform'", (tenant,)).fetchone()
        paid = db.execute("SELECT 1 FROM billing_invoices WHERE tenant=? AND kind='platform' AND status='paid' AND paid>0 LIMIT 1", (tenant,)).fetchone()
    # The one-time assistance fee is an optional add-on: a confirmed, paid
    # subscription alone activates the business.
    if row and paid and row['status'] == 'active':
        return {'active': True, 'status': 'active'}
    from service import payment_recovery
    if row and paid and row['status'] in payment_recovery.FAILED_STATUSES:
        # A failed renewal keeps service running for seven days from the first
        # failure, then stops. Data and records are untouched either way.
        window = payment_recovery.current(tenant)
        import time
        if window and time.time() < window['ends']:
            return {'active': True, 'status': 'payment_recovery', 'grace_ends': window['ends']}
        return {'active': False, 'status': 'billing_suspended',
                'grace_ends': window['ends'] if window else None}
    return {'active': False, 'status': 'awaiting_payments'}


def unavailable_notice(profile):
    """Fixed customer wording for a business whose assistant is switched off.

    Uses only the business's own saved public name and contact email. It never
    says why the assistant is unavailable.
    """
    from service.business_channels import address
    profile = profile if isinstance(profile, dict) else {}
    name = profile.get('name')
    name = ' '.join(name.split())[:80] if isinstance(name, str) else ''
    name = name if name and all(ch.isprintable() and ch not in '<>' for ch in name) else 'the business'
    try:
        email = address(profile.get('email'))
    except ValueError:
        email = ''
    if email:
        return f'This assistant is currently unavailable. Please contact {name} by email at {email}.'
    return f'This assistant is currently unavailable. Please contact {name} directly.'


_notified: dict[str, float] = {}


def notice_due(tenant, sender, *, now=None, interval=86400):
    """Best-effort limit: one unavailable notice per sender per day per worker."""
    import hashlib
    import time
    now = time.time() if now is None else now
    key = hashlib.sha256(f'{tenant}\0{sender}'.encode()).hexdigest()
    if len(_notified) > 5000:
        for old in [k for k, seen in _notified.items() if now - seen >= interval]:
            _notified.pop(old, None)
        if len(_notified) > 5000:
            return False
    if key in _notified and now - _notified[key] < interval:
        return False
    _notified[key] = now
    return True


def require_active(tenant):
    from flask import abort
    if not activation(tenant)['active']:
        abort(403, description='business_awaiting_activation')
