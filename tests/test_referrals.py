"""Referral snapshots, tenant boundaries and once-only payment rewards."""
from concurrent.futures import ThreadPoolExecutor
import json
import time
from unittest.mock import Mock

import pytest

from service import referrals, subscriptions
from tests.test_subscriptions import identity, stripe, signature


def welcome(monkeypatch):
    monkeypatch.setattr(subscriptions, 'internal_business', lambda tenant: False)
    monkeypatch.setattr(subscriptions, 'complimentary_plan', lambda tenant: None)
    code = referrals.report('SPONSOR', 'owner@example.test', 'https://example.test')['code']
    referrals.claim('EXAMPLE', 'new@example.test', code)
    return code


def test_disable_preserves_accepted_offer_and_earned_rewards(client, monkeypatch):
    code = welcome(monkeypatch)
    referrals.set_program('SPONSOR', False, '')
    with pytest.raises(ValueError, match='disabled'):
        referrals.claim('OTHER', 'other@example.test', code)
    report = referrals.report('EXAMPLE', 'new@example.test', 'https://example.test')
    assert report['claim']['percent'] == 40
    assert len(report['rewards']) == 2
    referrals.qualified_payment('EXAMPLE', 'platform', {'id':'in_first','status':'paid','amount_paid':5940,'billing_reason':'subscription_create'})
    assert len(referrals.report('SPONSOR', 'owner@example.test', 'https://example.test')['rewards']) == 2


def test_same_owner_self_and_repeated_claims_are_rejected(client, monkeypatch):
    code = welcome(monkeypatch)
    referrals.set_program('SPONSOR', True, '')
    for tenant, owner, error in [('SPONSOR','different@example.test','invalid_or_self'),('OTHER','owner@example.test','invalid_or_self'),('OTHER','new@example.test','already_accepted'),('EXAMPLE','other@example.test','already_accepted')]:
        with pytest.raises(ValueError, match=error):
            referrals.claim(tenant, owner, code)


@pytest.mark.parametrize('kind,status,reason,amount', [('implementation','paid','subscription_create',100),('platform','open','subscription_create',100),('platform','paid','subscription_cycle',100),('platform','paid','subscription_create',0)])
def test_only_positive_first_subscription_payment_earns_reward(client, monkeypatch, kind,status,reason,amount):
    welcome(monkeypatch)
    referrals.qualified_payment('EXAMPLE',kind,{'id':'in_other','status':status,'billing_reason':reason,'amount_paid':amount})
    assert referrals.report('SPONSOR','owner@example.test','https://example.test')['rewards'] == []


def test_duplicate_payment_awards_exactly_once(client, monkeypatch):
    welcome(monkeypatch)
    invoice={'id':'in_first','status':'paid','amount_paid':5940,'billing_reason':'subscription_create'}
    for _ in range(3):
        referrals.qualified_payment('EXAMPLE','platform',invoice)
    assert len(referrals.report('SPONSOR','owner@example.test','https://example.test')['rewards']) == 2


def test_concurrent_reservations_only_one_generation_and_cancel_releases(client, monkeypatch):
    welcome(monkeypatch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda ref: referrals.reserve('EXAMPLE','platform',ref),['first','second']))
    winner=[row for row in results if row]
    assert len(winner) == 1
    assert referrals.reserve('OTHER','platform',winner[0]['billing_ref']) is None
    referrals.release('EXAMPLE',winner[0]['billing_ref'])
    assert referrals.reserve('EXAMPLE','platform','third') is not None
    assert referrals.reserve('EXAMPLE','api','api-ref') is None


def test_verified_coupon_once_and_consumption_scoped_to_generation(client, monkeypatch):
    welcome(monkeypatch)
    reward=referrals.reserve('EXAMPLE','platform','first')
    provider=Mock()
    provider.stripe_request.return_value={'id':'coupon_test','percent_off':40,'duration':'once','valid':True}
    referrals.coupon(provider,'EXAMPLE',reward)
    assert provider.stripe_request.call_args.args[2]['duration'] == 'once'
    invoice={'id':'in_first','status':'paid','amount_paid':5940,'discounts':[{'source':{'coupon':{'id':'coupon_test'}}}]}
    referrals.consumed_payment('EXAMPLE','platform','stale',invoice)
    assert referrals.reserve('EXAMPLE','platform','first')['status']=='reserved'
    referrals.consumed_payment('EXAMPLE','platform','first',invoice)
    assert referrals.reserve('EXAMPLE','platform','first') is None


def test_routes_enforce_owner_tenant_and_admin_toggle(client):
    assert client.get('/billing/referrals').status_code == 401
    identity(client,'business_owner')
    assert client.get('/billing/referrals').status_code == 200
    assert client.get('/billing/referrals?tenant=OTHER').status_code == 403
    assert client.post('/billing/referrals/program',json={'enabled':False}).status_code == 403
    identity(client,'business_staff')
    assert client.get('/billing/referrals').status_code == 403
    identity(client)
    assert client.post('/billing/referrals/program',json={'enabled':False}).status_code == 200
    assert client.post('/billing/referrals/program',json={'enabled':'false'}).status_code == 400


def test_checkout_discount_is_once_and_undiscounted_price_unchanged(client,stripe,monkeypatch):
    monkeypatch.setenv('V7_VAT_REGISTERED','false')
    welcome(monkeypatch)
    stripe.side_effect=[{'id':'coupon_test','percent_off':40,'duration':'once','valid':True},{'id':'cs_test','url':'https://checkout.stripe.com/c/pay/test'}]
    identity(client,'business_owner')
    response=client.post('/billing/checkout',json={'kind':'platform','plan_id':'starter'})
    assert response.status_code==200, response.json
    payload=stripe.call_args.args[2]
    assert payload['discounts[0][coupon]']=='coupon_test'
    assert payload['line_items[0][price_data][unit_amount]']==9900
    assert stripe.call_args_list[0].args[2]['duration']=='once'


def test_webhook_signature_and_canonical_payment_are_required(client,stripe,monkeypatch):
    welcome(monkeypatch)
    contract=subscriptions._contract('EXAMPLE','platform')
    subscription={'metadata':{'tenant':'EXAMPLE','kind':'platform','billing_ref':contract['ref']},'status':'active','items':{'data':[]}}
    invoice={'id':'in_first','currency':'gbp','created':int(time.time()),'subscription':'sub_test','total':5940,'amount_paid':5940,'amount_remaining':0,'status':'paid','billing_reason':'subscription_create','lines':{'data':[]}}
    stripe.side_effect=lambda method,path,*a,**k: invoice if path.startswith('/v1/invoices/') else subscription
    body=json.dumps({'type':'invoice.paid','data':{'object':{'id':'in_first','tenant':'OTHER','amount_paid':999999}}}).encode()
    assert client.post('/billing/stripe/webhook',data=body,content_type='application/json').status_code==403
    assert referrals.report('SPONSOR','owner@example.test','https://example.test')['rewards']==[]
    for _ in range(2):
        assert client.post('/billing/stripe/webhook',data=body,content_type='application/json',headers={'Stripe-Signature':signature(body)}).status_code==200
    assert len(referrals.report('SPONSOR','owner@example.test','https://example.test')['rewards'])==2
    assert referrals.report('OTHER','other@example.test','https://example.test')['rewards']==[]


def test_reversal_review_survives_later_paid_callbacks(client,monkeypatch):
    welcome(monkeypatch)
    invoice={'id':'in_first','status':'paid','amount_paid':5940,'billing_reason':'subscription_create'}
    referrals.qualified_payment('EXAMPLE','platform',invoice)
    referrals.review_payment('EXAMPLE','in_first')
    referrals.qualified_payment('EXAMPLE','platform',invoice)
    rewards=referrals.report('SPONSOR','owner@example.test','https://example.test')['rewards']
    assert len(rewards)==2 and all(row['status']=='review' for row in rewards)


def test_cancelled_checkout_releases_reward(client,stripe,monkeypatch):
    welcome(monkeypatch)
    contract=subscriptions._contract('EXAMPLE','platform')
    referrals.reserve('EXAMPLE','platform',contract['ref'])
    with subscriptions.connection('EXAMPLE') as db:
        db.execute("UPDATE billing_contracts SET checkout='cs_test' WHERE ref=?",(contract['ref'],))
    stripe.side_effect=[{'status':'open'},{'status':'expired'}]
    subscriptions.cancel_pending_checkouts('EXAMPLE')
    assert referrals.reserve('EXAMPLE','platform','new_generation') is not None


def test_home_offer_follows_toggle_without_losing_rewards(client,monkeypatch):
    welcome(monkeypatch)
    page=client.get('/').get_data(as_text=True)
    assert 'referral-offer-title' in page and 'Get your referral link' in page
    assert 'href="/console/account"' in page
    referrals.set_program('EXAMPLE',False,'')
    assert 'referral-offer-title' not in client.get('/').get_data(as_text=True)
    assert len(referrals.report('EXAMPLE','new@example.test','https://example.test')['rewards'])==2


def test_existing_stronger_discount_is_preserved(client,stripe,monkeypatch):
    welcome(monkeypatch)
    monkeypatch.setattr(subscriptions,'saved_campaign',lambda tenant:'existing-campaign')
    with pytest.raises(ValueError,match='does_not_stack'):
        referrals.apply_next_month('EXAMPLE')
    stripe.assert_not_called()
    assert all(row['status']=='available' for row in referrals.report('EXAMPLE','new@example.test','https://example.test')['rewards'])


@pytest.mark.parametrize('other_discount',[False,True])
def test_renewal_reward_once_and_does_not_replace_other_stripe_discount(client,stripe,monkeypatch,other_discount):
    welcome(monkeypatch)
    contract=subscriptions._contract('EXAMPLE','platform')
    with subscriptions.connection('EXAMPLE') as db:
        db.execute("UPDATE billing_contracts SET subscription='sub_test',status='active' WHERE ref=?",(contract['ref'],))
    subscription={'id':'sub_test','status':'active','metadata':{'tenant':'EXAMPLE','kind':'platform','billing_ref':contract['ref']},'items':{'data':[]},'discounts':[{'coupon':'other_coupon'}] if other_discount else []}
    def provider(method,path,*args,**kwargs):
        if path=='/v1/coupons':
            return {'id':'coupon_test','percent_off':40,'duration':'once','valid':True}
        if method=='GET':
            return subscription
        return {**subscription,'discounts':[{'source':{'coupon':'coupon_test'}}]}
    stripe.side_effect=provider
    if other_discount:
        with pytest.raises(ValueError,match='does_not_stack'):
            referrals.apply_next_month('EXAMPLE')
        assert not any(call.args[:2]==('POST','/v1/subscriptions/sub_test') for call in stripe.call_args_list)
    else:
        assert referrals.apply_next_month('EXAMPLE')['percent']==40
        payload=stripe.call_args.args[2]
        assert payload['proration_behavior']=='none' and payload['discounts[0][coupon]']=='coupon_test'
        assert referrals.report('EXAMPLE','new@example.test','https://example.test')['rewards'][0]['status'] in {'applied','available'}


def test_referral_mutations_require_csrf(client):
    identity(client)
    response=client.post('/billing/referrals/program',json={'enabled':False},headers={'X-CSRF-Token':'invalid'})
    assert response.status_code==403
