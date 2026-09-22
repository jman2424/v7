"""Model changes require two confirmations and stay tenant-scoped at execution."""
from unittest.mock import Mock
import pytest
from service import model_settings, api_usage
from tests.test_platform_security import platform, login


def request(client, method, path, csrf, **data):
    return client.open('/admin/api/ai-model'+path,method=method,json=data,headers={'X-CSRF-Token':csrf})


def test_model_change_requires_both_confirmations_and_applies_to_calls(platform):
    app=platform[0]
    client=app.test_client()
    csrf=login(client)
    assert request(client,'PUT','',csrf,model='gpt-4o',confirm_and_save=True).status_code==409
    review=request(client,'POST','/review',csrf,model='gpt-4o')
    assert review.status_code==200
    token=review.json['token']
    assert request(client,'PUT','',csrf,token=token,confirm_and_save=True).status_code==409
    assert model_settings.selected('ALPHA',app.container.storage) is None
    assert request(client,'POST','/confirm',csrf,token=token).status_code==400
    confirm=request(client,'POST','/confirm',csrf,token=token,acknowledge_cost_and_responses=True)
    assert confirm.status_code==200
    final=confirm.json['token']
    assert model_settings.selected('ALPHA',app.container.storage) is None
    assert request(client,'PUT','',csrf,token=final).status_code==400
    assert request(client,'PUT','',csrf,token=final,confirm_and_save=True).status_code==200
    assert request(client,'PUT','',csrf,token=final,confirm_and_save=True).status_code==409
    assert model_settings.selected('ALPHA',app.container.storage)=='gpt-4o'
    assert model_settings.selected('BETA',app.container.storage) is None
    provider=Mock()
    provider.chat.completions.create.return_value={'model':'gpt-4o','usage':{'prompt_tokens':5,'completion_tokens':2}}
    with app.app_context():
        for purpose in ['planning','rewriting']:
            with api_usage.usage_context('ALPHA','web'):
                api_usage.tracked_completion(provider,purpose=purpose,model='gpt-4o-mini')
            assert provider.chat.completions.create.call_args.kwargs['model']=='gpt-4o'
        with api_usage.usage_context('BETA','web'):
            api_usage.tracked_completion(provider,purpose='planning',model='gpt-4o-mini')
        assert provider.chat.completions.create.call_args.kwargs['model']=='gpt-4o-mini'
    assert client.put('/files/raw/ai_model.json',json={'model':'gpt-4o-mini'},headers={'X-CSRF-Token':csrf}).status_code==404


def test_model_change_auth_csrf_tenant_allowlist_and_stale_settings(platform):
    app=platform[0]
    client=app.test_client()
    assert client.post('/admin/api/ai-model/review',json={'model':'gpt-4o'}).status_code in {401,403}
    csrf=login(client)
    assert client.post('/admin/api/ai-model/review',json={'model':'gpt-4o'}).status_code==403
    assert request(client,'POST','/review?tenant=BETA',csrf,model='gpt-4o').status_code==403
    assert request(client,'POST','/review',csrf,model='unapproved-model').status_code==400
    review=request(client,'POST','/review',csrf,model='gpt-4o').json
    confirm=request(client,'POST','/confirm',csrf,token=review['token'],acknowledge_cost_and_responses=True).json
    app.container.storage.write_json('ALPHA','ai_model.json',{'model':'gpt-4o-mini','generation':'another-owner-change'})
    assert request(client,'PUT','',csrf,token=confirm['token'],confirm_and_save=True).status_code==409
    review=request(client,'POST','/review',csrf,model='gpt-4o').json
    with client.session_transaction() as state:
        change=state['model_change'];change['expires']=0;state['model_change']=change
    assert request(client,'POST','/confirm',csrf,token=review['token'],acknowledge_cost_and_responses=True).status_code==409


def test_usage_configuration_reports_selected_model(platform,monkeypatch):
    from service import usage_currency
    monkeypatch.setattr(usage_currency,'gbp_rate',lambda:None)
    app=platform[0]
    app.container.storage.write_json('ALPHA','ai_model.json',{'model':'gpt-4o','generation':'test'})
    client=app.test_client();login(client)
    config=client.get('/admin/api/api-usage').json['configuration']
    assert config['planning_model']==config['rewriting_model']=='gpt-4o'
    assert config['can_change_model'] is True
    assert [option['id'] for option in config['model_options']]==list(model_settings.MODELS)

def test_staff_cannot_change_model(client,monkeypatch):
    from tests.test_business_access import owner, staff_login
    from service import usage_currency
    monkeypatch.setattr(usage_currency,'gbp_rate',lambda:None)
    owner(client)
    created=client.post('/admin/api/accounts',json={'email':'staff@testing.test','password':'Test-password-only-123','roles':['business_staff'],'permissions':['view_costs']})
    assert created.status_code==201
    client.post('/auth/logout')
    staff_login(client)
    assert client.get('/admin/api/api-usage').json['configuration']['can_change_model'] is False
    assert client.post('/admin/api/ai-model/review',json={'model':'gpt-4o'}).status_code==403


def test_model_selection_preserves_tenant_filename_case(tmp_path,monkeypatch):
    from retrieval.storage import Storage
    from service import analytics_db
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(analytics_db,'DB_PATH',str(tmp_path/'usage.db'))
    storage=Storage('MixedCase')
    storage.tenant_dir('MixedCase').mkdir(parents=True)
    storage.write_json('MixedCase','ai_model.json',{'model':'gpt-4o'})
    provider=Mock()
    provider.chat.completions.create.return_value={}
    with api_usage.usage_context('MixedCase','web'):
        api_usage.tracked_completion(provider,purpose='planning',model='gpt-4o-mini')
    assert provider.chat.completions.create.call_args.kwargs['model']=='gpt-4o'
