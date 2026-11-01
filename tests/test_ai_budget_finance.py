"""Exact financial projections and published prices, with synthetic funds only."""
from decimal import Decimal
from datetime import date
import pytest
from tests.test_subscriptions import identity
from service import usage_wallet, usage_currency
from service.ai_budget_rates import public_rates


def rate(monkeypatch):
    data={'rate':.75,'date':date.today().isoformat(),'stale':False,'source':'synthetic'}
    monkeypatch.setattr(usage_currency,'gbp_rate',lambda:dict(data))
    monkeypatch.setattr(usage_currency,'cached_gbp_rate',lambda:dict(data))
    monkeypatch.setenv('V7_USAGE_MARKUP_PERCENT','20')
    return data


def test_public_service_prices_match_the_billing_snapshot_without_exposing_margin(monkeypatch):
    rate(monkeypatch)
    data=public_rates()
    row=next(r for r in data['models'] if r['model']=='gpt-4o-mini')
    assert Decimal(row['input'])==Decimal('0.135000')
    assert Decimal(row['output'])==Decimal('0.540000')
    assert 'markup' not in str(data) and 'provider_cost' not in str(data)
    assert all(isinstance(value,str) for key,value in row.items() if key in {'input','cached','output'})


def test_unverified_exchange_rate_cannot_publish_zero_prices(monkeypatch):
    values=rate(monkeypatch)
    values['stale']=True
    assert public_rates()=={'available':False,'currency':'GBP','models':[],'audio':[]}


def test_only_platform_can_see_financial_observations_and_unknown_fees_stay_unknown(client,monkeypatch):
    rate(monkeypatch)
    usage_wallet.apply_payment('EXAMPLE','funding','pi_financetest',2500,2500)
    held=usage_wallet.reserve_usage('EXAMPLE',100*usage_wallet.NANO_PER_PENNY,{'requested_model':'gpt-4o-mini'})
    usage_wallet.settle_usage(held,100*usage_wallet.NANO_PER_PENNY)
    identity(client,'business_owner')
    assert client.get('/billing/ai-budget/provider-funding').status_code==403
    identity(client)
    response=client.get('/billing/ai-budget/provider-funding')
    assert response.status_code==200,response.json
    body=response.json
    assert body['provider_balance'] is None
    ops=body['operations']
    assert ops['gross_payments_pence']==2500
    assert ops['observed_stripe_fees_pence'] is None and ops['net_accounting_profit_gbp'] is None
    assert ops['climate_expenditure_pence'] is None and not ops['reserve_is_verified']
    assert 'payment_costs_incomplete' in ops['warnings']
    assert Decimal(ops['prepaid_liability_gbp'])==Decimal('24.1')


@pytest.mark.parametrize('payload',[{'stripe_percent_bps':-1},{'financial_review_completed':'true'},{'target_margin_bps':10000},{'usage_markup':100},{'reserve_target_pence':True}])
def test_cost_configuration_cannot_change_customer_pricing_or_accept_invalid_units(client,payload):
    identity(client)
    response=client.post('/billing/ai-budget/provider-funding/settings',json=payload)
    assert response.status_code==400
    assert response.json=={'error':'invalid_provider_funding_settings'}
