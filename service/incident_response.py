"""Emergency access revocation: sign out a business (or every business) everywhere at once."""
from __future__ import annotations

import re
from typing import Any

from service import session_store

_TENANT = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}')


def _execute(db: Any, sql: str, params: tuple = ()) -> Any:
    return db.execute(sql.replace('?', '%s') if session_store._using_postgres() else sql, params)


def _predicates() -> dict[str, str]:
    """Each store keeps the owning business inside its JSON record."""
    if session_store._using_postgres():
        return {'sessions': "identity::jsonb ->> 'tenant'",
                'devices': "account::jsonb ->> 2",
                'mcp': "payload::jsonb #>> '{identity,tenant}'"}
    return {'sessions': "json_extract(identity, '$.tenant')",
            'devices': "json_extract(account, '$[2]')",
            'mcp': "json_extract(payload, '$.identity.tenant')"}


def _not_platform(column: str, path: str) -> str:
    """Never sign out a platform administrator, whatever business their record names."""
    if session_store._using_postgres():
        roles = f"{column}::jsonb #> '{{{path.replace('.', ',')}}}'"
        return (f" AND NOT COALESCE(jsonb_exists_any({roles}, array['admin','platform_admin']), false)")
    return (f" AND NOT EXISTS (SELECT 1 FROM json_each({column}, '$.{path}') "
            "WHERE value IN ('admin','platform_admin'))")


def revoke_business_access(tenant: str | None) -> dict[str, int]:
    """Delete sign-in sessions, remembered devices and MCP connections.

    ``tenant`` limits this to one business; ``None`` means every business account.
    Platform administrator sessions are never touched here, so the person
    responding to an incident keeps access. Passwords and authenticators are
    unchanged; people simply have to sign in again (with their authenticator).
    """
    if tenant is not None and not (isinstance(tenant, str) and _TENANT.fullmatch(tenant)):
        raise ValueError('invalid_tenant')
    fields = _predicates()
    # Business accounts always carry a tenant; platform administrators carry none.
    where = '{field}=?' if tenant is not None else "COALESCE({field},'')<>''"
    params = (tenant,) if tenant is not None else ()
    counts = {}
    from service import mcp_auth, trusted_devices
    with (session_store.postgres_connection() if session_store._using_postgres() else session_store.connection()) as db:
        table = 'v7_private.management_sessions' if session_store._using_postgres() else 'management_sessions'
        if not session_store._using_postgres():
            db.execute('CREATE TABLE IF NOT EXISTS management_sessions (token_hash TEXT PRIMARY KEY, identity TEXT NOT NULL, '
                       'revision TEXT NOT NULL, expires REAL NOT NULL)')
        counts['sessions'] = _execute(db, f'DELETE FROM {table} WHERE ' + where.format(field=fields['sessions'])
                                      + _not_platform('identity', 'roles'), params).rowcount
    with trusted_devices._database() as db:
        trusted_devices._tables(db)
        counts['trusted_devices'] = _execute(db, 'DELETE FROM trusted_devices WHERE ' + where.format(field=fields['devices']),
                                             params).rowcount
    with mcp_auth.database() as db:
        counts['mcp_connections'] = _execute(db, 'DELETE FROM mcp_grants WHERE ' + where.format(field=fields['mcp'])
                                             + _not_platform('payload', 'identity.roles'), params).rowcount
    return {key: max(int(value or 0), 0) for key, value in counts.items()}
