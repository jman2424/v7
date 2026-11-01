"""Real migration/RLS/transaction coverage in the existing disposable PG CI job."""
import json
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from service import business_applications as applications, session_store
from tests.test_business_applications import details


def configure(runtime):
    value = {**applications.DEFAULT_SETTINGS, 'intake_enabled': True,
             'legal_review_completed': True, 'owner_email': 'owner@example.test'}
    runtime['admin'].execute('INSERT INTO v7_private.business_application_settings VALUES (1,%s) '
        'ON CONFLICT(id) DO UPDATE SET value=excluded.value', (applications._json(value),))


def test_native_application_rls_and_private_api_roles(pg_runtime):
    configure(pg_runtime)
    tenant, other = pg_runtime['tenant'], pg_runtime['other']
    result = applications.submit_verified(tenant, 'applicant@example.test', details())
    assert result['status'] == 'PENDING_REVIEW'
    with session_store.postgres_connection(other) as db:
        assert db.execute('SELECT tenant FROM business_applications WHERE tenant=%s', (tenant,)).fetchone() is None
        import psycopg
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with db.transaction():
                db.execute("UPDATE business_applications SET tenant=%s WHERE tenant=%s", (other, tenant))
                db.execute("INSERT INTO business_applications(tenant,status,revision,details,contact_email,policy_version,created,updated) "
                           "VALUES(%s,'APPROVED',1,'{}','forged@example.test','v1',0,0)", (tenant,))
    admin = pg_runtime['admin']
    for table in ['business_applications', 'business_application_events', 'business_application_settings',
                  'business_application_permits', 'business_application_notifications']:
        for role in ('anon', 'authenticated', 'service_role'):
            assert not admin.execute('SELECT has_table_privilege(%s,%s,\'SELECT\')', (role, 'v7_private.' + table)).fetchone()[0]
    with session_store.postgres_connection() as db:
        assert db.execute('SELECT tenant FROM business_applications').fetchall() == []


def test_native_platform_inventory_requires_a_live_operator_session(pg_runtime, monkeypatch):
    configure(pg_runtime)
    tenant = pg_runtime['tenant']
    applications.submit_verified(tenant, 'applicant@example.test', details())
    admin = pg_runtime['admin']
    for role in ['business_owner', 'platform_admin']:
        token = session_store.create({'id': 'operator', 'email': 'reviewer@example.test', 'roles': [role]}, 'synthetic-revision')
        with session_store.postgres_connection() as db:
            db.execute("SELECT set_config('v7.application_session',%s,true)", (session_store._digest(token),))
            result = db.execute('SELECT tenant FROM business_applications WHERE tenant=%s', (tenant,)).fetchall()
            assert bool(result) == (role == 'platform_admin')
        if role == 'platform_admin':
            from flask import Flask, session
            app = Flask(__name__)
            app.secret_key = 'Synthetic-application-search-session'
            # The HTTP role gate is covered separately; exercise the native JSON
            # search under a real scoped DB operator session here.
            with app.test_request_context(), monkeypatch.context() as patch:
                session['management_token'] = token
                patch.setattr(applications, '_operator', lambda: {'id': 'operator'})
                assert applications.list_applications(search='detailing')['total'] >= 1
                assert applications.list_applications(search='gambling')['total'] == 0
        session_store.revoke(token)
        with session_store.postgres_connection() as db:
            db.execute("SELECT set_config('v7.application_session',%s,true)", (session_store._digest(token),))
            assert not db.execute('SELECT tenant FROM business_applications WHERE tenant=%s', (tenant,)).fetchall()
    assert admin.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='v7_private.business_applications'::regclass").fetchone() == (True, True)


def test_native_duplicate_application_is_serialized_and_rollback_is_atomic(pg_runtime):
    configure(pg_runtime)
    tenant = pg_runtime['tenant']
    def submit(_):
        try:
            applications.submit_verified(tenant, 'applicant@example.test', details())
            return True
        except (applications.ApplicationError, RuntimeError):
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(submit, [0, 1])) == [False, True]
    admin = pg_runtime['admin']
    assert admin.execute('SELECT count(*) FROM v7_private.business_applications WHERE tenant=%s', (tenant,)).fetchone()[0] == 1
    assert admin.execute("SELECT count(*) FROM v7_private.business_application_events WHERE tenant=%s AND kind='submitted'", (tenant,)).fetchone()[0] == 1
    assert admin.execute('SELECT count(*) FROM v7_private.business_application_notifications WHERE tenant=%s', (tenant,)).fetchone()[0] == 2
    other = pg_runtime['other']
    with pytest.raises(RuntimeError, match='synthetic rollback'):
        with session_store.postgres_connection(other) as db:
            applications.submit_verified(other, 'other@example.test', details(), db=db)
            raise RuntimeError('synthetic rollback')
    for table in ('business_applications', 'business_application_events', 'business_application_notifications'):
        assert admin.execute('SELECT count(*) FROM v7_private.' + table + ' WHERE tenant=%s', (other,)).fetchone()[0] == 0


def test_native_permits_are_tenant_bound_and_retention_cannot_rewrite_audit(pg_runtime):
    configure(pg_runtime)
    tenant, other = pg_runtime['tenant'], pg_runtime['other']
    applications.submit_verified(tenant, 'applicant@example.test', details())
    # Only the test migration owner seeds approval; runtime clients cannot
    # acquire platform inventory authority by passing roles or tenant JSON.
    admin = pg_runtime['admin']
    admin.execute("UPDATE v7_private.business_applications SET status='APPROVED' WHERE tenant=%s", (tenant,))
    applications.reserve_payment(tenant, 'pg-checkout-reference-' + tenant, 'platform')
    applications.bind_payment(tenant, 'pg-checkout-reference-' + tenant, 'cs_native')
    with applications.database(other) as db:
        assert applications._execute(db, 'SELECT reference FROM business_application_permits WHERE tenant=?', (tenant,)).fetchall() == []
    with session_store.postgres_connection(tenant) as db:
        import psycopg
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with db.transaction():
                db.execute("UPDATE business_application_events SET kind='APPROVED' WHERE tenant=%s", (tenant,))
    applications.settle_payment(tenant, 'pg-checkout-reference-' + tenant)
    applications.verify_payment(tenant, 'pg-checkout-reference-' + tenant, 'platform')
    from retrieval.storage import Storage
    storage = Storage(tenant)
    profile = storage.read_json(tenant, 'store_info.json')
    storage.write_json(tenant, 'store_info.json', {**profile, 'name':'A material identity change'})
    assert applications.get(tenant)['status'] == 'PENDING_REVIEW'
    assert applications.get(tenant)['existing_service_preserved']
    with pytest.raises(applications.ApplicationError, match='business_approval_required'):
        applications.reserve_payment(tenant, 'unapproved-second-reference', 'ai_credit')
