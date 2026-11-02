"""Official read-only monitoring and funding outages, with no live API requests."""
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
import httpx
from openai import RateLimitError
import pytest

from service import ai_provider_funding as funding, ai_budget_store as store, api_usage
from tests import test_usage_wallet

ledger=test_usage_wallet.ledger


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(funding,'_platform_tenant',lambda:'ALPHA')
    funding._health_cache.clear()


def quota(code='credit_balance_exhausted'):
    response=httpx.Response(429,request=httpx.Request('POST','https://api.openai.com/v1/responses'))
    return RateLimitError('synthetic',response=response,body={'error':{'code':code,'message':'PRIVATE NOT STORED'}})


def test_official_admin_key_missing_is_unavailable_not_zero(ledger,monkeypatch):
    monkeypatch.delenv('OPENAI_ADMIN_KEY',raising=False)
    with pytest.raises(ValueError,match='not_configured'):
        funding._get('/v1/organization/costs')
    with pytest.raises(ValueError,match='unsupported'):
        funding._get('/v1/organisation/billing/balance')


@pytest.mark.parametrize('code',sorted(funding.KNOWN_BILLING_ERRORS))
def test_explicit_billing_rejections_release_usage_and_stop_storm(ledger,code):
    error=quota(code)
    assert api_usage.rejected_before_inference(error)
    funding.record_error(error,'ALPHA')
    assert not funding.allow_request('ALPHA')
    assert not funding.allow_request('BETA')  # Provider circuit is organisation-wide.
    with store.connection('ALPHA',write=True) as db:
        db.execute('UPDATE ai_provider_health SET retry_after=0 WHERE id=1')
    funding._health_cache.clear()
    with ThreadPoolExecutor(max_workers=5) as pool:
        assert sum(pool.map(lambda _:funding.allow_request('ALPHA'),range(10)))==1
    funding.record_success('ALPHA')
    assert funding.allow_request('ALPHA')
    assert 'PRIVATE' not in str(funding.health('ALPHA'))


def test_rate_limit_or_unknown_error_not_mislabelled_as_funding(ledger):
    assert funding.classify(quota('rate_limit_exceeded')) is None
    assert not api_usage.rejected_before_inference(quota('rate_limit_exceeded'))
    assert funding.classify(ValueError('credit_balance_exhausted')) is None


def test_older_inflight_success_cannot_clear_a_new_funding_failure(ledger):
    import time
    started=time.time()-10
    funding.record_error(quota(),'ALPHA')
    funding.record_success('ALPHA',started_at=started)
    assert not funding.allow_request('ALPHA')


def test_costs_are_decimal_delayed_and_failed_pagination_never_partially_writes(ledger,monkeypatch):
    end=datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)
    start=int((end-timedelta(days=1)).timestamp())
    row={'start_time':start,'end_time':int(end.timestamp()),'results':[{'amount':{'currency':'usd','value':'0.1000000001'},'project_id':''}]}
    monkeypatch.setattr(funding,'_get',lambda path,params=None:{'data':[row],'has_more':True,'next_page':'repeated'})
    with pytest.raises(ValueError,match='invalid'):
        funding.sync_costs(days=1)
    with store.connection('ALPHA') as db:
        assert db.execute('SELECT COUNT(*) n FROM ai_provider_cost_snapshots').fetchone()['n']==0
    monkeypatch.setattr(funding,'_get',lambda path,params=None:{'data':[row],'has_more':False})
    assert funding.sync_costs(days=1)['balance_available'] is False
    funding.sync_costs(days=1)
    with store.connection('ALPHA') as db:
        values=list(db.execute('SELECT amount_decimal FROM ai_provider_cost_snapshots'))
    assert len(values)==1 and Decimal(values[0]['amount_decimal'])==Decimal('0.1000000001')


@pytest.mark.parametrize('value',['NaN','Infinity','bad','1000000001'])
def test_invalid_official_costs_rejected(ledger,monkeypatch,value):
    now=datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)
    monkeypatch.setattr(funding,'_get',lambda *args:{'data':[{'start_time':int((now-timedelta(days=1)).timestamp()),'end_time':int(now.timestamp()),'results':[{'amount':{'currency':'usd','value':value}}]}],'has_more':False})
    with pytest.raises(ValueError):
        funding.sync_costs(days=1)


def test_unknown_fee_assumptions_do_not_claim_profitability():
    result=funding.break_even(funding.DEFAULTS,markup=0)
    assert not result['validated'] and 'stripe_fixed_pence' in result['missing']


def test_small_recharge_fixed_fees_and_vat_are_in_break_even():
    policy={**funding.DEFAULTS,'stripe_percent_bps':150,'stripe_fixed_pence':20,'climate_bps':100,
        'fx_cost_bps':100,'refund_dispute_risk_bps':100,'infrastructure_bps':100,'target_margin_bps':2000,
        'financial_review_completed':True}
    result=funding.break_even(policy,markup=0)
    assert result['validated'] and not result['profitable']
    assert Decimal(result['processing_fee_pence'])==28
    assert Decimal(result['climate_pence'])==5
    assert Decimal(result['gross_contribution_pence'])==-48
    assert Decimal(result['minimum_markup_for_target_percent'])>40
    taxed=funding.break_even(policy,markup=0,vat_percent=20)
    assert Decimal(taxed['net_revenue_pence'])<Decimal(result['net_revenue_pence'])
    assert Decimal(taxed['gross_contribution_pence'])<Decimal(result['gross_contribution_pence'])


def test_spend_limits_are_allowlisted_and_invalid_limits_unavailable(ledger,monkeypatch):
    monkeypatch.setattr(funding,'_get',lambda *args:{'object':'organization.spend_limit','currency':'USD','interval':'month','threshold_amount':10000,'enforcement':{'status':'enforcing'}})
    assert funding.sync_limits()['scopes']>=1
    with store.connection('ALPHA') as db:
        assert 'threshold_cents_usd' in db.execute('SELECT value FROM ai_provider_limit_snapshots WHERE scope=?',('organisation',)).fetchone()['value']
    monkeypatch.setattr(funding,'_get',lambda *args:{'currency':'GBP','threshold_amount':0})
    funding.sync_limits()
    with store.connection('ALPHA') as db:
        assert '"available": false' in db.execute('SELECT value FROM ai_provider_limit_snapshots WHERE scope=?',('organisation',)).fetchone()['value']
