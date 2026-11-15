"""Yearly billing uses server-owned yearly prices and never takes month-sized offers."""
import pytest

from service import billing_promotions, referrals, subscriptions
from service.plan_catalog import get_plan
from tests.test_billing_management import confirm_plan, managed_subscription  # noqa: F401
from tests.test_subscriptions import identity, stripe as stripe_fixture

stripe = stripe_fixture
TAX = {'active': True, 'inclusive': False, 'percentage': 20}


def _session(name):
    return {'id': 'cs_' + name, 'url': 'https://checkout.stripe.com/c/pay/' + name}


@pytest.mark.parametrize('plan_id,pence', [('starter', 99000), ('business', 199000), ('scale', 349000)])
def test_yearly_checkout_charges_the_server_owned_yearly_price(client, stripe, plan_id, pence):
    identity(client, 'business_owner')
    stripe.side_effect = [TAX, _session('year')]
    response = client.post('/billing/checkout', json={'kind': 'platform', 'plan_id': plan_id, 'interval': 'year',
                                                     'amount_pence': 1})
    assert response.status_code == 200, response.json
    data = stripe.call_args.args[2]
    assert data['line_items[0][price_data][unit_amount]'] == pence == get_plan(plan_id)['annual_pence']
    assert data['line_items[0][price_data][recurring][interval]'] == 'year'
    assert 'yearly' in data['line_items[0][price_data][product_data][name]']
    assert data['metadata[billing_interval]'] == data['subscription_data[metadata][billing_interval]'] == 'year'
    with subscriptions.connection('EXAMPLE') as db:
        assert subscriptions.bound_interval(db, 'EXAMPLE', data['metadata[billing_ref]']) == 'year'


def test_monthly_remains_the_default(client, stripe):
    identity(client, 'business_owner')
    stripe.side_effect = [TAX, _session('month')]
    assert client.post('/billing/checkout', json={'kind': 'platform', 'plan_id': 'starter'}).status_code == 200
    data = stripe.call_args.args[2]
    assert data['line_items[0][price_data][unit_amount]'] == 9900
    assert data['line_items[0][price_data][recurring][interval]'] == 'month'
    assert client.get('/billing/subscription').json['billing_interval'] == 'month'


@pytest.mark.parametrize('payload', [
    {'kind': 'platform', 'plan_id': 'starter', 'interval': 'week'},
    {'kind': 'platform', 'plan_id': 'starter', 'interval': 'YEAR'},
    {'kind': 'platform', 'plan_id': 'starter', 'interval': {}},
    {'kind': 'platform', 'plan_id': 'starter', 'interval': True},
    {'kind': 'implementation', 'plan_id': 'starter', 'interval': 'year'},
])
def test_invalid_interval_never_reaches_stripe(client, stripe, payload):
    identity(client, 'business_owner')
    assert client.post('/billing/checkout', json=payload).json == {'error': 'invalid_billing_interval'}
    stripe.assert_not_called()


def test_switching_an_open_checkout_to_yearly_replaces_it(client, stripe):
    identity(client, 'business_owner')
    stripe.side_effect = [TAX, _session('first')]
    assert client.post('/billing/checkout', json={'kind': 'platform', 'plan_id': 'starter'}).status_code == 200
    first = stripe.call_args.args[2]
    open_session = {'status': 'open', 'url': 'https://checkout.stripe.com/c/pay/first',
                    'metadata': {'billing_version': 'tiered_v1', 'plan_id': 'starter', 'billing_interval': 'month'}}
    stripe.side_effect = [TAX, open_session, {'status': 'expired'}, _session('second')]
    response = client.post('/billing/checkout', json={'kind': 'platform', 'plan_id': 'starter', 'interval': 'year'})
    assert response.status_code == 200, response.json
    second = stripe.call_args.args[2]
    assert stripe.call_args_list[-2].args[1].endswith('/expire')
    assert second['metadata[billing_ref]'] != first['metadata[billing_ref]']
    assert second['line_items[0][price_data][unit_amount]'] == 99000


def test_first_month_offer_cannot_discount_a_whole_year(client, stripe, monkeypatch):
    identity(client, 'business_owner')
    monkeypatch.setattr('service.platform_promotions.enabled', lambda campaign: True)
    billing_promotions.redeem('EXAMPLE', billing_promotions.HIGHSTREET)
    response = client.post('/billing/checkout', json={'kind': 'platform', 'plan_id': 'starter', 'interval': 'year'})
    assert response.json == {'error': 'first_month_offer_monthly_only'}
    stripe.assert_not_called()


def test_referral_reward_is_not_spent_on_a_yearly_checkout(client, stripe, monkeypatch):
    identity(client, 'business_owner')
    reserved = []
    monkeypatch.setattr(referrals, 'reserve', lambda *args: reserved.append(args))
    stripe.side_effect = [TAX, _session('year')]
    assert client.post('/billing/checkout', json={'kind': 'platform', 'plan_id': 'starter', 'interval': 'year'}).status_code == 200
    assert reserved == []
    assert 'discounts[0][coupon]' not in stripe.call_args.args[2]


def _yearly(subject, stripe):
    """Turn the managed monthly subscription into a yearly one."""
    with subscriptions.connection('EXAMPLE') as db:
        db.execute('INSERT INTO billing_interval_choices VALUES (?,?,?)', (subject['ref'], 'EXAMPLE', 'year'))
    original_price, original_provider = subject['price'], stripe.side_effect

    def price(plan_id):
        return {**original_price(plan_id), 'id': 'price_' + plan_id + 'Year', 'unit_amount': get_plan(plan_id)['annual_pence'],
                'recurring': {'interval': 'year', 'interval_count': 1, 'usage_type': 'licensed'}}

    def provider(method, path, body=None, **kwargs):
        if method == 'POST' and path == '/v1/prices':
            return price(body['metadata[v7_plan_id]'])
        return original_provider(method, path, body, **kwargs)

    subject['price'] = price
    subject['data']['items']['data'][0]['price'] = price('starter')
    stripe.side_effect = provider


def test_yearly_plan_change_keeps_yearly_billing(client, stripe, managed_subscription):  # noqa: F811 (shared fixture)
    _yearly(managed_subscription, stripe)
    assert subscriptions.billing_interval('EXAMPLE') == 'year'
    response = client.post('/billing/change-plan', json={'plan_id': 'business'})
    assert response.status_code == 200, response.json
    price = next(call.args[2] for call in stripe.call_args_list if call.args[1] == '/v1/prices')
    assert price['unit_amount'] == 199000 and price['recurring[interval]'] == 'year'
    confirm_plan(managed_subscription, 'business')
    managed_subscription['data']['latest_invoice']['lines']['data'][0]['pricing']['price_details']['price'] = 'price_businessYear'
    subscriptions.sync_subscription('sub_managed')
    assert subscriptions.plan_state('EXAMPLE')['active_plan'] == 'business'
    assert subscriptions.billing_interval('EXAMPLE') == 'year'
    assert client.get('/billing/subscription').json['billing_interval'] == 'year'


def test_monthly_price_on_a_yearly_subscription_is_refused(client, stripe, managed_subscription):  # noqa: F811 (shared fixture)
    _yearly(managed_subscription, stripe)
    managed_subscription['data']['items']['data'][0]['price'] = {
        **managed_subscription['price']('starter'), 'unit_amount': 9900,
        'recurring': {'interval': 'month', 'interval_count': 1, 'usage_type': 'licensed'}}
    assert client.post('/billing/change-plan', json={'plan_id': 'business'}).json == {'error': 'payment_processing_refresh_soon'}


def test_referral_month_credit_is_kept_for_monthly_billing(client, stripe, managed_subscription):  # noqa: F811 (shared fixture)
    _yearly(managed_subscription, stripe)
    with pytest.raises(ValueError, match='referral_reward_monthly_billing_only'):
        referrals.apply_next_month('EXAMPLE')


def test_yearly_price_is_ten_months_of_the_monthly_price():
    # "2 months free" in the console is only true while this holds.
    for plan_id in ('starter', 'business', 'scale'):
        plan = get_plan(plan_id)
        assert plan['annual_pence'] == plan['monthly_pence'] * 10
