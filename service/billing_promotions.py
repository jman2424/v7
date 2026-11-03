"""Server-owned, once-only setup/first-month offers using the existing ledger.

The tenant's billing_discounts TEXT record also holds immutable coupon bindings.
No browser value can choose a percentage, duration, coupon or billing reference.
Legacy plain-text campaign records remain supported by subscriptions.
"""
import hashlib
import json

from service import session_store

HIGHSTREET = 'highstreet-first-month-free-setup-v1'
SETUP = 'free-setup-v1'
CAMPAIGNS = {HIGHSTREET, SETUP}
CODE_DIGESTS = {
    hashlib.sha256(b'MHIGHSTREET').hexdigest(): HIGHSTREET,
    hashlib.sha256(b'SETUP').hexdigest(): SETUP,
}


def state(tenant, db=None):
    from service import subscriptions
    if db is None:
        with subscriptions.connection(tenant) as connection:
            return state(tenant, connection)
    row = db.execute('SELECT campaign FROM billing_discounts WHERE tenant=?', (tenant,)).fetchone()
    if not row:
        return {}
    raw = row['campaign']
    try:
        result = json.loads(raw)
    except (ValueError, TypeError):
        return {'campaign': raw}
    return result if isinstance(result, dict) else {}


def _lock(db, tenant):
    if session_store._using_postgres():
        db.execute('SELECT pg_advisory_xact_lock(hashtextextended(?,0))', ('billing-promotion:'+tenant,))
    else:
        db.execute('BEGIN IMMEDIATE')


def _save(db, tenant, value):
    db.execute('INSERT INTO billing_discounts VALUES (?,?) ON CONFLICT(tenant) DO UPDATE SET campaign=excluded.campaign',
               (tenant, json.dumps(value, separators=(',', ':'), allow_nan=False)))


def redeem(tenant, campaign):
    from service import subscriptions
    subscriptions._contract(tenant, 'platform')
    with subscriptions.connection(tenant) as db:
        _lock(db, tenant)
        current = state(tenant, db)
        previous = current.get('campaign')
        if previous == campaign or previous == HIGHSTREET and campaign == SETUP:
            return  # Idempotent; never replace a stronger accepted offer.
        from service.platform_promotions import enabled
        if not enabled(campaign):
            raise ValueError('promotion_unavailable')
        if previous and previous not in CAMPAIGNS:
            raise ValueError('discount_does_not_stack')
        platform = db.execute("SELECT subscription,implementation_paid FROM billing_contracts WHERE tenant=? AND kind='platform'", (tenant,)).fetchone()
        paid_month = db.execute("SELECT 1 FROM billing_invoices WHERE tenant=? AND kind='platform' AND status='paid' LIMIT 1", (tenant,)).fetchone()
        if campaign == HIGHSTREET and (platform['subscription'] or paid_month or current.get('first_month_started')):
            raise ValueError('first_month_discount_new_subscription_only')
        setup_paid = platform['implementation_paid'] or db.execute("SELECT 1 FROM billing_contracts WHERE tenant=? AND kind='implementation' AND status='paid'", (tenant,)).fetchone()
        if campaign == SETUP and setup_paid:
            raise ValueError('implementation_already_paid')
        _save(db, tenant, {**current, 'campaign': campaign})


def preview(tenant):
    from service import subscriptions
    value = state(tenant)
    campaign = value.get('campaign')
    if campaign not in CAMPAIGNS:
        return {'setup_discount_percent': 0, 'first_month_discount_percent': 0, 'promotion_applied': False}
    with subscriptions.connection(tenant) as db:
        started = db.execute("SELECT 1 FROM billing_contracts WHERE tenant=? AND kind='platform' AND subscription IS NOT NULL", (tenant,)).fetchone()
        paid = db.execute("SELECT 1 FROM billing_invoices WHERE tenant=? AND kind='platform' AND status='paid' LIMIT 1", (tenant,)).fetchone()
    first = campaign == HIGHSTREET and not (value.get('first_month_started') or started or paid)
    return {'setup_discount_percent': 100, 'first_month_discount_percent': 50 if first else 0, 'promotion_applied': True}


def terms(tenant, campaign, kind):
    if campaign not in CAMPAIGNS:
        return None
    if kind == 'implementation':
        return {'percent': 100, 'duration': 'once'}
    if kind == 'platform' and campaign == HIGHSTREET and preview(tenant)['first_month_discount_percent']:
        return {'percent': 50, 'duration': 'once'}
    return None


def coupon(stripe, tenant, campaign, kind, reference):
    from service import subscriptions
    offer = terms(tenant, campaign, kind)
    if offer is None:
        raise ValueError('discount_not_applicable')
    identifier = 'v7offer_' + hashlib.sha256(f'{tenant}:{campaign}:{kind}:{reference}'.encode()).hexdigest()[:48]
    with subscriptions.connection(tenant) as db:
        _lock(db, tenant)
        current = state(tenant, db)
        contract = db.execute('SELECT ref FROM billing_contracts WHERE tenant=? AND kind=?', (tenant, kind)).fetchone()
        if current.get('campaign') != campaign or not contract or contract['ref'] != reference:
            raise ValueError('checkout_promotion_changed_refresh')
        if kind == 'platform' and current.get('first_month_started'):
            raise ValueError('first_month_discount_new_subscription_only')
        bindings = {**current.get('bindings', {})}
        bindings[kind] = {'reference': reference, 'coupon': identifier, 'campaign': campaign}
        _save(db, tenant, {**current, 'bindings': bindings})
    result = stripe.stripe_request('POST', '/v1/coupons',
        {'id': identifier, 'percent_off': offer['percent'], 'duration': 'once',
         'name': 'V7 free setup' if kind == 'implementation' else 'V7 first month 50% off'},
        idempotency_key=identifier)
    if (result.get('id') != identifier or result.get('percent_off') != offer['percent']
            or result.get('duration') != 'once' or result.get('valid') is not True):
        raise ValueError('stripe_discount_invalid')
    return identifier


def mark_subscription_started(tenant, reference):
    from service import subscriptions
    with subscriptions.connection(tenant) as db:
        _lock(db, tenant)
        value = state(tenant, db)
        binding = value.get('bindings', {}).get('platform', {})
        if binding.get('reference') == reference and not value.get('first_month_started'):
            _save(db, tenant, {**value, 'first_month_started': True})


def verifies_free_setup(db, tenant, metadata, coupons):
    binding = state(tenant, db).get('bindings', {}).get('implementation', {})
    return (binding.get('campaign') in CAMPAIGNS
            and binding.get('reference') == metadata.get('billing_ref')
            and binding.get('campaign') == metadata.get('discount_campaign')
            and bool(binding.get('coupon')) and coupons == {binding['coupon']})
