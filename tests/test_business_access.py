import json
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from service import subscriptions, tenant_access
from service.account_service import AccountService
from service.security import generate_totp_token
from tests.conftest import set_test_identity
from tests.test_subscriptions import signature, stripe


def owner(client, name='owner'):
    with client.session_transaction() as state:
        set_test_identity(client, state, {'id':name, 'roles':['business_owner'], 'tenant':'EXAMPLE'})


def staff_login(client, secret=None):
    response = client.post('/auth/login', json={'tenant':'EXAMPLE','email':'staff@testing.test','password':'Test-password-only-123'})
    assert response.status_code == 202
    assert client.get('/billing/subscription').status_code == 401
    secret = secret or response.json['mfa']['setup_key']
    confirmed = client.post('/auth/mfa/confirm', json={'code':generate_totp_token(secret)})
    assert confirmed.status_code == 200
    return secret


def test_owner_can_configure_only_their_additional_businesses(client):
    owner(client)
    created = client.post('/admin/api/tenants', json={'key':'SHOP','name':'Grocery shop','active':True,'owner':'someone-else'})
    assert created.status_code == 201
    assert created.json['tenant']['activation']['active'] is False
    assert {row['key'] for row in client.get('/admin/api/tenants').json['tenants']} == {'EXAMPLE','SHOP'}
    assert client.get('/admin/api/catalog?tenant=SHOP').status_code == 200
    profile = client.get('/admin/api/profile?tenant=SHOP').json
    profile['about'] = 'Fresh groceries'
    assert client.put('/admin/api/profile?tenant=SHOP', json=profile).status_code == 200
    assert client.get('/billing/subscription?tenant=SHOP').status_code == 200
    assert client.get('/files/raw/catalog.json?tenant=SHOP').status_code == 200
    assert client.get('/admin/api/platform').status_code == 403
    assert client.post('/admin/api/accounts?tenant=SHOP', json={'email':'staff@shop.test','password':'Test-password-only-123','roles':['business_staff']}).status_code == 201
    owner(client, 'other-owner')
    for path in ['/admin/api/catalog','/billing/subscription','/files/raw/catalog.json','/admin/api/activation','/admin/api/accounts']:
        assert client.get(path+'?tenant=SHOP').status_code == 403
    assert {row['key'] for row in client.get('/admin/api/tenants').json['tenants']} == {'EXAMPLE'}


@pytest.mark.parametrize('permissions', [[], ['view_costs'], ['view_subscriptions'], ['view_costs','view_subscriptions']])
def test_staff_permissions_are_independent_read_only_and_revocable(client, monkeypatch, permissions):
    owner(client)
    created=client.post('/admin/api/accounts', json={'email':'staff@testing.test','password':'Test-password-only-123','roles':['business_staff'],'permissions':permissions})
    assert created.status_code == 201
    account=created.json['account']
    with subscriptions.connection() as db:
        db.execute('INSERT INTO billing_invoices VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', ('in_api','EXAMPLE','api','2026-01',1,None,1200,1200,0,'paid','[]','https://invoice.stripe.com/test'))
    secret=staff_login(client)
    assert set(client.get('/auth/session').json['user']['permissions'])==set(permissions)
    usage=client.get('/admin/api/api-usage')
    assert usage.status_code == (200 if 'view_costs' in permissions else 403)
    response=client.get('/billing/subscription')
    assert response.status_code == (200 if 'view_subscriptions' in permissions else 403)
    if response.status_code==200:
        assert response.json['totals']['paid']==(1200 if 'view_costs' in permissions else 0)
        assert all(row['url'] is None for row in response.json['invoices'])
        if 'view_costs' not in permissions:
            assert response.json['usage']==[]
            assert response.json['invoices']==[]
    for path,body in [('/billing/checkout',{'kind':'platform'}),('/billing/portal',{}),('/billing/whatsapp',{'enabled':True}),('/admin/api/tenants',{'key':'BAD','name':'Bad'})]:
        assert client.post(path,json=body).status_code==403
    assert client.put('/admin/api/accounts/'+account['id'],json={'permissions':['view_costs','view_subscriptions']}).status_code==403
    assert client.get('/admin/api/api-usage?scope=all').status_code==403
    assert client.get('/billing/subscription?tenant=OTHER').status_code==403
    AccountService(client.application.container.storage).update_account('EXAMPLE',account['id'],{'permissions':[]})
    if permissions:
        assert client.get('/admin/api/catalog').status_code==401
        staff_login(client,secret)
    assert client.get('/billing/subscription').status_code==403
    assert client.get('/admin/api/api-usage').status_code==403


def test_unknown_permissions_rejected(client):
    owner(client)
    assert client.post('/admin/api/accounts',json={'email':'staff@testing.test','password':'Test-password-only-123','roles':['business_staff'],'permissions':['platform_admin']}).status_code==400


def test_activation_requires_both_verified_payments_and_blocks_all_agent_paths(client,stripe,monkeypatch):
    owner(client)
    assert client.post('/admin/api/tenants',json={'key':'SHOP','name':'Grocery shop'}).status_code==201
    assert client.get('/admin/api/activation?tenant=SHOP').json['active'] is False
    assert client.post('/admin/api/test-agent?tenant=SHOP',json={'message':'hello'}).status_code==403
    assert client.post('/chat_api',json={'tenant':'SHOP','message':'hello'}).status_code==403
    from routes import whatsapp_routes
    reply=Mock()
    monkeypatch.setattr(whatsapp_routes,'_reply',reply)
    assert whatsapp_routes._process(SimpleNamespace(settings=SimpleNamespace(BUSINESS_KEY='SHOP')),{},'cloud')==''
    reply.assert_not_called()
    plan=subscriptions._contract('SHOP','platform')
    setup=subscriptions._contract('SHOP','implementation')
    sub={'metadata':{'tenant':'SHOP','kind':'platform','billing_ref':plan['ref']},'customer':'cus_shop','status':'active','items':{'data':[{'current_period_end':int(time.time())+86400}]}}
    invoice={'id':'in_setup','currency':'gbp','created':int(time.time()),'customer':'cus_shop','metadata':{'tenant':'SHOP','kind':'implementation','billing_ref':setup['ref']},'total':24000,'amount_paid':24000,'amount_remaining':0,'status':'paid','lines':{'data':[]}}
    stripe.side_effect=lambda method,path,*a,**k: invoice if path.startswith('/v1/invoices/') else sub
    # Redirects and invalid signatures cannot activate the business.
    client.get('/console/subscription?payment=processing')
    assert client.post('/billing/stripe/webhook',json={'type':'invoice.paid','data':{'object':{'id':'in_setup'}}}).status_code==403
    assert tenant_access.activation('SHOP')['active'] is False
    subscriptions.sync_subscription('sub_shop')
    assert tenant_access.activation('SHOP')['active'] is False
    body=json.dumps({'type':'invoice.paid','data':{'object':{'id':'in_setup'}}}).encode()
    for _ in range(2):
        assert client.post('/billing/stripe/webhook',data=body,content_type='application/json',headers={'Stripe-Signature':signature(body)}).status_code==200
    assert tenant_access.activation('SHOP')['active'] is False
    invoice={'id':'in_plan','currency':'gbp','created':int(time.time()),'subscription':'sub_shop','total':48000,'amount_paid':48000,'amount_remaining':0,'status':'paid','billing_reason':'subscription_create','lines':{'data':[{'description':'V7 monthly subscription','amount':40000}]}}
    body=json.dumps({'type':'invoice.paid','data':{'object':{'id':'in_plan'}}}).encode()
    assert client.post('/billing/stripe/webhook',data=body,content_type='application/json',headers={'Stripe-Signature':signature(body)}).status_code==200
    assert tenant_access.activation('SHOP')['active'] is True
    assert client.get('/admin/api/activation?tenant=SHOP').json['active'] is True
    assert client.get('/chat_ui?tenant=SHOP').status_code==200
    sub['status']='past_due'
    subscriptions.sync_subscription('sub_shop')
    assert tenant_access.activation('SHOP')['active'] is False
