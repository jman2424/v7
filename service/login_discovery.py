"""Private account routing only; callers still verify credentials and MFA."""
import os

from retrieval.storage import Storage
from service import security, session_store


def tenant_for_email(container, email):
    """Return one unambiguous configured tenant, never expose matches publicly."""
    fallback = container.settings.BUSINESS_KEY
    registry = [row for row in security._registry_users(container)
                if str(row.get('email') or '').strip().lower() == email]
    if registry:
        if len(registry) != 1:
            return None
        row = registry[0]
        candidate = fallback if row.get('role') in {'admin', 'platform_admin'} else row.get('tenant')
    elif email == os.getenv('ADMIN_USERNAME', '').strip().lower():
        candidate = fallback
    else:
        configured = [row for row in security._business_users()
                      if str(row.get('email') or '').strip().lower() == email]
        if configured:
            if len(configured) != 1:
                return None
            row = configured[0]
            roles = row.get('roles', [])
            candidate = fallback if isinstance(roles, list) and {'admin','platform_admin'}.intersection(roles) else row.get('tenant')
        else:
            if session_store._using_postgres():
                with session_store.postgres_connection() as db:
                    matches = db.execute('SELECT tenant FROM v7_private.email_login_tenants(%s)', (email,)).fetchall()
                candidates = [row[0] for row in matches]
            else:
                candidates = []
                for tenant in container.storage.tenant_keys():
                    candidates += [tenant for row in security._stored_business_users(container, tenant)
                                   if str(row.get('email') or '').strip().lower() == email]
                    if len(candidates) > 1:
                        break
            if len(candidates) != 1:
                return None
            candidate = candidates[0]
    try:
        candidate = container.storage.canonical_tenant_key(Storage.validate_tenant_key(candidate))
        return candidate if container.storage.tenant_exists(candidate) else None
    except (ValueError, TypeError):
        return None
