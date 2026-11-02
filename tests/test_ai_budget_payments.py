"""No live money: consent, canonical Stripe evidence, tenant locks and recovery."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
import time

import pytest

from connectors.billing import BillingClient, StripePaymentError
from service import ai_budget as budget, ai_budget_payments as payments, ai_budget_store as store
from service import business_applications as applications, subscriptions, usage_wallet
from tests.test_subscriptions import identity, signature


@pytest.fixture
def card(client,monkeypatch):
    from service import usage_currency
    from datetime import date
    rate={'rate':1,'date':date.today().isoformat(),'stale':False,'source':'synthetic'}
    monkeypatch.setattr(usage_currency,'gbp_rate',lambda:dict(rate))
    monkeypatch.setattr(usage_currency,'cached_gbp_rate',lambda:dict(rate))
    monkeypatch.setenv('BILLING_PROVIDER','stripe')
    monkeypatch.setenv('STRIPE_API_KEY','sk_test_synthetic')
    monkeypatch.setenv('STRIPE_WEBHOOK_SECRET','test-webhook-secret-not-real')
    monkeypatch.setenv('V7_VAT_REGISTERED','false')
    monkeypatch.setattr(budget,'require_eligible',lambda tenant: {'active':True})
    state = {'objects':{},'requests':[],'creates':0,'status':'succeeded'}
    def request(self,method,path,data=None,**kw):
        state['requests'].append((method,path,deepcopy(data),kw))
        if method == 'POST' and path == '/v1/customers':
            return {'id':'cus_budget'}
        if method == 'POST' and path == '/v1/checkout/sessions':
            metadata = {k[9:-1]:v for k,v in data.items() if k.startswith('metadata[')}
            checkout_id='cs_'+metadata['budget_authorisation']
            setup_id='seti_'+metadata['budget_authorisation']
            common = {'customer':data['customer'],'livemode':False,'metadata':metadata}
            checkout = {**common,'id':checkout_id,'status':'complete','mode':'setup','setup_intent':setup_id,
                        'url':'https://checkout.stripe.com/c/pay/budget'}
            state['objects'].update({'/v1/checkout/sessions/'+checkout_id:checkout,
                '/v1/setup_intents/'+setup_id:{**common,'id':setup_id,'status':'succeeded','usage':'off_session','payment_method':'pm_budget'},
                '/v1/payment_methods/pm_budget':{'id':'pm_budget','customer':data['customer'],'type':'card','livemode':False}})
            return deepcopy(checkout)
        if method == 'POST' and path == '/v1/payment_intents':
            key = kw['idempotency_key']
            identifier = 'pi_'+key.rsplit('-',1)[-1]
            if '/v1/payment_intents/'+identifier in state['objects']:
                return deepcopy(state['objects']['/v1/payment_intents/'+identifier])
            state['creates'] += 1
            metadata = {k[9:-1]:v for k,v in data.items() if k.startswith('metadata[')}
            charge_id = 'ch_'+identifier[3:]
            common = {'customer':data['customer'],'currency':'gbp','livemode':False}
            intent = {**common,'id':identifier,'metadata':metadata,'status':state['status'],
                'payment_method':data['payment_method'],'amount':500,'amount_received':500,'latest_charge':charge_id}
            charge = {**common,'id':charge_id,'payment_intent':identifier,'paid':True,'captured':True,'status':'succeeded',
                'amount':500,'amount_captured':500,'amount_refunded':0,'disputed':False,'receipt_url':'https://pay.stripe.com/receipts/budget'}
            state['objects'].update({'/v1/payment_intents/'+identifier:intent,'/v1/charges/'+charge_id:charge,
                '/v1/disputes?charge='+charge_id+'&limit=100':{'data':[],'has_more':False}})
            if state.get('uncertain'):
                raise ValueError('synthetic_network_interruption')
            if state.get('http402'):
                raise StripePaymentError(identifier)
            return deepcopy(intent)
        if method == 'POST' and path.endswith('/cancel'):
            state['objects'][path[:-7]]['status'] = 'canceled'
            return deepcopy(state['objects'][path[:-7]])
        assert method == 'GET' and path in state['objects'],(method,path)
        return deepcopy(state['objects'][path])
    monkeypatch.setattr(BillingClient,'stripe_request',request)
    identity(client,'business_owner')
    # The signed-in test identity has a real active credential revision.
    result = client.post('/billing/ai-budget/automatic-recharge/authorise',json={'accepted_terms':True,'cap_pence':2500,'request_id':'synthetic-consent-001'})
    assert result.status_code == 200,result.json
    result = client.post('/billing/ai-budget/automatic-recharge/confirm',json={})
    assert result.status_code == 200,result.json
    assert result.json['status']=='active',result.json
    return state


def reserve(client):
    with client.application.app_context():
        reference = payments.reserve_recharge('EXAMPLE')
    assert reference
    return reference


def process(client,ref):
    with client.application.app_context():
        return payments.process_recharge('EXAMPLE',ref)


def test_explicit_consent_and_no_payment_before_worker(client,card):
    assert not any(row[1]=='/v1/payment_intents' for row in card['requests'])
    data = client.get('/billing/ai-budget').json
    assert data['automatic_recharge']['enabled']
    setup = next(row[2] for row in card['requests'] if row[1]=='/v1/checkout/sessions' and row[0]=='POST')
    assert setup['mode']=='setup' and '£5' in setup['custom_text[submit][message]']
    assert not any('line_items' in key for key in setup)


def test_canonical_payment_once_and_no_second_event_above_threshold(client,card):
    ref=reserve(client)
    assert process(client,ref)
    assert not process(client,ref)
    assert usage_wallet.report('EXAMPLE')['balance_pence']==500
    assert usage_wallet.report('OTHER')['balance_pence']==0
    with client.application.app_context():
        assert payments.reserve_recharge('EXAMPLE') is None
    payment=next(obj for path,obj in card['objects'].items() if path.startswith('/v1/payment_intents/'))
    event={'id':'evt_budget','type':'payment_intent.succeeded','data':{'object':payment}}
    body=json.dumps(event).encode()
    assert client.post('/billing/stripe/webhook',data=body,headers={'Stripe-Signature':'bad'},content_type='application/json').status_code==403
    for _ in range(2):
        assert client.post('/billing/stripe/webhook',data=body,headers={'Stripe-Signature':signature(body)},content_type='application/json').status_code==200
    assert usage_wallet.report('EXAMPLE')['balance_pence']==500
    assert card['creates']==1


def test_cap_is_atomic_and_counts_inflight_not_just_paid(client,card):
    for _ in range(5):
        ref=reserve(client)
        assert process(client,ref)
        held=usage_wallet.reserve_usage('EXAMPLE',500*usage_wallet.NANO_PER_PENNY)
        usage_wallet.settle_usage(held,500*usage_wallet.NANO_PER_PENNY)
    with client.application.app_context():
        assert payments.reserve_recharge('EXAMPLE') is None
    assert card['creates']==5
    report=client.get('/billing/ai-budget').json
    assert report['automatic_recharge']['spent_this_month_pence']==2500
    assert sum(n['kind']=='recharge_cap' for n in report['notifications'])==1


def test_concurrent_reservations_and_execution_share_one_intent(client,card):
    def attempt(_):
        with client.application.app_context():
            return payments.reserve_recharge('EXAMPLE')
    with ThreadPoolExecutor(max_workers=6) as pool:
        refs=list(pool.map(attempt,range(12)))
    assert len(set(refs))==1
    def run(_):
        return process(client,refs[0])
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(run,range(6)))
    assert card['creates']==1
    assert usage_wallet.report('EXAMPLE')['balance_pence']==500


@pytest.mark.parametrize('state',['requires_action','requires_payment_method'])
def test_failed_or_authentication_payment_blocks_repeat_and_can_cancel(client,card,state):
    card['status'],card['http402']=state,True
    ref=reserve(client)
    assert process(client,ref)
    assert usage_wallet.report('EXAMPLE')['balance_pence']==0
    with client.application.app_context():
        assert payments.reserve_recharge('EXAMPLE') is None
        assert not payments.process_recharge('EXAMPLE',ref)
        assert payments.cancel_recharge('EXAMPLE',ref)
    assert card['creates']==1


def test_opt_out_cancels_unsent_and_expires_approval_hold(client,card):
    ref=reserve(client)
    assert client.post('/billing/ai-budget/automatic-recharge/disable',json={}).status_code==200
    assert not process(client,ref)
    assert not card['creates']
    with applications.database('EXAMPLE') as db:
        permit=applications._one(applications._execute(db,'SELECT state FROM business_application_permits WHERE tenant=? AND reference=?',('EXAMPLE',ref)))
    assert permit['state']=='expired'
    assert client.post('/billing/ai-budget/automatic-recharge/confirm',json={}).json['status']=='revoked'


def test_uncertain_creation_retry_reuses_exact_key_and_unknown_cannot_be_cancelled(client,card):
    card['uncertain']=True
    ref=reserve(client)
    with pytest.raises(ValueError):
        process(client,ref)
    with client.application.app_context():
        with pytest.raises(budget.BudgetError,match='needs_review'):
            payments.cancel_recharge('EXAMPLE',ref)
    with store.connection('EXAMPLE',write=True) as db:
        db.execute('UPDATE ai_budget_recharges SET lease_until=0 WHERE tenant=? AND reference=?',('EXAMPLE',ref))
    card['uncertain']=False
    assert process(client,ref)
    assert card['creates']==1
    assert usage_wallet.report('EXAMPLE')['balance_pence']==500
    creates=[r for r in card['requests'] if r[0]=='POST' and r[1]=='/v1/payment_intents']
    assert len(creates)==2 and creates[0][3]==creates[1][3]


def test_provider_mismatch_cannot_credit_and_other_tenant_cannot_reconcile(client,card):
    ref=reserve(client)
    card['uncertain']=True
    with pytest.raises(ValueError):
        process(client,ref)
    payment=next(o for p,o in card['objects'].items() if p.startswith('/v1/payment_intents/'))
    payment['amount']=1
    with client.application.app_context():
        with pytest.raises(budget.BudgetError,match='mismatch'):
            payments.reconcile_payment('EXAMPLE',ref,payment['id'])
        with pytest.raises(budget.BudgetError,match='not_found'):
            payments.reconcile_payment('OTHER',ref,payment['id'])
    assert usage_wallet.report('EXAMPLE')['balance_pence']==0


def test_disabled_credential_cannot_dispatch_or_reenable(client,card,monkeypatch):
    ref=reserve(client)
    monkeypatch.setattr('service.security._revision',lambda identity:None)
    assert not process(client,ref)
    assert card['creates']==0


def test_production_release_switch_blocks_authorisation_and_worker(client,card,monkeypatch):
    monkeypatch.setattr('service.usage_payments._production',lambda:True)
    monkeypatch.delenv('V7_AUTO_RECHARGE_LIVE_ENABLED',raising=False)
    with client.application.app_context():
        assert payments.reserve_recharge('EXAMPLE') is None
    assert card['creates']==0


def test_canonical_refund_reverses_exact_balance_once(client,card):
    ref=reserve(client)
    process(client,ref)
    payment=next(o for p,o in card['objects'].items() if p.startswith('/v1/payment_intents/'))
    charge=card['objects']['/v1/charges/'+payment['latest_charge']]
    charge['amount_refunded']=250
    with client.application.app_context():
        for _ in range(2):
            payments.reconcile_payment('EXAMPLE',ref,payment['id'],event_id='evt_partial_refund')
    assert usage_wallet.report('EXAMPLE')['balance_pence']==250
    assert not client.get('/billing/ai-budget').json['automatic_recharge']['enabled']
    with client.application.app_context():
        assert payments.reserve_recharge('EXAMPLE') is None


def test_stale_unknown_retains_cap_instead_of_fresh_payment(client,card):
    ref=reserve(client)
    with store.connection('EXAMPLE',write=True) as db:
        db.execute('UPDATE ai_budget_recharges SET created=? WHERE tenant=? AND reference=?',(time.time()-86400,'EXAMPLE',ref))
    assert not process(client,ref)
    assert card['creates']==0


def test_manual_funding_before_dispatch_prevents_unnecessary_charge(client,card):
    ref=reserve(client)
    usage_wallet.apply_payment('EXAMPLE','manual_funding','pi_manualfunding',2500,2500)
    assert not process(client,ref)
    assert card['creates']==0
    with store.connection('EXAMPLE') as db:
        assert store.monthly_reserved(db,'EXAMPLE')==0


def test_suspended_business_cannot_dispatch_previously_reserved_purchase(client,card,monkeypatch):
    ref=reserve(client)
    def inactive(tenant):
        raise budget.BudgetError('budget_active_business_required',403)
    monkeypatch.setattr(budget,'require_eligible',inactive)
    with pytest.raises(budget.BudgetError):
        process(client,ref)
    assert card['creates']==0


def test_unknown_usage_never_triggers_another_card_purchase(client,card):
    usage_wallet.apply_payment('EXAMPLE','some_funds','pi_somefunds',100,100)
    held=usage_wallet.reserve_usage('EXAMPLE',10*usage_wallet.NANO_PER_PENNY)
    usage_wallet.settle_usage(held,None)
    with client.application.app_context():
        assert payments.reserve_recharge('EXAMPLE') is None
    assert card['creates']==0


def test_interrupted_finalisation_recovers_credit_without_another_charge(client,card,monkeypatch):
    ref=reserve(client)
    notify=store.notify
    def fail(db,tenant,kind,*args,**kwargs):
        if kind=='recharge_succeeded':
            raise ValueError('synthetic_crash_after_ledger_commit')
        return notify(db,tenant,kind,*args,**kwargs)
    monkeypatch.setattr(store,'notify',fail)
    with pytest.raises(ValueError):
        process(client,ref)
    assert usage_wallet.report('EXAMPLE')['balance_pence']==500
    monkeypatch.setattr(store,'notify',notify)
    assert process(client,ref)
    assert usage_wallet.report('EXAMPLE')['balance_pence']==500 and card['creates']==1


def test_cap_change_requires_fresh_consent_and_reuses_business_customer(client,card):
    response=client.post('/billing/ai-budget/automatic-recharge/authorise',json={'accepted_terms':True,'cap_pence':5000,'request_id':'synthetic-consent-002'})
    assert response.status_code==200,response.json
    report=client.get('/billing/ai-budget').json
    assert not report['automatic_recharge']['enabled']
    assert client.post('/billing/ai-budget/automatic-recharge/confirm',json={}).json['status']=='active'
    assert client.get('/billing/ai-budget').json['automatic_recharge']['cap_pence']==5000
    assert sum(r[0]=='POST' and r[1]=='/v1/customers' for r in card['requests'])==1
