"""Read-only checks before accepting writes through the PostgreSQL runtime."""
from service.session_store import postgres_connection


_TABLES = {
    'tenants', 'business_documents', 'document_versions', 'operator_accounts',
    'crm_records', 'audit_records', 'migration_runs', 'schema_version', 'events',
    'leads', 'management_sessions', 'login_attempts', 'account_authenticators',
    'mfa_challenges', 'managed_businesses', 'registration_requests',
    'auth_login_failures', 'mfa_code_uses', 'trusted_devices', 'oidc_states', 'oidc_links',
    'billing_contracts', 'billing_invoices', 'billing_discounts',
    'billing_api_charges', 'billing_references', 'webhook_inbox', 'api_usage',
    'recorded_sales', 'inventory_history', 'usage_exchange_rate', 'mcp_grants',
    'mcp_rate', 'sales_action_requests', 'sales_action_attempts',
}


def validate_postgres_storage(default_tenant):
    """Fail closed on missing schema, unsafe table ownership or public API grants.

    This never creates tables, imports data, or falls back to local storage.
    Migration versions are private to the migration owner; check the required
    runtime objects through PostgreSQL's catalogs instead of granting access.
    """
    with postgres_connection(default_tenant) as db:
        tables = db.execute(
            "SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity,"
            "pg_has_role(current_user,c.relowner,'USAGE') "
            "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='v7_private' AND c.relkind='r' AND c.relname=ANY(%s)",
            (sorted(_TABLES),),
        ).fetchall()
        if ({row[0] for row in tables} != _TABLES
                or any(not row[1] or not row[2] or row[3] for row in tables)):
            raise RuntimeError('Complete restricted PostgreSQL schema required')
        exposed = db.execute(
            "SELECT rolname FROM pg_roles WHERE rolname=ANY(%s) AND "
            "(has_schema_privilege(oid,'v7_private','USAGE') "
            "OR pg_has_role(oid,'v7_backend','MEMBER'))",
            (['anon', 'authenticated', 'service_role'],),
        ).fetchall()
        if exposed:
            raise RuntimeError('Private PostgreSQL storage must not be exposed to Data API roles')
        auth_keys = dict(db.execute(
            "SELECT c.relname,pg_get_constraintdef(k.oid) FROM pg_constraint k "
            "JOIN pg_class c ON c.oid=k.conrelid "
            "JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='v7_private' AND k.contype='p' "
            "AND c.relname=ANY(%s)",
            (['auth_login_failures', 'mfa_code_uses', 'trusted_devices', 'oidc_states', 'oidc_links'],),
        ).fetchall())
        if auth_keys != {
            'auth_login_failures': 'PRIMARY KEY (attempt)',
            'mfa_code_uses': 'PRIMARY KEY (account, secret_hash, timestep)',
            'trusted_devices': 'PRIMARY KEY (token_hash)',
            'oidc_states': 'PRIMARY KEY (state_hash)',
            'oidc_links': 'PRIMARY KEY (provider, client_id, issuer, subject)',
        }:
            raise RuntimeError('PostgreSQL authentication migrations are incomplete')
        links = db.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid='v7_private.oidc_links'::regclass AND contype='u'",
        ).fetchall()
        if ('UNIQUE (provider, client_id, account)',) not in links:
            raise RuntimeError('PostgreSQL authentication migrations are incomplete')
        # Audio accounting and gated platform inventory are both required for
        # the completed runtime; an earlier schema is not sufficient.
        audio = db.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_schema='v7_private' "
            "AND table_name='api_usage' AND column_name='audio_seconds'",
        ).fetchone()
        inventory = db.execute(
            "SELECT p.prosecdef,p.proconfig FROM pg_proc p "
            "WHERE p.oid=to_regprocedure('v7_private.list_platform_tenant_keys(text,integer,integer)') "
            "AND has_function_privilege(current_user,p.oid,'EXECUTE')",
        ).fetchone()
        snapshots = db.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid='v7_private.document_versions'::regclass "
            "AND conname='document_versions_filename_check' AND contype='c'",
        ).fetchone()
        if (not audio or not inventory or not inventory[0]
                or not snapshots or "'_snapshot.json'::text" not in snapshots[0]
                or 'search_path=pg_catalog' not in (inventory[1] or [])):
            raise RuntimeError('PostgreSQL runtime migrations are incomplete')
        if db.execute('SELECT 1 FROM v7_private.tenants WHERE tenant=%s',
                      (default_tenant,)).fetchone() is None:
            raise RuntimeError('Default PostgreSQL tenant must be imported before startup')
