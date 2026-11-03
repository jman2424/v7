"""Offer policy uses existing tenant-isolated documents; no schema migration."""
from types import SimpleNamespace

from flask import Flask

from retrieval.storage import Storage
from service import platform_promotions as policy, session_store


def test_native_offer_policy_documents_are_scoped_and_reads_refresh_between_jobs(pg_runtime):
    tenant, other = pg_runtime['tenant'], pg_runtime['other']
    storage = Storage(tenant)
    app = Flask('native-platform-offers')
    app.container = SimpleNamespace(storage=storage, settings=SimpleNamespace(PLATFORM_MARKETING_TENANT=tenant))
    storage.write_json(tenant, policy.FILENAME, {'setup_enabled': False, 'highstreet_enabled': True})
    with app.app_context():
        assert policy.public_flags() == {'setup_enabled': False, 'highstreet_enabled': True}
        storage.write_json(tenant, policy.FILENAME, policy.DEFAULTS.copy())
        assert policy.public_flags() == policy.DEFAULTS
    with session_store.postgres_connection(other) as db:
        assert db.execute('SELECT payload FROM v7_private.business_documents WHERE tenant=%s AND filename=%s',
                          (tenant, policy.FILENAME)).fetchone() is None
