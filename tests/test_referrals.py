"""Referral snapshots, tenant boundaries and once-only payment rewards."""
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
import time
from unittest.mock import Mock

import pytest

from service import referrals, subscriptions
from service.plan_catalog import get_plan
from tests import test_subscriptions
from tests.test_subscriptions import identity, signature

stripe = test_subscriptions.stripe


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


def test_new_joiner_gets_free_setup_but_referrer_keeps_40_percent(client,monkeypatch):
    welcome(monkeypatch)
    report=referrals.report('EXAMPLE','new@example.test','https://example.test')
    assert report['claim']['joining_setup_percent']==100
    assert {row['kind']:row['percent'] for row in report['rewards']}=={'platform':40,'implementation':100}
    referrals.qualified_payment('EXAMPLE','platform',{'id':'in_first','status':'paid','amount_paid':5940,'billing_reason':'subscription_create'})
    earned=referrals.report('SPONSOR','owner@example.test','https://example.test')['rewards']
    assert {row['kind']:row['percent'] for row in earned}=={'platform':40,'implementation':40}
    offer=referrals.public_offer('EXAMPLE')
    assert offer['joining_setup_percent']==100 and offer['sponsor_setup_percent']==40
    assert offer['stacks'] is False and offer['excludes_ai_credit'] is True


def test_previous_offer_snapshot_is_not_rewritten_when_program_changes(client,monkeypatch):
    monkeypatch.setattr(subscriptions,'internal_business',lambda tenant:False)
    monkeypatch.setattr(subscriptions,'complimentary_plan',lambda tenant:None)
    code=referrals.report('SPONSOR','owner@example.test','https://example.test')['code']
    with subscriptions.connection('SPONSOR') as db:
        db.execute('UPDATE referral_program SET joining_setup_percent=40 WHERE id=1')
    referrals.claim('EXAMPLE','old@example.test',code)
    with subscriptions.connection('SPONSOR') as db:
        db.execute('UPDATE referral_program SET joining_setup_percent=100 WHERE id=1')
    referrals.claim('OTHER','new@example.test',code)
    referrals.set_program('SPONSOR',False,'')
    old=referrals.report('EXAMPLE','old@example.test','https://example.test')
    new=referrals.report('OTHER','new@example.test','https://example.test')
    assert old['claim']['joining_setup_percent']==40
    assert next(row['percent'] for row in old['rewards'] if row['kind']=='implementation')==40
    assert new['claim']['joining_setup_percent']==100


def test_local_schema_upgrade_snapshots_existing_percentage(monkeypatch):
    monkeypatch.setattr(referrals.session_store,'_using_postgres',lambda:False)
    with sqlite3.connect(':memory:') as db:
        db.row_factory=sqlite3.Row
        db.execute('CREATE TABLE referral_program(id INTEGER PRIMARY KEY,enabled INTEGER NOT NULL,percent INTEGER NOT NULL)')
        db.execute('INSERT INTO referral_program VALUES(1,1,40)')
        db.execute('CREATE TABLE referral_claims(tenant TEXT PRIMARY KEY,sponsor TEXT NOT NULL,owner_hash TEXT UNIQUE NOT NULL,percent INTEGER NOT NULL,created INTEGER NOT NULL,qualifying_invoice TEXT UNIQUE,status TEXT NOT NULL DEFAULT \'pending\')')
        db.execute("INSERT INTO referral_claims(tenant,sponsor,owner_hash,percent,created) VALUES('OLD','SPONSOR','old-owner',35,1)")
        referrals._schema(db)
        referrals._schema(db)
        assert db.execute("SELECT joining_setup_percent FROM referral_claims WHERE tenant='OLD'").fetchone()[0]==35
        assert db.execute('SELECT joining_setup_percent FROM referral_program WHERE id=1').fetchone()[0]==100


@pytest.mark.parametrize('plan_id',['starter','business','scale'])
@pytest.mark.parametrize('saved_campaign',[False,True])
def test_zero_setup_coupon_is_once_and_wins_over_weaker_campaign(client,stripe,monkeypatch,plan_id,saved_campaign):
    monkeypatch.setenv('V7_VAT_REGISTERED','false')
    welcome(monkeypatch)
    if saved_campaign:
        monkeypatch.setattr(subscriptions,'saved_campaign',lambda tenant:'existing-campaign')
    stripe.side_effect=[{'id':'coupon_free','percent_off':100,'duration':'once','valid':True},{'id':'cs_free','url':'https://checkout.stripe.com/c/pay/free'}]
    identity(client,'business_owner')
    response=client.post('/billing/checkout',json={'kind':'implementation','plan_id':plan_id})
    assert response.status_code==200,response.json
    assert stripe.call_args_list[0].args[2]['percent_off']==100
    assert stripe.call_args_list[0].args[2]['duration']=='once'
    payload=stripe.call_args.args[2]
    assert payload['discounts[0][coupon]']=='coupon_free'
    assert payload['line_items[0][price_data][unit_amount]']==get_plan(plan_id)['setup_pence']
    assert payload['invoice_creation[enabled]']=='true'
    assert 'metadata[discount_campaign]' not in payload
    assert subscriptions._contract('EXAMPLE','platform')['implementation_paid']==0


def free_setup_checkout(client,stripe,monkeypatch):
    monkeypatch.setenv('V7_VAT_REGISTERED','false')
    welcome(monkeypatch)
    stripe.side_effect=[{'id':'coupon_free','percent_off':100,'duration':'once','valid':True},{'id':'cs_free','url':'https://checkout.stripe.com/c/pay/free'}]
    identity(client,'business_owner')
    assert client.post('/billing/checkout',json={'kind':'implementation','plan_id':'starter'}).status_code==200
    payload=stripe.call_args.args[2]
    stripe.side_effect=None
    return {'id':'cs_free','mode':'payment','status':'complete','payment_status':'no_payment_required','currency':'gbp',
            'amount_total':0,'amount_subtotal':14900,'customer':'cus_new','discounts':[{'coupon':'coupon_free'}],
            'metadata':{'tenant':'EXAMPLE','kind':'implementation','plan_id':'starter','billing_ref':payload['metadata[billing_ref]'],'referral_reward':payload['metadata[referral_reward]']}}


def test_verified_zero_invoice_fulfils_setup_and_consumes_reward_without_referrer_award(client,stripe,monkeypatch):
    checkout=free_setup_checkout(client,stripe,monkeypatch)
    stripe.return_value={'id':'in_free','currency':'gbp','created':int(time.time()),'total':0,'amount_paid':0,'amount_remaining':0,
                         'status':'paid','metadata':checkout['metadata'],'lines':{'data':[]},'discounts':[{'coupon':'coupon_free'}]}
    for _ in range(2):
        subscriptions.sync_invoice('in_free')
    assert subscriptions._contract('EXAMPLE','platform')['implementation_paid']==1
    assert subscriptions.plan_state('EXAMPLE')['setup_plan']=='starter'
    rewards=referrals.report('EXAMPLE','new@example.test','https://example.test')['rewards']
    assert next(row['status'] for row in rewards if row['kind']=='implementation')=='used'
    assert next(row['status'] for row in rewards if row['kind']=='platform')=='available'
    assert referrals.report('SPONSOR','owner@example.test','https://example.test')['rewards']==[]
    assert subscriptions._contract('OTHER','platform')['implementation_paid']==0


def test_signed_no_cost_checkout_without_invoice_requires_canonical_proof(client,stripe,monkeypatch):
    checkout=free_setup_checkout(client,stripe,monkeypatch)
    stripe.return_value=checkout
    body=json.dumps({'type':'checkout.session.completed','data':{'object':{'id':'cs_free','metadata':{'tenant':'OTHER'}}}}).encode()
    assert client.post('/billing/stripe/webhook',data=body,content_type='application/json').status_code==403
    assert subscriptions._contract('EXAMPLE','platform')['implementation_paid']==0
    for _ in range(2):
        assert client.post('/billing/stripe/webhook',data=body,content_type='application/json',headers={'Stripe-Signature':signature(body)}).status_code==200
    assert subscriptions._contract('EXAMPLE','platform')['implementation_paid']==1
    assert subscriptions._contract('OTHER','platform')['implementation_paid']==0
    with subscriptions.connection('EXAMPLE') as db:
        proof=db.execute("SELECT status,invoice FROM referral_rewards WHERE tenant='EXAMPLE' AND kind='implementation'").fetchone()
        assert proof['status']=='used' and proof['invoice']=='cs_free'
        assert db.execute("SELECT 1 FROM billing_invoices WHERE tenant='EXAMPLE'").fetchone() is None
    assert referrals.report('SPONSOR','owner@example.test','https://example.test')['rewards']==[]


@pytest.mark.parametrize('field,value',[('status','open'),('payment_status','unpaid'),('currency','usd'),('amount_subtotal',1),('discounts',[]),('discounts',[{'coupon':'not_our_coupon'}]),('metadata',{'tenant':'OTHER','kind':'implementation'})])
def test_zero_checkout_never_fulfils_unbound_or_incomplete_order(client,stripe,monkeypatch,field,value):
    checkout=free_setup_checkout(client,stripe,monkeypatch)
    stripe.return_value={**checkout,field:value}
    with pytest.raises(ValueError):
        subscriptions.sync_zero_setup_checkout('cs_free')
    assert subscriptions._contract('EXAMPLE','platform')['implementation_paid']==0
    assert subscriptions._contract('OTHER','platform')['implementation_paid']==0


@pytest.mark.parametrize('kind,percent,total,remaining',[('platform',40,0,0),('implementation',40,0,0),('implementation',100,1,0),('implementation',100,0,1)])
def test_zero_payment_cannot_consume_non_free_or_outstanding_reward(client,monkeypatch,kind,percent,total,remaining):
    welcome(monkeypatch)
    with subscriptions.connection('EXAMPLE') as db:
        db.execute('UPDATE referral_rewards SET percent=? WHERE tenant=? AND kind=?',(percent,'EXAMPLE',kind))
    reward=referrals.reserve('EXAMPLE',kind,'bound')
    provider=Mock()
    provider.stripe_request.return_value={'id':'coupon_test','percent_off':percent,'duration':'once','valid':True}
    referrals.coupon(provider,'EXAMPLE',reward)
    referrals.consumed_payment('EXAMPLE',kind,'bound',{'id':'in_zero','status':'paid','amount_paid':0,'total':total,'amount_remaining':remaining,'discounts':[{'coupon':'coupon_test'}]})
    assert referrals.reserve('EXAMPLE',kind,'bound')['status']=='reserved'
