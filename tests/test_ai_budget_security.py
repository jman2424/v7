"""Real authenticated routes enforce permissions, tenant scope and safe errors."""
import pytest
from tests.test_subscriptions import identity
from service import ai_budget as budget, ai_budget_payments as payments


@pytest.mark.parametrize('path',['','/preferences','/checkout','/automatic-recharge/authorise','/automatic-recharge/confirm','/automatic-recharge/disable','/automatic-recharge/resolve','/notifications/seen','/provider-funding','/provider-funding/settings','/provider-funding/sync'])
def test_unauthenticated_routes_are_closed(client,path):
    response=client.get('/billing/ai-budget'+path) if path in {'','/provider-funding'} else client.post('/billing/ai-budget'+path,json={})
    assert response.status_code in {401,403}


@pytest.mark.parametrize('path',['','/preferences','/automatic-recharge/disable'])
def test_owners_cannot_choose_another_tenant(client,path):
    identity(client,'business_owner')
    response=client.get('/billing/ai-budget?tenant=OTHER') if not path else client.post('/billing/ai-budget'+path+'?tenant=OTHER',json={})
    assert response.status_code==403


def test_cost_view_staff_cannot_authorise_payments_or_read_provider_finances(client):
    identity(client,'business_staff')
    assert client.post('/billing/ai-budget/automatic-recharge/authorise',json={}).status_code==403
    assert client.get('/billing/ai-budget/provider-funding').status_code==403
    assert client.post('/billing/ai-budget/provider-funding/settings',json={}).status_code==403


@pytest.mark.parametrize('payload',[{}, {'accepted_terms':False,'cap_pence':2500}, {'accepted_terms':True,'cap_pence':True},
    {'accepted_terms':True,'cap_pence':999999}, {'accepted_terms':True,'cap_pence':2500,'amount_pence':1}])
def test_json_cannot_manipulate_amount_or_consent(client,payload):
    identity(client,'business_owner')
    response=client.post('/billing/ai-budget/automatic-recharge/authorise',json=payload)
    assert response.status_code==400
    assert response.json=={'error':'budget_authorisation_required'}


def test_raw_provider_errors_do_not_escape(client,monkeypatch):
    identity(client,'business_owner')
    def fail(*args,**kwargs):
        raise ValueError('PRIVATE token secret /srv/database CUSTOMER_MESSAGE')
    monkeypatch.setattr(payments,'confirm_authorisation',fail)
    result=client.post('/billing/ai-budget/automatic-recharge/confirm',json={})
    assert result.status_code==409
    assert result.json=={'error':'budget_request_unavailable'}


def test_approved_business_gate_cannot_be_bypassed_by_new_checkout(client,monkeypatch):
    from service.business_applications import ApplicationError
    identity(client,'business_owner')
    def denied(tenant):
        raise ApplicationError('business_approval_required',403)
    monkeypatch.setattr('service.business_applications.require_eligible',denied)
    result=client.post('/billing/ai-budget/checkout',json={'pack_id':'gbp_25','request_id':'approved_only_test'})
    assert result.status_code==403 and result.json['error']=='business_approval_required'


def test_unknown_notification_id_is_tenant_scoped_not_found(client):
    identity(client,'business_owner')
    result=client.post('/billing/ai-budget/notifications/seen',json={'id':'a'*32})
    assert result.status_code==404


@pytest.mark.parametrize('metadata',[{'tenant':'../ALPHA','budget_authorisation':'a'*48}, {'tenant':'ALPHA','budget_authorisation':'../private'}])
def test_provider_metadata_cannot_be_a_storage_path(metadata):
    with pytest.raises(budget.BudgetError):
        payments._setup_row({**metadata,'kind':payments.SETUP_KIND,'budget_version':payments.VERSION})
