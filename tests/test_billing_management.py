"""Owner confirmation and paid provider evidence control subscription changes."""
import copy
import time

import pytest

from service import billing_management, subscriptions, tenant_access
from service.plan_catalog import get_plan
from tests.test_subscriptions import identity, stripe as stripe_fixture

stripe = stripe_fixture


@pytest.fixture
def managed_subscription(client, stripe):
    subscriptions.select_plan('EXAMPLE', 'starter')
    contract = subscriptions._contract('EXAMPLE', 'platform')
    now = int(time.time())
    with subscriptions.connection('EXAMPLE') as db:
        db.execute('INSERT INTO billing_plan_choices VALUES (?,?,?,?)', (contract['ref'], 'EXAMPLE', 'platform', 'starter'))
        db.execute("UPDATE billing_plan_state SET active_plan='starter',setup_plan='starter' WHERE tenant='EXAMPLE'")
        db.execute("UPDATE billing_contracts SET subscription='sub_managed',customer='cus_managed',status='active',"
                   "implementation_paid=1,next_due=? WHERE tenant='EXAMPLE' AND kind='platform'", (now + 86400,))
        db.execute("INSERT INTO billing_invoices VALUES ('in_original','EXAMPLE','platform','2026-10',?,NULL,9900,9900,0,'paid','[]',NULL)", (now,))
    tenant_access.register('EXAMPLE')

    def price(plan_id):
        return {'id': 'price_' + plan_id, 'product': 'prod_' + plan_id, 'active': True, 'currency': 'gbp',
                'unit_amount': get_plan(plan_id)['monthly_pence'], 'tax_behavior': 'exclusive',
                'recurring': {'interval': 'month', 'interval_count': 1, 'usage_type': 'licensed'}}

    data = {'id': 'sub_managed', 'customer': 'cus_managed', 'status': 'active',
            'metadata': {'tenant': 'EXAMPLE', 'kind': 'platform', 'billing_ref': contract['ref'], 'plan_id': 'starter'},
            'items': {'data': [{'id': 'si_managed', 'quantity': 1, 'price': price('starter'), 'current_period_end': now + 86400}]}}
    invoices = {}

    def provider(method, path, body=None, **kwargs):
        if method == 'GET' and path == '/v1/subscriptions/sub_managed':
            return copy.deepcopy(data)
        if method == 'GET' and path.startswith('/v1/invoices/'):
            return copy.deepcopy(invoices[path.rsplit('/', 1)[-1]])
        if method == 'POST' and path == '/v1/prices':
            return price(body['metadata[v7_plan_id]'])
        if method == 'POST' and path == '/v1/billing_portal/configurations':
            return {'id': 'bpc_managed'}
        if method == 'POST' and path == '/v1/billing_portal/sessions':
            return {'url': 'https://billing.stripe.com/p/session/managed'}
        raise AssertionError('Unexpected provider operation: ' + method + ' ' + path)

    stripe.side_effect = provider
    identity(client, 'business_owner')
    return {'data': data, 'price': price, 'invoices': invoices, 'ref': contract['ref'], 'now': now}


def confirm_plan(subject, plan_id, *, paid=True):
    data = subject['data']
    data['items']['data'][0]['price'] = subject['price'](plan_id)
    data['latest_invoice'] = {'id': 'in_change' + plan_id, 'status': 'paid' if paid else 'open',
                              'currency': 'gbp', 'created': int(time.time()), 'subscription': 'sub_managed',
                              'lines': {'data': [{'pricing': {'price_details': {'price': 'price_' + plan_id}}}]}}


def test_active_change_is_reviewed_in_stripe_and_activated_only_after_paid_evidence(client, stripe, managed_subscription):
    response = client.post('/billing/change-plan', json={'plan_id': 'business', 'amount_pence': 1, 'tenant': 'OTHER'})
    assert response.status_code == 200, response.json
    assert response.json['url'].startswith('https://billing.stripe.com/')
    calls = stripe.call_args_list
    price = next(call.args[2] for call in calls if call.args[1] == '/v1/prices')
    assert price['unit_amount'] == 19900 and price['currency'] == 'gbp'
    config = next(call.args[2] for call in calls if call.args[1] == '/v1/billing_portal/configurations')
    assert config['features[subscription_update][proration_behavior]'] == 'always_invoice'
    assert config['features[subscription_update][billing_cycle_anchor]'] == 'unchanged'
    flow = calls[-1].args[2]
    assert flow['customer'] == 'cus_managed' and flow['flow_data[type]'] == 'subscription_update_confirm'
    assert flow['flow_data[subscription_update_confirm][subscription]'] == 'sub_managed'
    assert flow['flow_data[subscription_update_confirm][items][0][price]'] == 'price_business'
    assert flow['flow_data[subscription_update_confirm][items][0][quantity]'] == 1
    assert flow['return_url'].endswith('/console/subscription?tenant=EXAMPLE')
    assert subscriptions.plan_state('EXAMPLE')['active_plan'] == 'starter'
    confirm_plan(managed_subscription, 'business', paid=False)
    subscriptions.sync_subscription('sub_managed')
    assert subscriptions.plan_state('EXAMPLE')['active_plan'] == 'starter'
    confirm_plan(managed_subscription, 'business')
    for _ in range(2):
        subscriptions.sync_subscription('sub_managed')
    state = subscriptions.plan_state('EXAMPLE')
    assert state['active_plan'] == state['selected_plan'] == 'business' and state['setup_plan'] == 'starter'
    assert tenant_access.activation('EXAMPLE')['active']
    with subscriptions.connection('EXAMPLE') as db:
        assert db.execute('SELECT plan_id FROM billing_plan_choices WHERE ref=?', (managed_subscription['ref'],)).fetchone()['plan_id'] == 'starter'
        assert db.execute("SELECT count(*) n FROM billing_plan_changes WHERE tenant='EXAMPLE' AND status='applied'").fetchone()['n'] == 1


def test_unpaid_second_change_retains_previously_confirmed_plan(client, stripe, managed_subscription):
    assert client.post('/billing/change-plan', json={'plan_id': 'business'}).status_code == 200
    confirm_plan(managed_subscription, 'business')
    subscriptions.sync_subscription('sub_managed')
    assert client.post('/billing/change-plan', json={'plan_id': 'scale'}).status_code == 200
    confirm_plan(managed_subscription, 'scale', paid=False)
    subscriptions.sync_subscription('sub_managed')
    assert subscriptions.plan_state('EXAMPLE')['active_plan'] == 'business'
    assert tenant_access.activation('EXAMPLE')['active']


@pytest.mark.parametrize('plan_id', ['', 'enterprise', 'STARTER', True, {}, None])
def test_invalid_plan_cannot_contact_provider(client, stripe, plan_id):
    identity(client, 'business_owner')
    assert client.post('/billing/change-plan', json={'plan_id': plan_id}).json == {'error': 'invalid_subscription_plan'}
    stripe.assert_not_called()


@pytest.mark.parametrize('path', ['change-plan', 'cancel-subscription'])
def test_management_requires_owner_tenant_and_csrf(client, stripe, managed_subscription, path):
    body = {'plan_id': 'business'}
    stripe.reset_mock()
    assert client.post('/billing/' + path + '?tenant=OTHER', json=body).status_code == 403
    assert client.post('/billing/' + path, json=body, headers={'X-CSRF-Token': 'wrong'}).status_code == 403
    identity(client, 'business_staff')
    assert client.post('/billing/' + path, json=body).status_code == 403
    stripe.assert_not_called()


def test_provider_tenant_reference_cannot_be_used_for_another_company(client, stripe, managed_subscription):
    managed_subscription['data']['metadata']['tenant'] = 'OTHER'
    response = client.post('/billing/change-plan', json={'plan_id': 'business'})
    assert response.status_code == 400 and response.json == {'error': 'unknown_billing_reference'}
    assert all(call.args[0] == 'GET' for call in stripe.call_args_list)


def test_cancel_opens_period_end_confirmation_and_preserves_access_until_provider_ends_it(client, stripe, managed_subscription):
    response = client.post('/billing/cancel-subscription', json={})
    assert response.status_code == 200, response.json
    config = stripe.call_args_list[1].args[2]
    assert config['features[subscription_cancel][mode]'] == 'at_period_end'
    assert config['features[subscription_cancel][proration_behavior]'] == 'none'
    flow = stripe.call_args.args[2]
    assert flow['flow_data[type]'] == 'subscription_cancel'
    assert flow['flow_data[subscription_cancel][subscription]'] == 'sub_managed'
    assert not subscriptions._contract('EXAMPLE', 'platform')['cancel_at_end']
    assert tenant_access.activation('EXAMPLE')['active']
    managed_subscription['data']['cancel_at_period_end'] = True
    subscriptions.sync_subscription('sub_managed')
    assert subscriptions._contract('EXAMPLE', 'platform')['cancel_at_end'] == 1
    assert tenant_access.activation('EXAMPLE')['active'] and not billing_management.summary('EXAMPLE')['can_cancel']
    managed_subscription['data']['status'] = 'canceled'
    subscriptions.sync_subscription('sub_managed')
    assert not tenant_access.activation('EXAMPLE')['active']
    assert not any(call.args[0] == 'POST' and call.args[1].startswith('/v1/subscriptions/') for call in stripe.call_args_list)


@pytest.mark.parametrize('field,value', [('currency', 'usd'), ('status', 'open'), ('subscription', 'sub_other'), ('created', 1)])
def test_wrong_or_unpaid_invoice_cannot_upgrade_entitlements(client, stripe, managed_subscription, field, value):
    assert client.post('/billing/change-plan', json={'plan_id': 'scale'}).status_code == 200
    confirm_plan(managed_subscription, 'scale')
    managed_subscription['data']['latest_invoice'][field] = value
    subscriptions.sync_subscription('sub_managed')
    assert subscriptions.plan_state('EXAMPLE')['active_plan'] == 'starter'


def test_wrong_price_or_original_metadata_cannot_claim_an_upgrade(client, stripe, managed_subscription):
    assert client.post('/billing/change-plan', json={'plan_id': 'scale'}).status_code == 200
    confirm_plan(managed_subscription, 'scale')
    managed_subscription['data']['items']['data'][0]['price']['unit_amount'] = 1
    with pytest.raises(ValueError, match='unknown_billing_plan'):
        subscriptions.sync_subscription('sub_managed')
    managed_subscription['data']['metadata']['plan_id'] = 'scale'
    with pytest.raises(ValueError, match='unknown_billing_plan'):
        subscriptions.sync_subscription('sub_managed')
    assert subscriptions.plan_state('EXAMPLE')['active_plan'] == 'starter'


def test_existing_scheduled_update_cannot_be_overwritten(client, stripe, managed_subscription):
    managed_subscription['data']['schedule'] = 'sub_sched_existing'
    for path in ['change-plan', 'cancel-subscription']:
        assert client.post('/billing/' + path, json={'plan_id': 'business'}).json == {'error': 'scheduled_subscription_requires_review'}
    assert all(call.args[0] == 'GET' for call in stripe.call_args_list)


def test_confirmed_setup_proof_survives_cancel_and_new_subscription_generation(client, stripe, managed_subscription):
    subject = managed_subscription
    assert client.post('/billing/change-plan', json={'plan_id': 'business'}).status_code == 200
    confirm_plan(subject, 'business')
    subscriptions.sync_subscription('sub_managed')
    assert client.post('/billing/change-plan', json={'plan_id': 'scale'}).status_code == 200
    subject['data']['status'] = 'canceled'
    subscriptions.sync_subscription('sub_managed')
    assert not tenant_access.activation('EXAMPLE')['active']
    assert billing_management.paid_setup_covers('EXAMPLE', 'business', 'starter')
    assert not billing_management.paid_setup_covers('OTHER', 'business', 'starter')
    assert not billing_management.paid_setup_covers('EXAMPLE', 'scale', 'starter')
    assert not billing_management.paid_setup_covers('EXAMPLE', 'business', 'scale')
    with pytest.raises(ValueError, match='paid_setup_plan_requires_review'):
        subscriptions.select_plan('EXAMPLE', 'scale')
    original_provider = stripe.side_effect
    new_sub, invoice = {}, {}

    def provider(method, path, body=None, **kwargs):
        if method == 'GET' and path == '/v1/tax_rates/txr_test':
            return {'active': True, 'inclusive': False, 'percentage': 20}
        if method == 'POST' and path == '/v1/checkout/sessions':
            return {'id': 'cs_resumed', 'url': 'https://checkout.stripe.com/c/pay/resumed',
                    'expires_at': int(time.time()) + 3600}
        if method == 'GET' and path == '/v1/subscriptions/sub_resumed':
            return copy.deepcopy(new_sub)
        if method == 'GET' and path == '/v1/invoices/in_resumed':
            return copy.deepcopy(invoice)
        return original_provider(method, path, body, **kwargs)

    stripe.side_effect = provider
    response = client.post('/billing/checkout', json={'kind': 'platform', 'plan_id': 'business'})
    assert response.status_code == 200, response.json
    body = stripe.call_args.args[2]
    new_ref = body['metadata[billing_ref]']
    assert new_ref != subject['ref'] and body['metadata[plan_id]'] == 'business'
    new_sub.update(id='sub_resumed', customer='cus_managed', status='active', latest_invoice='in_resumed',
                   metadata={'tenant': 'EXAMPLE', 'kind': 'platform', 'billing_ref': new_ref, 'plan_id': 'business'},
                   items={'data': [{'id': 'si_resumed', 'quantity': 1, 'price': subject['price']('business'),
                                    'current_period_end': int(time.time()) + 86400}]})
    invoice.update(id='in_resumed', currency='gbp', created=int(time.time()), subscription='sub_resumed',
                   total=23880, amount_paid=23880, amount_remaining=0, status='paid',
                   billing_reason='subscription_create', lines={'data': []})
    subscriptions.sync_invoice('in_resumed')
    state = subscriptions.plan_state('EXAMPLE')
    assert state['active_plan'] == state['selected_plan'] == 'business' and state['setup_plan'] == 'starter'
    assert subscriptions._contract('EXAMPLE', 'platform')['ref'] == new_ref
    assert tenant_access.activation('EXAMPLE')['active']
    with subscriptions.connection('EXAMPLE') as db:
        assert db.execute("SELECT count(*) n FROM billing_invoices WHERE tenant='EXAMPLE' AND kind='implementation'").fetchone()['n'] == 0
        assert db.execute('SELECT plan_id FROM billing_plan_choices WHERE ref=?', (subject['ref'],)).fetchone()['plan_id'] == 'starter'
        assert db.execute('SELECT plan_id FROM billing_plan_choices WHERE ref=?', (new_ref,)).fetchone()['plan_id'] == 'business'
