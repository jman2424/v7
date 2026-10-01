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
    with _database() as db:
        _schema(db)
        managed = _execute(db, 'SELECT 1 FROM managed_businesses WHERE tenant=?', (tenant,)).fetchone()
    # Preserve existing businesses; all newly registered businesses require payments.
    if not managed:
        return {'active': True, 'status': 'active'}
    from service.subscriptions import connection
    with connection(tenant) as db:
        row = db.execute("SELECT status,implementation_paid FROM billing_contracts WHERE tenant=? AND kind='platform'", (tenant,)).fetchone()
        paid = db.execute("SELECT 1 FROM billing_invoices WHERE tenant=? AND kind='platform' AND status='paid' AND paid>0 LIMIT 1", (tenant,)).fetchone()
    active = bool(row and row['status']=='active' and row['implementation_paid'] and paid)
    return {'active': active, 'status': 'active' if active else 'awaiting_payments'}


def require_active(tenant):
    from flask import abort
    if not activation(tenant)['active']:
        abort(403, description='business_awaiting_activation')
