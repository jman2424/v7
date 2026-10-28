"""Native role/RLS rejection and atomic lead writes on disposable PostgreSQL."""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from service import analytics_db, session_store
from service.analytics_service import AnalyticsService


def test_native_combined_lead_write_uses_one_transaction_and_keeps_tenants(pg_runtime, monkeypatch):
    tenant, other = pg_runtime['tenant'], pg_runtime['other']
    analytics_db.upsert_lead(tenant=tenant, lead_id='shared-id', name='Synthetic customer', phone='test-only')
    # Startup validation is not a chat write; measure the per-turn operation.
    analytics = AnalyticsService(SimpleNamespace())
    opened = []
    original = session_store.postgres_connection

    @contextmanager
    def counted(scope):
        opened.append(scope)
        with original(scope) as db:
            yield db

    with monkeypatch.context() as context:
        context.setattr(session_store, 'postgres_connection', counted)
        analytics.upsert_lead_session(tenant=tenant, lead_id='shared-id', session_id='new')
    assert opened == [tenant]
    analytics_db.upsert_lead_session(tenant=other, lead_id='shared-id', session_id='other', name='Other')
    with original(tenant) as db:
        assert db.execute('SELECT name,phone,last_session_id FROM v7_private.leads '
                          'WHERE tenant=%s AND lead_id=%s', (tenant, 'shared-id')).fetchone() == (
                              'Synthetic customer', 'test-only', 'new')
        assert db.execute('SELECT count(*) FROM v7_private.leads WHERE tenant=%s', (other,)).fetchone()[0] == 0


@pytest.mark.parametrize('boundary', ['extra_membership', 'unforced_security_table', 'bypass_rls'])
def test_native_combined_scope_cannot_yield_after_authority_change(pg_runtime, boundary):
    from psycopg import sql
    admin, role = pg_runtime['admin'], pg_runtime['role']
    if boundary == 'extra_membership':
        change = sql.SQL('GRANT anon TO {}').format(sql.Identifier(role))
        restore = sql.SQL('REVOKE anon FROM {}').format(sql.Identifier(role))
    elif boundary == 'bypass_rls':
        change = sql.SQL('ALTER ROLE {} BYPASSRLS').format(sql.Identifier(role))
        restore = sql.SQL('ALTER ROLE {} NOBYPASSRLS').format(sql.Identifier(role))
    else:
        change = sql.SQL('ALTER TABLE v7_private.management_sessions NO FORCE ROW LEVEL SECURITY')
        restore = sql.SQL('ALTER TABLE v7_private.management_sessions FORCE ROW LEVEL SECURITY')
    admin.execute(change)
    try:
        with pytest.raises(RuntimeError, match='not restricted'):
            with session_store.postgres_connection(pg_runtime['tenant']):
                pytest.fail('A changed security scope reached business code')
    finally:
        admin.execute(restore)
