import hashlib
import hmac
import json
import time
from unittest.mock import Mock

import pytest
from connectors.billing import BillingClient
from service import subscriptions
from tests.conftest import set_test_identity


def identity(client, role='platform_admin', tenant='EXAMPLE'):
    with client.session_transaction() as state:
        set_test_identity(client,state,{'id':'billing-test','roles':[role],'tenant':tenant})


@pytest.fixture
def stripe(monkeypatch):
    monkeypatch.setenv('BILLING_PROVIDER','stripe')
    monkeypatch.setenv('STRIPE_API_KEY','test-api-key-not-real')
    monkeypatch.setenv('STRIPE_WEBHOOK_SECRET','test-webhook-secret-not-real')
    monkeypatch.setenv('STRIPE_TAX_RATE_ID','txr_test')
    request = Mock()
    monkeypatch.setattr(BillingClient,'stripe_request',request)
    return request


def signature(body):
    ts=str(int(time.time()))
    return 't='+ts+',v1='+hmac.new(b'test-webhook-secret-not-real',ts.encode()+b'.'+body,hashlib.sha256).hexdigest()


def test_owner_billing_is_private_and_only_platform_lists_companies(client):
    assert client.get('/billing/subscription').status_code==401
    identity(client,'business_owner')
    assert client.get('/billing/subscription').status_code==200
    assert client.get('/billing/subscription?tenant=OTHER').status_code==403
    assert client.get('/billing/companies').status_code==403
    assert client.post('/billing/api-charge',json={'month':'2025-01','amount_pence':100}).status_code==403
    assert client.post('/billing/whatsapp?tenant=OTHER',json={'enabled':False}).status_code==403
    identity(client,'business_staff')
    assert client.get('/billing/subscription').status_code==403
    identity(client)
    report=client.get('/billing/companies').json
    assert report['companies'][0]['key']=='EXAMPLE'
    assert report['companies'][0]['contracts']==[]


def test_checkout_prices_are_server_owned_and_include_one_time_implementation(client,stripe):
    stripe.side_effect=[{'active':True,'inclusive':False,'percentage':20}, {'id':'cs_test_checkout','url':'https://checkout.stripe.com/c/pay/example','expires_at':int(time.time())+3600}]
    identity(client,'business_owner')
    response=client.post('/billing/checkout',json={'kind':'platform','amount':1,'tenant':'OTHER'})
    assert response.status_code==200
    args=stripe.call_args.args
    assert args[:2]==('POST','/v1/checkout/sessions')
    body=args[2]
    assert body['metadata[tenant]']=='EXAMPLE'
    assert body['line_items[0][price_data][unit_amount]']==40000
    assert body['line_items[1][price_data][unit_amount]']==20000
    assert body['line_items[0][price_data][recurring][interval]']=='month'
    assert 'line_items[1][price_data][recurring][interval]' not in body
    assert body['line_items[0][tax_rates][0]']=='txr_test'
    assert body['subscription_data[metadata][billing_ref]']
    assert client.get('/billing/subscription').json['totals']['paid']==0


def test_bad_or_missing_stripe_signature_fails_closed(client,monkeypatch):
    monkeypatch.delenv('STRIPE_WEBHOOK_SECRET',raising=False)
    assert client.post('/billing/stripe/webhook',json={}).status_code==403
    monkeypatch.setenv('STRIPE_WEBHOOK_SECRET','test-webhook-secret-not-real')
    assert client.post('/billing/stripe/webhook',json={},headers={'Stripe-Signature':'t=1,v1=wrong'}).status_code==403
    connector=BillingClient.from_env()
    body=b'{}'
    assert connector.verify_webhook({'Stripe-Signature':signature(body)+',v1=oldkey'},body)
    assert not connector.verify_webhook({'Stripe-Signature':signature(body)},b'{"changed":true}')
    assert not connector.verify_webhook({'Stripe-Signature':'t=nan,v1=wrong'},body)


def test_verified_invoice_is_idempotent_and_totals_do_not_double_count(client,stripe):
    contract=subscriptions._contract('EXAMPLE','platform')
    sub={'metadata':{'tenant':'EXAMPLE','kind':'platform','billing_ref':contract['ref']},'customer':'cus_test','status':'active','items':{'data':[{'current_period_end':int(time.time())+86400}]}}
    invoice={'id':'in_test','currency':'gbp','created':int(time.time()),'parent':{'subscription_details':{'subscription':'sub_test'}},'total':72000,'amount_paid':72000,'amount_remaining':0,'status':'paid','billing_reason':'subscription_create','lines':{'data':[{'description':'V7 subscription','amount':40000},{'description':'V7 implementation','amount':20000}]}}
    stripe.side_effect=lambda method,path,*a,**k: invoice if path.startswith('/v1/invoices/') else sub
    body=json.dumps({'type':'invoice.paid','data':{'object':{'id':'in_test'}}}).encode()
    for _ in range(2):
        assert client.post('/billing/stripe/webhook',data=body,content_type='application/json',headers={'Stripe-Signature':signature(body)}).status_code==200
    identity(client)
    report=client.get('/billing/subscription').json
    assert report['totals']=={'paid':72000,'due':0,'approved_api_due':0}
    assert len(report['invoices'])==1
    assert report['contracts'][0]['implementation_paid']==1
    invoice.update(status='open',amount_paid=0,amount_remaining=72000)
    subscriptions.sync_invoice('in_test')
    assert client.get('/billing/subscription').json['totals']=={'paid':72000,'due':0,'approved_api_due':0}


def test_api_charge_requires_closed_month_valid_amount_and_one_approval(client):
    identity(client)
    assert client.post('/billing/api-charge',json={'month':'2099-01','amount_pence':100}).status_code==400
    assert client.post('/billing/api-charge',json={'month':'2025-01','amount_pence':True}).status_code==400
    assert client.post('/billing/api-charge',json={'month':'2025-01','amount_pence':100}).status_code==201
    assert client.post('/billing/api-charge',json={'month':'2025-01','amount_pence':100}).status_code==400


def test_whatsapp_deactivation_stops_agent_before_it_runs(client,stripe,monkeypatch):
    contract=subscriptions._contract('EXAMPLE','whatsapp')
    with subscriptions.connection() as db:
        db.execute("UPDATE billing_contracts SET subscription='sub_test',status='active',next_due=? WHERE ref=?",(int(time.time())+86400,contract['ref']))
    stripe.return_value={'metadata':{'tenant':'EXAMPLE','kind':'whatsapp','billing_ref':contract['ref']},'customer':'cus_test','status':'active','cancel_at_period_end':True,'items':{'data':[{'current_period_end':int(time.time())+86400}]}}
    identity(client,'business_owner')
    assert client.post('/billing/whatsapp',json={'enabled':False}).status_code==200
    assert stripe.call_args_list[0].args[2]=={'cancel_at_period_end':'true'}
    assert not subscriptions.whatsapp_enabled('EXAMPLE')
    from routes import whatsapp_routes
    handler=Mock()
    monkeypatch.setattr(whatsapp_routes,'_reply',handler)
    assert whatsapp_routes._process(client.application.container,{},'cloud')==''
    handler.assert_not_called()


def test_csrf_cannot_be_skipped_for_checkout(client):
    identity(client,'business_owner')
    assert client.post('/billing/checkout',json={'kind':'platform'},headers={'X-CSRF-Token':'wrong'}).status_code==403
