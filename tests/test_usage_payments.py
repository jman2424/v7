"""Credits require exact canonical Stripe payments, never a redirect or payload."""
from copy import deepcopy
from datetime import date
import json
import time

import pytest

from connectors.billing import BillingClient
from service import subscriptions, usage_wallet
from service import usage_payments
from tests.test_subscriptions import identity, signature


@pytest.fixture
def paid_stripe(monkeypatch):
    monkeypatch.setenv('V7_VAT_REGISTERED', 'true')
    monkeypatch.setenv('BILLING_PROVIDER', 'stripe')
    monkeypatch.setenv('STRIPE_API_KEY', 'test-api-key-not-real')
    monkeypatch.setenv('STRIPE_WEBHOOK_SECRET', 'test-webhook-secret-not-real')
    monkeypatch.setenv('STRIPE_TAX_RATE_ID', 'txr_test')
    state = {'objects': {}, 'requests': [], 'creates': 0}

    def request(self, method, path, data=None, **kwargs):
        state['requests'].append((method, path, deepcopy(data), kwargs))
        if path == '/v1/tax_rates/txr_test':
            return {'id':'txr_test', 'active':True, 'inclusive':False, 'percentage':20}
        if method == 'POST' and path == '/v1/checkout/sessions':
            state['creates'] += 1
            metadata = {key: data['metadata['+key+']'] for key in ['tenant','kind','usage_ref','usage_version','pack_id']}
            value = data['line_items[0][price_data][unit_amount]']
            percentage = 20 if data.get('line_items[0][tax_rates][0]') else 0
            tax = value * percentage // 100
            total = value + tax
            common = {'currency':'gbp', 'livemode':False}
            checkout = {**common, 'id':'cs_credit', 'metadata':metadata, 'client_reference_id':metadata['tenant'],
                        'mode':'payment', 'subscription':None, 'status':'complete', 'payment_status':'paid',
                        'amount_subtotal':value, 'amount_total':total,
                        'total_details':{'amount_tax':tax,'amount_discount':0,'amount_shipping':0},
                        'invoice_creation':{'enabled':True}, 'payment_intent':'pi_credit', 'invoice':'in_credit',
                        'url':'https://checkout.stripe.com/c/pay/credit', 'expires_at':int(time.time())+3600}
            line = {'data':[{'quantity':1, 'currency':'gbp', 'amount_subtotal':value,'amount_total':total,
                             'amount_tax':tax,'price':{'currency':'gbp','type':'one_time','recurring':None,
                                                              'tax_behavior':'exclusive','unit_amount':value}}], 'has_more':False}
            payment = {**common,'id':'pi_credit','metadata':metadata,'status':'succeeded','amount':total,
                       'amount_received':total,'latest_charge':'ch_credit'}
            charge = {**common,'id':'ch_credit','payment_intent':'pi_credit','paid':True,'captured':True,'status':'succeeded',
                      'amount':total,'amount_captured':total,'amount_refunded':0,'disputed':False,
                      'receipt_url':'https://pay.stripe.com/receipts/test'}
            invoice = {**common,'id':'in_credit','metadata':metadata,'status':'paid','total':total,
                       'total_excluding_tax':value,'amount_paid':total,'amount_remaining':0,
                       'parent':None,'hosted_invoice_url':'https://invoice.stripe.com/i/credit'}
            state['objects'].update({'/v1/checkout/sessions/cs_credit':checkout,
                '/v1/checkout/sessions/cs_credit/line_items':line, '/v1/payment_intents/pi_credit':payment,
                '/v1/charges/ch_credit':charge, '/v1/invoices/in_credit':invoice,
                '/v1/disputes?charge=ch_credit&limit=100':{'data':[],'has_more':False}})
            return deepcopy(checkout)
        assert method == 'GET', (method,path)
        assert path in state['objects'], path
        return deepcopy(state['objects'][path])
    monkeypatch.setattr(BillingClient, 'stripe_request', request)
    return state


def create(client, state, **overrides):
    identity(client, 'business_owner')
    response = client.post('/billing/usage-credit/checkout', json={'pack_id':'gbp_5','request_id':'request_test_123', **overrides})
    assert response.status_code == 200, response.json
    return response.json


def test_unregistered_credit_is_face_value_and_verified_without_tax_rate(client, paid_stripe, monkeypatch):
    monkeypatch.setenv('V7_VAT_REGISTERED', 'false')
    monkeypatch.delenv('STRIPE_TAX_RATE_ID')
    create(client, paid_stripe)
    data = next(row[2] for row in paid_stripe['requests'] if row[0]=='POST')
    assert not any('tax_rates' in key for key in data)
    assert data['automatic_tax[enabled]'] == 'false'
    report = client.get('/billing/usage-credit').json
    assert report['packs'][0]['total_pence'] == report['packs'][0]['credit_pence'] == 500
    assert report['vat_percent'] == report['packs'][0]['tax_pence'] == 0
    assert send(client, paid_stripe, signed=False).status_code == 403
    assert usage_wallet.report('EXAMPLE')['balance_pence'] == 0
    assert send(client, paid_stripe).status_code == 200
    assert send(client, paid_stripe).status_code == 200
    assert usage_wallet.report('EXAMPLE')['balance_pence'] == 500
    assert not any('/tax_rates/' in row[1] for row in paid_stripe['requests'])


def test_old_taxed_payment_keeps_its_verified_snapshot_after_registration_change(client, paid_stripe, monkeypatch):
    create(client, paid_stripe)
    monkeypatch.setenv('V7_VAT_REGISTERED','false')
    assert send(client, paid_stripe).status_code == 200
    assert usage_wallet.report('EXAMPLE')['balance_pence'] == 500
    with subscriptions.connection('EXAMPLE') as db:
        row=db.execute('SELECT total_pence,vat_percent FROM usage_checkout_requests WHERE tenant=?',('EXAMPLE',)).fetchone()
    assert row['total_pence']==600 and row['vat_percent']==20


def test_production_rejects_test_checkout_before_any_stripe_side_effect(client, paid_stripe, monkeypatch):
    identity(client, 'business_owner')
    monkeypatch.setattr(usage_payments, '_production', lambda: True)
    response = client.post('/billing/usage-credit/checkout', json={
        'pack_id':'gbp_5', 'request_id':'production_test_123'})
    assert response.status_code == 400
    assert response.json['error'] == 'usage_live_payments_required'
    assert paid_stripe['requests'] == []
    assert not client.get('/billing/usage-credit').json['configured']
    assert usage_wallet.report('EXAMPLE')['balance_pence'] == 0


def test_test_payment_created_before_production_cannot_credit_production_wallet(client, paid_stripe, monkeypatch):
    create(client, paid_stripe)
    monkeypatch.setattr(usage_payments, '_production', lambda: True)
    assert send(client, paid_stripe).status_code == 503
    assert usage_wallet.report('EXAMPLE')['balance_pence'] == 0


def test_production_usage_checkout_readiness_requires_live_credentials(client, paid_stripe, monkeypatch):
    monkeypatch.setattr(usage_payments, '_production', lambda: True)
    assert not usage_payments.payments_ready()
    monkeypatch.setenv('STRIPE_API_KEY', 'sk_live_synthetic_not_a_real_key')
    assert usage_payments.payments_ready()


def send(client, state, kind='checkout.session.completed', obj=None, signed=True):
    if obj is None:
        obj = state['objects']['/v1/checkout/sessions/cs_credit']
    body = json.dumps({'id':'evt_credit','type':kind,'data':{'object':deepcopy(obj)}}).encode()
    return client.post('/billing/stripe/webhook', data=body, content_type='application/json',
                       headers={'Stripe-Signature':signature(body) if signed else 'invalid'})


def test_credit_purchase_is_server_priced_one_time_and_does_not_grant_credit_on_return(client, paid_stripe):
    result = create(client, paid_stripe, amount_pence=1, tenant='OTHER', automatic_recharge=True)
    data = next(row[2] for row in paid_stripe['requests'] if row[0]=='POST')
    assert data['mode'] == 'payment'
    assert data['line_items[0][price_data][unit_amount]'] == 500
    assert data['line_items[0][tax_rates][0]'] == 'txr_test'
    assert not any('recurring' in key or 'setup_future_usage' in key for key in data)
    assert data['metadata[tenant]'] == 'EXAMPLE'
    assert 'customer_email' not in data
    assert data['payment_intent_data[metadata][usage_ref]'] == result['reference']
    assert data['invoice_creation[invoice_data][metadata][usage_ref]'] == result['reference']
    report = client.get('/billing/usage-credit?credit=paid').json
    assert report['wallet']['balance_pence'] == 0
    assert report['packs'][0] == {'id':'gbp_5','credit_pence':500,'subtotal_pence':500,'tax_pence':100,
                                 'total_pence':600,'currency':'GBP','vat_percent':20}
    assert report['policy']['automatic_recharge'] is False
    assert report['checkout_requests'][0]['request_id'] == 'request_test_123'


def test_owner_credit_checkout_reuses_exact_company_customer(client, paid_stripe):
    contract = subscriptions._contract('EXAMPLE','platform')
    with subscriptions.connection('EXAMPLE') as db:
        db.execute('UPDATE billing_contracts SET customer=? WHERE tenant=? AND ref=?',
                   ('cus_business','EXAMPLE',contract['ref']))
    create(client, paid_stripe)
    data = next(row[2] for row in paid_stripe['requests'] if row[0]=='POST')
    assert data['customer'] == 'cus_business'
    assert 'customer_creation' not in data
    assert 'customer_email' not in data


def test_platform_operator_email_is_not_sent_to_company_checkout_or_report(client, paid_stripe):
    identity(client,'platform_admin')
    response = client.post('/billing/usage-credit/checkout',json={'pack_id':'gbp_5','request_id':'admin_request_123'})
    assert response.status_code == 200
    data = next(row[2] for row in paid_stripe['requests'] if row[0]=='POST')
    assert data['customer_creation'] == 'always'
    assert 'customer_email' not in data
    assert send(client, paid_stripe).status_code == 200
    identity(client,'business_owner')
    report = client.get('/billing/usage-credit').json
    assert 'billing-test@example.test' not in json.dumps(report)
    assert any(row['receipt_url']=='https://invoice.stripe.com/i/credit' for row in report['wallet']['transactions'])


def test_idempotent_checkout_reuses_snapshot_and_rejects_changed_pack(client, paid_stripe):
    first = create(client, paid_stripe)
    repeated = create(client, paid_stripe)
    assert repeated['reference'] == first['reference']
    assert repeated['checkout_id'] == first['checkout_id']
    assert repeated['status'] == 'processing'
    assert repeated['url'] is None
    assert paid_stripe['creates'] == 1
    response = client.post('/billing/usage-credit/checkout', json={'pack_id':'gbp_20','request_id':'request_test_123'})
    assert response.status_code == 400
    assert response.json['error'] == 'usage_request_mismatch'
    assert paid_stripe['creates'] == 1


def test_signed_canonical_payment_credits_once_by_actual_payment(client, paid_stripe):
    create(client, paid_stripe)
    assert send(client, paid_stripe, signed=False).status_code == 403
    assert client.get('/billing/usage-credit').json['wallet']['balance_pence'] == 0
    for kind in ['checkout.session.completed','checkout.session.async_payment_succeeded','invoice.paid']:
        obj = paid_stripe['objects']['/v1/invoices/in_credit'] if kind=='invoice.paid' else None
        assert send(client, paid_stripe, kind, obj).status_code == 200
    report = client.get('/billing/usage-credit').json
    assert report['wallet']['balance_pence'] == 500
    assert sum(row['kind']=='topup' for row in report['wallet']['transactions']) == 1
    assert report['checkout_requests'][0]['status'] == 'paid'
    assert report['pending_checkouts'] == []
    assert create(client, paid_stripe)['url'] is None


@pytest.mark.parametrize('path,field,value', [
    ('/v1/checkout/sessions/cs_credit','amount_total',1),
    ('/v1/checkout/sessions/cs_credit','amount_subtotal',1),
    ('/v1/checkout/sessions/cs_credit','currency','usd'),
    ('/v1/checkout/sessions/cs_credit','livemode',True),
    ('/v1/checkout/sessions/cs_credit','mode','subscription'),
    ('/v1/payment_intents/pi_credit','amount_received',1),
    ('/v1/payment_intents/pi_credit','status','processing'),
    ('/v1/charges/ch_credit','amount_captured',1),
    ('/v1/charges/ch_credit','payment_intent','pi_another'),
    ('/v1/invoices/in_credit','amount_paid',1),
    ('/v1/invoices/in_credit','total_excluding_tax',1),
    ('/v1/invoices/in_credit','status','open'),
])
def test_canonical_mismatches_never_credit(client, paid_stripe, path, field, value):
    create(client, paid_stripe)
    paid_stripe['objects'][path][field] = value
    assert send(client, paid_stripe).status_code == 503
    assert client.get('/billing/usage-credit').json['wallet']['balance_pence'] == 0


@pytest.mark.parametrize('field,value', [('tenant','OTHER'),('tenant','../EXAMPLE'),('usage_ref','f'*48),
                                       ('pack_id','gbp_50'),('usage_version','forged')])
def test_canonical_metadata_cannot_redirect_or_increase_credit(client, paid_stripe, field, value):
    create(client, paid_stripe)
    paid_stripe['objects']['/v1/payment_intents/pi_credit']['metadata'] = {
        **paid_stripe['objects']['/v1/payment_intents/pi_credit']['metadata'],field:value}
    assert send(client, paid_stripe).status_code == 503
    assert client.get('/billing/usage-credit').json['wallet']['balance_pence'] == 0


def test_unpaid_completion_waits_for_asynchronous_paid_event(client, paid_stripe):
    create(client, paid_stripe)
    checkout = paid_stripe['objects']['/v1/checkout/sessions/cs_credit']
    checkout['payment_status'] = 'unpaid'
    assert send(client, paid_stripe).status_code == 200
    assert client.get('/billing/usage-credit').json['wallet']['balance_pence'] == 0
    checkout['payment_status'] = 'paid'
    assert send(client, paid_stripe, 'checkout.session.async_payment_succeeded').status_code == 200
    assert client.get('/billing/usage-credit').json['wallet']['balance_pence'] == 500


def test_refund_before_paid_webhook_and_duplicate_partial_refunds_are_cumulative(client, paid_stripe):
    create(client, paid_stripe)
    charge = paid_stripe['objects']['/v1/charges/ch_credit']
    charge['amount_refunded'] = 300
    for kind, obj in [('charge.refunded',charge),('checkout.session.completed',None),('charge.refunded',charge)]:
        assert send(client, paid_stripe, kind, obj).status_code == 200
    assert client.get('/billing/usage-credit').json['wallet']['balance_pence'] == 250
    charge['amount_refunded'] = 600
    assert send(client, paid_stripe,'charge.refunded',charge).status_code == 200
    assert client.get('/billing/usage-credit').json['wallet']['balance_pence'] == 0


def test_dispute_hold_and_won_restoration_use_current_state_not_event_order(client, paid_stripe):
    create(client, paid_stripe)
    assert send(client, paid_stripe).status_code == 200
    charge = paid_stripe['objects']['/v1/charges/ch_credit']
    charge['disputed'] = True
    dispute = {'id':'dp_credit','charge':'ch_credit','payment_intent':'pi_credit','currency':'gbp',
               'livemode':False,'status':'under_review'}
    paid_stripe['objects']['/v1/disputes/dp_credit'] = dispute
    paid_stripe['objects']['/v1/disputes?charge=ch_credit&limit=100']['data'] = [dispute]
    assert send(client, paid_stripe,'charge.dispute.created',dispute).status_code == 200
    held = client.get('/billing/usage-credit').json['wallet']
    assert held['balance_pence'] == 0
    assert held['paused'] is True
    dispute['status'] = 'won'
    for kind in ['charge.dispute.closed','charge.dispute.created','charge.dispute.closed']:
        assert send(client, paid_stripe,kind,dispute).status_code == 200
    assert client.get('/billing/usage-credit').json['wallet']['balance_pence'] == 500


def test_stale_undisputed_read_cannot_restore_after_newer_dispute_hold(client, paid_stripe, monkeypatch):
    create(client, paid_stripe)
    original = usage_wallet.apply_payment
    interrupted = False

    def interleave(*args, **kwargs):
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            charge = paid_stripe['objects']['/v1/charges/ch_credit']
            charge['disputed'] = True
            dispute = {'id':'dp_race','charge':'ch_credit','payment_intent':'pi_credit',
                       'currency':'gbp','livemode':False,'status':'under_review'}
            paid_stripe['objects']['/v1/disputes/dp_race'] = dispute
            paid_stripe['objects']['/v1/disputes?charge=ch_credit&limit=100']['data'] = [dispute]
            assert send(client, paid_stripe, 'charge.dispute.created', dispute).status_code == 200
            assert client.get('/billing/usage-credit').json['wallet']['balance_pence'] == 0
            # Resume the older paid callback with its already-read empty list.
            assert kwargs['disputed'] is False
            assert kwargs['dispute_states'] == {}
        return original(*args, **kwargs)

    monkeypatch.setattr(usage_wallet, 'apply_payment', interleave)
    assert send(client, paid_stripe).status_code == 200
    result = client.get('/billing/usage-credit').json['wallet']
    assert result['balance_pence'] == 0
    assert result['paused'] is True


@pytest.mark.parametrize('resolved_status', ['won','warning_closed'])
def test_direct_dispute_proof_handles_lagging_list_and_resolved_inquiries(client, paid_stripe, resolved_status):
    create(client, paid_stripe)
    charge = paid_stripe['objects']['/v1/charges/ch_credit']
    charge['disputed'] = True
    dispute = {'id':'dp_lag','charge':'ch_credit','payment_intent':'pi_credit',
               'currency':'gbp','livemode':False,'status':'under_review'}
    paid_stripe['objects']['/v1/disputes/dp_lag'] = dispute
    # The list deliberately never catches up. The exact canonical object still
    # supplies durable proof for that dispute, avoiding an unidentified hold.
    assert send(client, paid_stripe,'charge.dispute.created',dispute).status_code == 200
    assert client.get('/billing/usage-credit').json['wallet']['balance_pence'] == 0
    dispute['status'] = resolved_status
    assert send(client, paid_stripe,'charge.dispute.closed',dispute).status_code == 200
    assert client.get('/billing/usage-credit').json['wallet']['balance_pence'] == 500


def test_failed_async_checkout_is_terminal_but_later_canonical_paid_event_wins(client, paid_stripe):
    first = create(client, paid_stripe)
    checkout = paid_stripe['objects']['/v1/checkout/sessions/cs_credit']
    payment = paid_stripe['objects']['/v1/payment_intents/pi_credit']
    checkout['payment_status'] = 'unpaid'
    payment['status'] = 'requires_payment_method'
    assert send(client, paid_stripe, 'checkout.session.async_payment_failed').status_code == 200
    identity(client, 'business_owner')
    report = client.get('/billing/usage-credit').json
    assert report['checkout_requests'][0]['status'] == 'failed'
    assert report['pending_checkouts'] == []
    repeated = create(client, paid_stripe)
    assert repeated['reference'] == first['reference']
    assert repeated['url'] is None
    assert repeated['status'] == 'failed'
    assert paid_stripe['creates'] == 1
    checkout['payment_status'] = 'paid'
    payment['status'] = 'succeeded'
    assert send(client, paid_stripe, 'checkout.session.async_payment_succeeded').status_code == 200
    identity(client, 'business_owner')
    report = client.get('/billing/usage-credit').json
    assert report['checkout_requests'][0]['status'] == 'paid'
    assert report['wallet']['balance_pence'] == 500


def test_async_failed_payload_without_canonical_failure_cannot_discard_processing_payment(client, paid_stripe):
    create(client, paid_stripe)
    paid_stripe['objects']['/v1/checkout/sessions/cs_credit']['payment_status'] = 'unpaid'
    paid_stripe['objects']['/v1/payment_intents/pi_credit']['status'] = 'processing'
    assert send(client, paid_stripe, 'checkout.session.async_payment_failed').status_code == 200
    assert client.get('/billing/usage-credit').json['checkout_requests'][0]['status'] == 'pending'


def test_checkout_retry_confirms_expiration_instead_of_reusing_a_dead_url(client, paid_stripe):
    create(client, paid_stripe)
    checkout = paid_stripe['objects']['/v1/checkout/sessions/cs_credit']
    checkout.update(status='expired', payment_status='unpaid')
    repeated = create(client, paid_stripe)
    assert repeated['status'] == 'expired'
    assert repeated['url'] is None
    assert client.get('/billing/usage-credit').json['pending_checkouts'] == []
    assert paid_stripe['creates'] == 1


def test_credit_checkout_keeps_csrf_enforced(client, paid_stripe):
    identity(client, 'business_owner')
    response = client.post('/billing/usage-credit/checkout',json={'pack_id':'gbp_5','request_id':'csrf_test_123'},
                           headers={'X-CSRF-Token':'wrong'})
    assert response.status_code == 403
    assert paid_stripe['requests'] == []


def test_permissions_tenant_scope_and_audited_adjustment_idempotency(client, paid_stripe):
    assert client.get('/billing/usage-credit').status_code == 401
    identity(client,'business_owner')
    assert client.get('/billing/usage-credit?tenant=OTHER').status_code == 403
    assert client.get('/billing/usage-credit/companies').status_code == 403
    assert client.post('/billing/usage-credit/adjust',json={}).status_code == 403
    identity(client,'business_staff')
    assert client.get('/billing/usage-credit').status_code == 403
    identity(client,'platform_admin')
    body = {'amount_pence':500,'reason':'Onboarding credit adjustment','request_id':'adjust_test_123'}
    first = client.post('/billing/usage-credit/adjust',json=body)
    assert first.status_code == 200, first.json
    assert first.json['duplicate'] is False
    assert client.post('/billing/usage-credit/adjust',json=body).json['duplicate'] is True
    assert client.post('/billing/usage-credit/adjust',json={**body,'amount_pence':501}).status_code == 400
    assert client.get('/billing/usage-credit').json['wallet']['balance_pence'] == 500
    report = client.get('/billing/usage-credit/companies').json
    assert report['companies'][0]['wallet']['balance_pence'] == 500
    assert client.get('/billing/usage-credit?page=-1').status_code == 400


def test_unconfirmed_review_is_operator_only_tenant_scoped_and_explicit(client,paid_stripe,monkeypatch):
    monkeypatch.setattr(usage_wallet.usage_currency,'gbp_rate',lambda:{
        'rate':1,'date':date.today().isoformat(),'stale':False,'source':'synthetic'})
    identity(client,'platform_admin')
    usage_wallet.adjust('EXAMPLE',500,'Test funding','operator','review-funding')
    held = usage_wallet.reserve_usage('EXAMPLE',100_000)
    usage_wallet.settle_usage(held,None)
    body = {'reference':held.ref,'reason':'Setup timeout review','platform_absorbs_provider_cost':True}
    assert client.get('/billing/usage-credit').json['usage_reviews'][0]['reference']==held.ref
    identity(client,'business_owner')
    assert client.get('/billing/usage-credit').json['usage_reviews']==[]
    assert client.post('/billing/usage-credit/waive-unconfirmed',json=body).status_code==403
    identity(client,'platform_admin')
    assert client.post('/billing/usage-credit/waive-unconfirmed?tenant=OTHER',json=body).status_code in {400,404}
    assert client.post('/billing/usage-credit/waive-unconfirmed',json={**body,'platform_absorbs_provider_cost':'true'}).status_code==400
    assert client.post('/billing/usage-credit/waive-unconfirmed',json=body,headers={'X-CSRF-Token':'wrong'}).status_code==403
    result = client.post('/billing/usage-credit/waive-unconfirmed',json=body)
    assert result.status_code==200, result.json
    assert result.json['duplicate'] is False and result.json['wallet']['available_pence']==500
    assert not result.json['wallet']['paused']
    assert client.post('/billing/usage-credit/waive-unconfirmed',json=body).json['duplicate'] is True
    assert client.get('/billing/usage-credit').json['usage_reviews']==[]


@pytest.mark.parametrize('body', [{'amount_pence':True,'reason':'Valid reason','request_id':'adjust_123'},
                                 {'amount_pence':1,'reason':'','request_id':'adjust_123'},
                                 {'amount_pence':1,'reason':'Valid reason','request_id':'../evil'}])
def test_invalid_platform_adjustments_do_not_move_money(client, paid_stripe, body):
    identity(client)
    assert client.post('/billing/usage-credit/adjust',json=body).status_code == 400
    assert client.get('/billing/usage-credit').json['wallet']['balance_pence'] == 0


def test_new_legacy_usage_approval_cannot_double_bill_wallet_usage(client, paid_stripe):
    identity(client)
    response = client.post('/billing/api-charge',json={'month':'2020-01','amount_pence':500})
    assert response.status_code == 400
    assert response.json['error'] == 'prepaid_usage_requires_topup'
