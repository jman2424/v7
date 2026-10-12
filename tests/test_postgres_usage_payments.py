"""Native restricted-role isolation for durable prepaid checkout snapshots."""
import time
from unittest.mock import Mock

import pytest

from service import session_store, subscriptions, usage_payments


@pytest.fixture
def credit_provider(pg_runtime, monkeypatch):
    monkeypatch.setenv('BILLING_PROVIDER','stripe')
    monkeypatch.setenv('STRIPE_API_KEY','native-test-placeholder')
    monkeypatch.setenv('STRIPE_WEBHOOK_SECRET','native-test-placeholder')
    monkeypatch.setenv('STRIPE_TAX_RATE_ID','txr_native')
    provider = Mock(provider='stripe',api_key='native-test-placeholder',webhook_secret='native-test-placeholder')

    def request(method, path, data=None, **kwargs):
        if path == '/v1/tax_rates/txr_native':
            return {'active':True,'inclusive':False,'percentage':20}
        assert method=='POST' and path=='/v1/checkout/sessions'
        assert data['mode']=='payment'
        return {'id':'cs_'+data['metadata[usage_ref]'], 'url':'https://checkout.stripe.com/c/pay/native',
                'expires_at':int(time.time())+3600}

    provider.stripe_request.side_effect = request
    monkeypatch.setattr(subscriptions,'client',lambda:provider)
    return provider


def test_native_credit_checkout_snapshots_are_exact_tenant_scoped(pg_runtime, credit_provider):
    tenant, other = pg_runtime['tenant'], pg_runtime['other']
    first = usage_payments.checkout(tenant,'owner@example.test','gbp_5','native_request_1','https://example.test')
    second = usage_payments.checkout(other,'owner@example.test','gbp_50','native_request_1','https://example.test')
    assert first['reference'] != second['reference']
    assert usage_payments._snapshot(tenant,first['reference'])['credit_pence']==500
    assert usage_payments._snapshot(other,second['reference'])['credit_pence']==5000
    with pytest.raises(ValueError,match='unknown_usage_payment_reference'):
        usage_payments._snapshot(tenant,second['reference'])
    assert len(usage_payments.checkout_requests(tenant))==1
    with session_store.postgres_connection(tenant) as db:
        security = db.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class "
                              "WHERE oid='v7_private.usage_checkout_requests'::regclass").fetchone()
        assert security==(True,True)
        assert db.execute('SELECT count(*) FROM v7_private.usage_checkout_requests WHERE tenant=%s',(other,)).fetchone()[0]==0
        assert not db.execute("SELECT has_table_privilege(current_user,'v7_private.usage_checkout_requests','TRUNCATE')").fetchone()[0]


def test_native_credit_checkout_scope_cannot_insert_another_tenant(pg_runtime, credit_provider):
    tenant, other = pg_runtime['tenant'], pg_runtime['other']
    usage_payments.checkout(tenant,'owner@example.test','gbp_5','native_request_1','https://example.test')
    with pytest.raises(RuntimeError,match='database operation failed'):
        with session_store.postgres_connection(tenant) as db:
            db.execute("INSERT INTO v7_private.usage_checkout_requests (tenant,reference,request_id,pack_id,"
                       "credit_pence,subtotal_pence,tax_pence,total_pence,vat_percent,tax_rate,livemode,created) "
                       "VALUES(%s,%s,'forged_request_1','gbp_5',500,500,100,600,20,'txr_native',0,1)",
                       (other,'a'*48))
    assert usage_payments.checkout_requests(other)==[]
