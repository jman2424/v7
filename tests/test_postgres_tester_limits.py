from tests.test_tester_limits import _race


def test_native_postgres_concurrent_daily_limit(pg_runtime):
    from app import create_app
    app = create_app({'TESTING': True, 'SECRET_KEY': 'Native-daily-limit-test-secret-' + pg_runtime['tenant']})
    _race(app, pg_runtime['tenant'])


def test_native_paid_exemption_requires_own_paid_business(pg_runtime):
    from app import create_app
    from service import subscriptions, tester_limits
    app = create_app({'TESTING': True, 'SECRET_KEY': 'daily-paid-native-' + pg_runtime['tenant']})
    tenant, other = pg_runtime['tenant'], pg_runtime['other']
    with app.app_context():
        with subscriptions.connection(tenant) as db:
            db.execute("INSERT INTO billing_contracts(tenant,kind,ref,status,subscription) VALUES(?,'platform',?,'active','sub_native')", (tenant, tenant+'-ref'))
            db.execute("INSERT INTO billing_invoices VALUES(?,?,'platform','2026-10',1,NULL,9900,9900,0,'paid','[]',NULL)", (tenant+'-invoice', tenant))
        assert tester_limits._paid({'tenant': tenant, 'roles': ['business_staff']})
        assert not tester_limits._paid({'tenant': other, 'roles': ['business_staff']})
