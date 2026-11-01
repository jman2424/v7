"""Exercise the existing tenant-isolated promotion ledger with native PG."""
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

from service import billing_promotions as promotions, subscriptions, session_store


def test_native_promotion_json_locking_coupon_bindings_and_tenant_isolation(pg_runtime):
    tenant, other = pg_runtime['tenant'], pg_runtime['other']
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: subscriptions.redeem_discount(tenant, 'MHIGHSTREET'), [0, 1]))
    assert all(row['first_month_discount_percent'] == 50 for row in results)
    assert subscriptions.saved_campaign(other) == ''
    with session_store.postgres_connection(other) as db:
        assert db.execute('SELECT campaign FROM billing_discounts WHERE tenant=%s', (tenant,)).fetchall() == []
    provider = Mock()
    provider.stripe_request.side_effect = lambda method, path, data, **kwargs: {**data, 'valid': True}
    setup = subscriptions._contract(tenant, 'implementation')
    coupon = promotions.coupon(provider, tenant, promotions.HIGHSTREET, 'implementation', setup['ref'])
    with subscriptions.connection(tenant) as db:
        assert promotions.verifies_free_setup(db, tenant,
            {'billing_ref': setup['ref'], 'discount_campaign': promotions.HIGHSTREET}, {coupon})
    with subscriptions.connection(other) as db:
        assert not promotions.verifies_free_setup(db, other,
            {'billing_ref': setup['ref'], 'discount_campaign': promotions.HIGHSTREET}, {coupon})
    platform = subscriptions._contract(tenant, 'platform')
    promotions.coupon(provider, tenant, promotions.HIGHSTREET, 'platform', platform['ref'])
    promotions.mark_subscription_started(tenant, platform['ref'])
    subscriptions.redeem_discount(tenant, 'MHIGHSTREET')
    assert promotions.preview(tenant)['first_month_discount_percent'] == 0
    assert promotions.preview(tenant)['setup_discount_percent'] == 100
