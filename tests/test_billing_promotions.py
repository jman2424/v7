"""Offer amounts, first-invoice scope and canonical no-cost setup proofs."""
import json

import pytest

from service import billing_promotions as promotions, subscriptions
from service.plan_catalog import get_plan
from tests import test_subscriptions
from tests.test_subscriptions import identity, signature

stripe = test_subscriptions.stripe


def provider(method, path, data=None, **kwargs):
    if path.startswith('/v1/tax_rates/'):
        return {'active': True, 'inclusive': False, 'percentage': 20}
    if path == '/v1/coupons':
        return {**data, 'valid': True}
    if path == '/v1/checkout/sessions':
        return {'id': 'cs_offer', 'url': 'https://checkout.stripe.com/c/pay/offer'}
    raise AssertionError((method, path))


@pytest.mark.parametrize('code', ['MHIGHSTREET', 'SETUP'])
@pytest.mark.parametrize('kind', ['platform', 'implementation'])
@pytest.mark.parametrize('plan_id', ['starter', 'business', 'scale'])
def test_offers_keep_base_prices_and_discount_only_the_intended_item(client, stripe, code, kind, plan_id):
    identity(client, 'business_owner')
    stripe.side_effect = provider
    response = client.post('/billing/discount', json={'code': ' '+code.lower()+' '})
    assert response.status_code == 200, response.json
    assert response.json['setup_discount_percent'] == 100
    assert response.json['first_month_discount_percent'] == (50 if code == 'MHIGHSTREET' else 0)
    stripe.assert_not_called()
    response = client.post('/billing/checkout', json={'kind': kind, 'plan_id': plan_id})
    assert response.status_code == 200, response.json
    body = stripe.call_args.args[2]
    assert body['line_items[0][price_data][unit_amount]'] == get_plan(plan_id)['monthly_pence' if kind == 'platform' else 'setup_pence']
    coupons = [call.args[2] for call in stripe.call_args_list if call.args[1] == '/v1/coupons']
    if kind == 'implementation' or code == 'MHIGHSTREET':
        assert len(coupons) == 1
        assert coupons[0]['percent_off'] == (100 if kind == 'implementation' else 50)
        assert coupons[0]['duration'] == 'once'
        assert body['discounts[0][coupon]'] == coupons[0]['id']
    else:
        assert not coupons and 'discounts[0][coupon]' not in body
    assert code not in json.dumps(body)
    assert subscriptions._contract('EXAMPLE', 'platform')['implementation_paid'] == 0
    assert subscriptions.saved_campaign('OTHER') == ''
    report = client.get('/billing/subscription').json
    assert report['discount_percent'] == 0  # Never portray first-month as recurring.
    assert report['setup_discount_percent'] == 100


def setup_checkout(client, stripe):
    identity(client, 'business_owner')
    stripe.side_effect = provider
    assert client.post('/billing/discount', json={'code': 'SETUP'}).status_code == 200
    assert client.post('/billing/checkout', json={'kind': 'implementation', 'plan_id': 'starter'}).status_code == 200
    body = stripe.call_args.args[2]
    return {'id': 'cs_offer', 'mode': 'payment', 'status': 'complete', 'payment_status': 'no_payment_required',
            'currency': 'gbp', 'amount_total': 0, 'amount_subtotal': 14900, 'customer': 'cus_offer',
            'discounts': [{'coupon': body['discounts[0][coupon]']}],
            'metadata': {key[9:-1]: value for key, value in body.items() if key.startswith('metadata[')}}


def test_zero_setup_requires_signed_event_and_canonical_coupon_binding_and_is_replay_safe(client, stripe):
    checkout = setup_checkout(client, stripe)
    stripe.side_effect = None
    stripe.return_value = checkout
    body = json.dumps({'type': 'checkout.session.completed', 'data': {'object': {'id': 'cs_offer'}}}).encode()
    assert client.post('/billing/stripe/webhook', data=body, content_type='application/json').status_code == 403
    for _ in range(2):
        assert client.post('/billing/stripe/webhook', data=body, content_type='application/json', headers={'Stripe-Signature': signature(body)}).status_code == 200
    assert subscriptions._contract('EXAMPLE', 'platform')['implementation_paid'] == 1
    assert subscriptions.plan_state('EXAMPLE')['setup_plan'] == 'starter'
    assert subscriptions._contract('OTHER', 'platform')['implementation_paid'] == 0
    with subscriptions.connection('EXAMPLE') as db:
        assert db.execute("SELECT 1 FROM billing_invoices WHERE tenant='EXAMPLE'").fetchone() is None


@pytest.mark.parametrize('field,value', [
    ('status', 'open'), ('payment_status', 'unpaid'), ('currency', 'usd'),
    ('amount_subtotal', 1), ('discounts', []), ('discounts', [{'coupon': 'forged'}]),
    ('metadata', {'tenant': 'OTHER', 'kind': 'implementation'}),
])
def test_forged_or_unfinished_setup_cannot_waive_fees(client, stripe, field, value):
    checkout = setup_checkout(client, stripe)
    stripe.side_effect = None
    stripe.return_value = {**checkout, field: value}
    with pytest.raises(ValueError):
        subscriptions.sync_zero_setup_checkout('cs_offer')
    assert subscriptions._contract('EXAMPLE', 'platform')['implementation_paid'] == 0


def test_first_month_cannot_be_renewed_by_reentering_code_or_restarting_subscription(client, stripe):
    identity(client, 'business_owner')
    stripe.side_effect = provider
    assert client.post('/billing/discount', json={'code': 'MHIGHSTREET'}).status_code == 200
    assert client.post('/billing/checkout', json={'kind': 'platform', 'plan_id': 'starter'}).status_code == 200
    request = stripe.call_args.args[2]
    ref = request['metadata[billing_ref]']
    stripe.side_effect = None
    stripe.return_value = {'id': 'sub_offer', 'status': 'active', 'customer': 'cus_offer',
        'metadata': {'tenant': 'EXAMPLE', 'kind': 'platform', 'billing_ref': ref, 'plan_id': 'starter'}}
    subscriptions.sync_subscription('sub_offer')
    assert promotions.preview('EXAMPLE')['first_month_discount_percent'] == 0
    stripe.reset_mock()
    assert client.post('/billing/discount', json={'code': 'MHIGHSTREET'}).status_code == 200
    stripe.assert_not_called()  # Never attach another coupon to an existing subscription.
    # Even if a completed/cancelled contract is later replaced, the consumed flag survives.
    with subscriptions.connection('EXAMPLE') as db:
        db.execute("UPDATE billing_contracts SET subscription=NULL,checkout=NULL,status='not_started' WHERE tenant='EXAMPLE' AND kind='platform'")
    assert promotions.terms('EXAMPLE', promotions.HIGHSTREET, 'platform') is None
    assert subscriptions.saved_campaign('EXAMPLE') == promotions.HIGHSTREET


@pytest.mark.parametrize('code', ['MHIGHSTREET', 'SETUP'])
def test_codes_cannot_cross_tenants_or_roles_or_accept_forged_percentages(client, stripe, code):
    assert client.post('/billing/discount', json={'code': code}).status_code in {401, 403}
    identity(client, 'business_staff')
    assert client.post('/billing/discount', json={'code': code}).status_code == 403
    identity(client, 'business_owner')
    assert client.post('/billing/discount?tenant=OTHER', json={'code': code}).status_code == 403
    assert client.post('/billing/discount', json={'code': code, 'percent': 999, 'duration': 'forever'}).status_code == 200
    assert promotions.preview('EXAMPLE')['first_month_discount_percent'] in {0, 50}
    stripe.assert_not_called()


def test_first_month_code_rejects_existing_paid_subscriptions_and_setup_does_not_refund(client, stripe):
    identity(client, 'business_owner')
    subscriptions._contract('EXAMPLE', 'platform')
    with subscriptions.connection('EXAMPLE') as db:
        db.execute("UPDATE billing_contracts SET subscription='sub_existing',implementation_paid=1 WHERE tenant='EXAMPLE' AND kind='platform'")
    for code, error in [('MHIGHSTREET', 'first_month_discount_new_subscription_only'), ('SETUP', 'implementation_already_paid')]:
        response = client.post('/billing/discount', json={'code': code})
        assert response.status_code == 400 and response.json['error'] == error
    assert subscriptions.saved_campaign('EXAMPLE') == ''
    stripe.assert_not_called()


def test_stronger_offer_upgrade_retains_existing_setup_proof(client, stripe):
    checkout = setup_checkout(client, stripe)
    assert client.post('/billing/discount', json={'code': 'MHIGHSTREET'}).status_code == 200
    stripe.side_effect = None
    stripe.return_value = checkout
    subscriptions.sync_zero_setup_checkout('cs_offer')
    assert subscriptions._contract('EXAMPLE', 'platform')['implementation_paid'] == 1
    assert promotions.preview('EXAMPLE')['first_month_discount_percent'] == 50


def test_promotion_never_bypasses_business_approval(client, stripe, monkeypatch):
    from service import business_applications
    identity(client, 'business_owner')
    assert client.post('/billing/discount', json={'code': 'MHIGHSTREET'}).status_code == 200
    def deny(tenant):
        raise business_applications.ApplicationError('business_approval_required', 403)
    monkeypatch.setattr(business_applications, 'require_eligible', deny)
    assert client.post('/billing/checkout', json={'kind': 'implementation'}).status_code == 403
    stripe.assert_not_called()


@pytest.mark.parametrize('bad', [None, 100, '', 'x'*101, 'MHIGHSTREET!', 'SETUP\x00'])
def test_invalid_offer_codes_fail_without_provider_calls(client, stripe, bad):
    identity(client, 'business_owner')
    assert client.post('/billing/discount', json={'code': bad}).status_code == 400
    stripe.assert_not_called()


@pytest.mark.parametrize('wrong', [{'duration': 'forever'}, {'percent_off': 99}, {'id': 'unexpected'}, {'valid': False}])
def test_provider_coupon_must_match_exact_server_owned_terms(client, stripe, wrong):
    identity(client, 'business_owner')
    assert client.post('/billing/discount', json={'code': 'MHIGHSTREET'}).status_code == 200
    def invalid(method, path, data=None, **kwargs):
        result = provider(method, path, data, **kwargs)
        return {**result, **wrong} if path == '/v1/coupons' else result
    stripe.side_effect = invalid
    response = client.post('/billing/checkout', json={'kind': 'platform', 'plan_id': 'starter'})
    assert response.status_code == 400 and response.json['error'] == 'stripe_discount_invalid'
    assert not any(call.args[1] == '/v1/checkout/sessions' for call in stripe.call_args_list)
