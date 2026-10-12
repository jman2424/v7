"""Plan prices, provider confirmation and company boundaries are server-owned."""
import time

import pytest

from service import subscriptions
from service.plan_catalog import get_plan
from tests.test_subscriptions import identity, stripe


@pytest.mark.parametrize('plan_id', ['starter','business','scale'])
@pytest.mark.parametrize('kind', ['platform','implementation'])
def test_all_plan_checkout_amounts_and_metadata_are_server_owned(client,stripe,plan_id,kind):
    identity(client,'business_owner')
    stripe.side_effect=[{'active':True,'inclusive':False,'percentage':20},
                        {'id':'cs_tier','url':'https://checkout.stripe.com/c/pay/tier'}]
    result=client.post('/billing/checkout',json={'kind':kind,'plan_id':plan_id,'amount_pence':1,'tenant':'OTHER'})
    assert result.status_code==200, result.json
    data=stripe.call_args.args[2]
    plan=get_plan(plan_id)
    assert data['line_items[0][price_data][unit_amount]']==plan['monthly_pence' if kind=='platform' else 'setup_pence']
    assert data['metadata[plan_id]']==plan_id
    assert data['metadata[tenant]']=='EXAMPLE'
    prefix='subscription_data[metadata]' if kind=='platform' else 'invoice_creation[invoice_data][metadata]'
    assert data[prefix+'[plan_id]']==plan_id
    assert subscriptions.plan_state('EXAMPLE')['active_plan'] is None
    assert subscriptions._contract('EXAMPLE','platform')['implementation_paid']==0


def test_invalid_plan_cannot_reach_stripe_and_selection_is_private(client,stripe):
    identity(client,'business_owner')
    for invalid in ['enterprise','STARTER',{},True,'']:
        response=client.post('/billing/checkout',json={'kind':'platform','plan_id':invalid})
        assert response.status_code==400
        assert response.json['error']=='invalid_subscription_plan'
    stripe.assert_not_called()
    assert client.post('/billing/select-plan?tenant=OTHER',json={'plan_id':'scale'}).status_code==403
    identity(client,'business_staff')
    assert client.post('/billing/select-plan',json={'plan_id':'scale'}).status_code==403
    identity(client,'business_owner')
    assert client.post('/billing/select-plan',json={'plan_id':'scale'},headers={'X-CSRF-Token':'wrong'}).status_code==403


def test_provider_metadata_cannot_upgrade_plan_or_activate_without_confirmation(client,stripe):
    identity(client,'business_owner')
    stripe.side_effect=[{'active':True,'inclusive':False,'percentage':20},
                        {'id':'cs_tier','url':'https://checkout.stripe.com/c/pay/tier'}]
    assert client.post('/billing/checkout',json={'kind':'platform','plan_id':'starter'}).status_code==200
    data=stripe.call_args.args[2]
    metadata={'tenant':'EXAMPLE','kind':'platform','billing_ref':data['metadata[billing_ref]'],'plan_id':'scale'}
    stripe.side_effect=None
    stripe.return_value={'metadata':metadata,'status':'active','items':{'data':[{'current_period_end':int(time.time())+86400}]}}
    with pytest.raises(ValueError,match='unknown_billing_plan'):
        subscriptions.sync_subscription('sub_tier')
    assert subscriptions.plan_state('EXAMPLE')['active_plan'] is None
    metadata['plan_id']='starter'
    subscriptions.sync_subscription('sub_tier')
    assert subscriptions.plan_state('EXAMPLE')['active_plan']=='starter'
    assert subscriptions.whatsapp_enabled('EXAMPLE')
    stripe.reset_mock()
    assert client.post('/billing/whatsapp',json={'enabled':False}).status_code==200
    assert not subscriptions.whatsapp_enabled('EXAMPLE')
    assert client.post('/billing/whatsapp',json={'enabled':True}).status_code==200
    stripe.assert_not_called()
    assert client.post('/billing/checkout',json={'kind':'whatsapp'}).json['error']=='whatsapp_included_in_subscription'
    assert client.post('/billing/api-charge',json={'month':'2025-01','amount_pence':100}).status_code==403
    identity(client)
    assert client.post('/billing/api-charge',json={'month':'2025-01','amount_pence':100}).json['error']=='prepaid_usage_requires_topup'
    assert client.post('/billing/select-plan',json={'plan_id':'scale'}).json['error']=='existing_subscription_requires_review'


def test_paid_setup_cannot_be_reused_for_another_plan(client,stripe):
    subscriptions.select_plan('EXAMPLE','starter')
    with subscriptions.connection('EXAMPLE') as db:
        db.execute("UPDATE billing_plan_state SET setup_plan='starter' WHERE tenant='EXAMPLE'")
    with pytest.raises(ValueError,match='paid_setup_plan_requires_review'):
        subscriptions.select_plan('EXAMPLE','scale')
    stripe.assert_not_called()


def test_existing_legacy_subscription_is_preserved(client,stripe):
    contract=subscriptions._contract('EXAMPLE','platform')
    with subscriptions.connection('EXAMPLE') as db:
        db.execute("UPDATE billing_contracts SET subscription='sub_legacy',status='active',implementation_paid=1 WHERE ref=?",(contract['ref'],))
    assert subscriptions.configured_plan('EXAMPLE') is None
    with pytest.raises(ValueError,match='existing_subscription_requires_review'):
        subscriptions.select_plan('EXAMPLE','starter')
    stripe.assert_not_called()


def test_admin_company_overview_does_not_enforce_historical_message_caps(client,stripe):
    from service import plan_usage
    subscriptions.select_plan('EXAMPLE','starter')
    with subscriptions.connection('EXAMPLE') as db:
        plan_usage._schema(db)
        db.execute('INSERT INTO billing_plan_usage (tenant,month,website_conversations,website_paused) VALUES (?,?,?,?)',('EXAMPLE',plan_usage._month(),300,1))
    identity(client)
    company=next(row for row in client.get('/billing/companies').json['companies'] if row['key']=='EXAMPLE')
    assert not any(alert['resource']=='website_conversations' for alert in company['allowance']['alerts'])
    assert company['allowance']['website_conversations']['used']==300
    assert company['allowance']['website_conversations']['enforced'] is False
    assert not company['allowance']['website_conversations']['paused']


def test_invoice_without_bound_plan_is_rejected(client,stripe):
    contract=subscriptions._contract('EXAMPLE','implementation')
    stripe.return_value={'currency':'gbp','created':int(time.time()),'metadata':{'tenant':'EXAMPLE','kind':'implementation','billing_ref':contract['ref'],'plan_id':'scale'}}
    with pytest.raises(ValueError,match='unknown_billing_plan'):
        subscriptions.sync_invoice('in_fake')


def test_setup_cannot_use_a_cheaper_plan_while_monthly_checkout_is_open(client,stripe):
    identity(client,'business_owner')
    stripe.side_effect=[{'active':True,'inclusive':False,'percentage':20},
                        {'id':'cs_scale','url':'https://checkout.stripe.com/c/pay/scale','expires_at':int(time.time())+3600}]
    assert client.post('/billing/checkout',json={'kind':'platform','plan_id':'scale'}).status_code==200
    stripe.reset_mock()
    stripe.side_effect=None
    assert client.post('/billing/checkout',json={'kind':'implementation','plan_id':'starter'}).json['error']=='cancel_pending_checkout_before_changing_plan'
    stripe.assert_not_called()
    assert subscriptions.plan_state('EXAMPLE')['selected_plan']=='scale'
    stripe.side_effect=[{'status':'open'},{'status':'expired'}]
    assert client.post('/billing/cancel-checkout').status_code==200
    assert not subscriptions.plan_state('EXAMPLE')['checkout_pending']
    assert client.post('/billing/select-plan',json={'plan_id':'starter'}).status_code==200


def test_tiered_activation_requires_matching_paid_setup(client):
    from service import tenant_access
    tenant_access.register('EXAMPLE')
    subscriptions.select_plan('EXAMPLE','scale')
    subscriptions._contract('EXAMPLE','platform')
    with subscriptions.connection('EXAMPLE') as db:
        db.execute("UPDATE billing_plan_state SET active_plan='scale',setup_plan='starter' WHERE tenant='EXAMPLE'")
        db.execute("UPDATE billing_contracts SET status='active',implementation_paid=1 WHERE tenant='EXAMPLE' AND kind='platform'")
        db.execute("INSERT INTO billing_invoices VALUES ('in_scale','EXAMPLE','platform','2025-01',1,NULL,100,100,0,'paid','[]',NULL)")
    assert not tenant_access.activation('EXAMPLE')['active']
