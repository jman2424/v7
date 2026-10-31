"""Optional modules gate discovery, direct execution and queued work identically."""
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from service import agent_modules as modules, business_channels as channels, business_operations as operations
from service.conversion_actions import ActionError, public_availability, submit_action
from tests.conftest import set_test_identity
from tests.test_business_channel_providers import configured as _configured, owner, reviewed, received, fake_answer, intake
from tests.test_booking_management import settings, book

configured = _configured


@pytest.fixture(autouse=True)
def policy_environment(monkeypatch):
    monkeypatch.setenv('V7_AGENT_MODULE_POLICY_JSON', '{}')


def policy(storage, tenant='EXAMPLE', **enabled):
    value = {'version':1, 'modules':{name:{'granted':True,'enabled':enabled.get(name,True)} for name in modules.REGISTRY}}
    storage.write_json(tenant,modules.FILENAME,value)
    return value


def operator(client):
    with client.session_transaction() as state:
        set_test_identity(client,state,{'id':'operator','role':'platform_admin'})


def test_legacy_actions_are_preserved_until_explicit_migration(client, configured):
    storage=configured.storage
    storage.write_json('EXAMPLE','sales_actions.json',settings())
    assert public_availability(storage,'EXAMPLE')['quote']['enabled']
    operator(client)
    before=client.get('/admin/api/agent-modules?tenant=EXAMPLE').json
    assert not before['initialized'] and before['core_intelligence_always_on']
    grants={row['id']:row['granted'] for row in before['modules']}
    response=client.put('/admin/api/agent-modules/grants?tenant=EXAMPLE',json={'revision':before['revision'],'grants':grants})
    assert response.status_code==200 and response.json['initialized']
    assert all(row['enabled'] for row in response.json['modules'])
    assert public_availability(storage,'EXAMPLE')['quote']['enabled']
    assert client.put('/admin/api/agent-modules/grants?tenant=EXAMPLE',json={'revision':before['revision'],'grants':grants}).status_code==409


def test_new_grant_does_not_enable_unconfigured_or_previously_disabled_service(client, configured):
    operator(client)
    before=client.get('/admin/api/agent-modules?tenant=EXAMPLE').json
    response=client.put('/admin/api/agent-modules/grants?tenant=EXAMPLE',json={
        'revision':before['revision'],'grants':{name:True for name in modules.REGISTRY}})
    assert response.status_code==200
    rows={row['id']:row for row in response.json['modules']}
    assert rows['quote']['granted'] and not rows['quote']['enabled'] and not rows['quote']['available']


def test_owner_controls_cannot_grant_migrate_or_cross_tenants(client, configured):
    owner(client)
    before=client.get('/admin/api/agent-modules?tenant=EXAMPLE').json
    values={name:True for name in modules.REGISTRY}
    assert client.put('/admin/api/agent-modules/grants?tenant=EXAMPLE',json={'revision':before['revision'],'grants':values}).status_code==403
    assert client.put('/admin/api/agent-modules?tenant=EXAMPLE',json={'revision':before['revision'],'enabled':values}).status_code==409
    assert client.get('/admin/api/agent-modules?tenant=OTHER').status_code==403
    assert client.put('/files/raw/agent_modules.json?tenant=EXAMPLE',json={}).status_code==404
    assert modules.document(configured.storage,'EXAMPLE') is None


def test_owner_cannot_escalate_grants_or_overwrite_concurrent_changes(client, configured):
    value=policy(configured.storage)
    value['modules']['quote']['granted']=False
    configured.storage.write_json('EXAMPLE',modules.FILENAME,value)
    owner(client)
    before=client.get('/admin/api/agent-modules?tenant=EXAMPLE').json
    values={name:False for name in modules.REGISTRY}
    assert client.put('/admin/api/agent-modules?tenant=EXAMPLE',json={'revision':before['revision'],'enabled':{**values,'quote':True}}).status_code==403
    assert client.put('/admin/api/agent-modules?tenant=EXAMPLE',json={'revision':before['revision'],'enabled':values,'grants':values}).status_code==400
    saved=client.put('/admin/api/agent-modules?tenant=EXAMPLE',json={'revision':before['revision'],'enabled':values})
    assert saved.status_code==200
    assert client.put('/admin/api/agent-modules?tenant=EXAMPLE',json={'revision':before['revision'],'enabled':values}).status_code==409
    assert not modules.allowed(configured.storage,'EXAMPLE','quote')


@pytest.mark.parametrize('payload',[None, [], {}, {'quote':'true'}, {'intelligence':False}])
def test_invalid_or_unknown_module_settings_fail_closed(client,configured,payload):
    policy(configured.storage)
    owner(client)
    before=client.get('/admin/api/agent-modules?tenant=EXAMPLE').json
    response=client.put('/admin/api/agent-modules?tenant=EXAMPLE',json={'revision':before['revision'],'enabled':payload})
    assert response.status_code==400
    assert modules.allowed(configured.storage,'EXAMPLE','quote')


def test_authentication_permissions_and_csrf_are_preserved(client,configured):
    assert client.get('/admin/api/agent-modules?tenant=EXAMPLE').status_code==401
    for role in ('business_staff','business_owner'):
        with client.session_transaction() as state:
            set_test_identity(client,state,{'id':role,'role':role,'tenant':'EXAMPLE','permissions':[]})
        assert client.get('/admin/api/agent-modules?tenant=EXAMPLE').status_code==403
    operator(client)
    before=client.get('/admin/api/agent-modules?tenant=EXAMPLE').json
    assert client.put('/admin/api/agent-modules/grants?tenant=EXAMPLE',json={
        'revision':before['revision'],'grants':{name:True for name in modules.REGISTRY}},
        headers={'X-CSRF-Token':'wrong'}).status_code==403


def test_kill_switch_and_actual_plan_are_rechecked_without_changing_pricing(configured,monkeypatch):
    storage=configured.storage
    policy(storage)
    assert modules.allowed(storage,'EXAMPLE','quote')
    monkeypatch.setenv('V7_AGENT_MODULE_POLICY_JSON','{"disabled":["quote"]}')
    assert not modules.allowed(storage,'EXAMPLE','quote')
    monkeypatch.setenv('V7_AGENT_MODULE_POLICY_JSON','{"plans":{"quote":["scale"]}}')
    monkeypatch.setattr('service.subscriptions.configured_plan',lambda _: {'id':'starter','selected_plan':'scale'})
    assert modules.decisions(storage,'EXAMPLE',('quote',))['quote']['reason']=='plan_not_allowed'
    monkeypatch.setattr('service.subscriptions.configured_plan',lambda _: {'id':'scale'})
    assert modules.allowed(storage,'EXAMPLE','quote')
    monkeypatch.setattr('service.subscriptions.configured_plan',lambda _: None)
    assert not modules.allowed(storage,'EXAMPLE','quote')


@pytest.mark.parametrize('value',['broken','{"disabled":["unknown"]}','{"plans":{"quote":["invented"]}}'])
def test_malformed_global_policy_disables_operations_not_core_knowledge(configured,monkeypatch,value):
    monkeypatch.setenv('V7_AGENT_MODULE_POLICY_JSON',value)
    state=modules.snapshot(configured,'EXAMPLE')
    assert state['core_intelligence_always_on']
    assert all(not row['available'] for row in state['modules'])


def test_no_extra_billing_read_when_all_current_plans_remain_allowed(configured,monkeypatch):
    monkeypatch.setattr('service.subscriptions.configured_plan',Mock(side_effect=AssertionError('Unnecessary billing read')))
    assert all(row['allowed'] for row in modules.decisions(configured.storage,'EXAMPLE',modules.REGISTRY).values())


def test_revoked_quote_is_hidden_and_direct_execution_cannot_bypass_it(configured):
    storage=configured.storage
    storage.write_json('EXAMPLE','sales_actions.json',settings())
    policy(storage,quote=False)
    assert not public_availability(storage,'EXAMPLE')['quote']['enabled']
    with pytest.raises(ActionError,match='action_unavailable'):
        submit_action(storage,'EXAMPLE',{'action':'quote','name':'Synthetic','contact':'visitor@example.net','consent':True},'module-test')
    from service.conversion_actions import list_action_requests
    assert not list_action_requests('EXAMPLE')


def test_booking_creation_and_management_are_separate_controls(configured):
    from service.booking_management import manage_booking
    storage=configured.storage
    storage.write_json('EXAMPLE','sales_actions.json',settings())
    ref=book(storage,'EXAMPLE')['reference']
    policy(storage,consultation=False)
    with pytest.raises(ActionError,match='action_unavailable'):
        manage_booking(storage,'EXAMPLE',ref,'reschedule',slot_id='second',expected_slot_id='first')
    policy(storage,consultation=False,booking_management=False)
    with pytest.raises(ActionError,match='management_unavailable'):
        manage_booking(storage,'EXAMPLE',ref,'cancel',expected_slot_id='first')
    assert manage_booking(storage,'EXAMPLE',ref,'view')['status']=='confirmed'
    policy(storage,consultation=False)
    assert manage_booking(storage,'EXAMPLE',ref,'cancel',expected_slot_id='first')['status']=='cancelled'


def test_background_send_stops_after_module_revocation(client,configured,monkeypatch):
    from connectors import business_email
    from service.channel_worker import process_one
    job=reviewed(client,configured)
    operations.decide('EXAMPLE',job['id'],job['version'],'approve')
    policy(configured.storage,email=False)
    send=Mock(side_effect=AssertionError('Revoked module sent mail'))
    monkeypatch.setattr(business_email,'send_reply',send)
    assert process_one(configured,'EXAMPLE')
    assert operations.get('EXAMPLE',job['id'])['state']=='needs_review'
    send.assert_not_called()


def test_revocation_during_generation_prevents_automatic_approval(client,configured,monkeypatch):
    from connectors import business_email
    from service.channel_worker import process_one
    row=intake(client).json
    monkeypatch.setattr(business_email,'receive',lambda _:received())
    fake_answer(monkeypatch,configured)
    original=configured.for_tenant('EXAMPLE').handler.handle
    def handle(*args,**kwargs):
        policy(configured.storage,email=False)
        return original(*args,**kwargs)
    configured.for_tenant('EXAMPLE').handler.handle=handle
    process_one(configured,'EXAMPLE')
    assert operations.get('EXAMPLE',row['reference'])['state']=='needs_review'


def test_audit_failure_prevents_policy_initialization(client,configured,monkeypatch):
    from service.audit import AuditService
    operator(client)
    before=client.get('/admin/api/agent-modules?tenant=EXAMPLE').json
    original=AuditService.record
    def record(self,**kwargs):
        if kwargs['action']=='agent.modules.grants':
            raise OSError('private-provider-path')
        return original(self,**kwargs)
    monkeypatch.setattr(AuditService,'record',record)
    response=client.put('/admin/api/agent-modules/grants?tenant=EXAMPLE',json={
        'revision':before['revision'],'grants':{name:True for name in modules.REGISTRY}})
    assert response.status_code==503 and 'private-provider-path' not in response.text
    assert modules.document(configured.storage,'EXAMPLE') is None


def test_discovery_revocation_does_not_discard_the_answer(app,monkeypatch):
    from handlers.handler_v7 import MessageHandlerV7
    from service import grounded_conversation
    handler=MessageHandlerV7(SimpleNamespace(rewriter=SimpleNamespace(_client=object(),_model='test')))
    handler.module_storage=app.container.storage
    handler.tenant_key='EXAMPLE'
    handler.sales_actions={'quote':{'enabled':True}}
    def answer(*args,**kwargs):
        assert kwargs['allowed_actions']==['quote']
        policy(app.container.storage,quote=False)
        kwargs['agent_state'].update(_validated_grounded=True,requested_action='quote')
        return 'The saved service information answers your question.'
    monkeypatch.setattr(grounded_conversation,'answer',answer)
    result=handler._grounded_answer('What can your team help with?',{},channel='web')
    assert result['reply']=='The saved service information answers your question.'
    assert result['actions']==[] and 'requested_action' not in result['agent']


def test_corrupted_policy_cannot_reenable_tools(configured):
    configured.storage.write_json('EXAMPLE',modules.FILENAME,{'version':True,'modules':{}})
    assert not modules.allowed(configured.storage,'EXAMPLE','quote')
    with pytest.raises(ValueError,match='invalid_module_configuration'):
        modules.snapshot(configured,'EXAMPLE')


def test_older_policy_does_not_grant_new_registry_entries(configured):
    value=policy(configured.storage)
    del value['modules']['phone']
    configured.storage.write_json('EXAMPLE',modules.FILENAME,value)
    assert modules.allowed(configured.storage,'EXAMPLE','quote')
    assert not modules.allowed(configured.storage,'EXAMPLE','phone')


def test_module_grants_are_the_channel_authority_after_migration(client,configured):
    value=policy(configured.storage,email=False)
    value['modules']['email']['granted']=False
    configured.storage.write_json('EXAMPLE',modules.FILENAME,value)
    # The older channel file cannot override an explicit module revocation.
    assert not channels.grants(configured.storage,'EXAMPLE')['email']
    operator(client)
    response=client.put('/admin/api/business-channel-grants?tenant=EXAMPLE',json={'email':True,'phone':False})
    assert response.status_code==200
    updated=modules.document(configured.storage,'EXAMPLE')['modules']
    assert updated['email']['granted'] and not updated['phone']['granted']
    assert updated['quote']==value['modules']['quote']
    assert not updated['email']['enabled']  # Granting does not activate sending.


def test_plan_storage_failure_blocks_tools_without_leaking_details(configured,monkeypatch,caplog):
    monkeypatch.setenv('V7_AGENT_MODULE_POLICY_JSON','{"plans":{"quote":["scale"]}}')
    monkeypatch.setattr('service.subscriptions.configured_plan',Mock(side_effect=sqlite3.OperationalError('private-customer-db')))
    assert not modules.allowed(configured.storage,'EXAMPLE','quote')
    assert 'private-customer-db' not in caplog.text


def test_future_module_is_off_for_both_legacy_and_migrated_businesses(configured,monkeypatch):
    monkeypatch.setitem(modules.REGISTRY,'future',modules.Module('Future module',('future_tool',),('web',),'confirmation'))
    assert not modules.allowed(configured.storage,'EXAMPLE','future')
    state=modules.snapshot(configured,'EXAMPLE')
    assert not next(row for row in state['modules'] if row['id']=='future')['enabled']
    value=modules.update_grants(configured.storage,'EXAMPLE',{name:True for name in modules.REGISTRY})
    assert not value['modules']['future']['enabled']
    configured.storage.write_json('EXAMPLE',modules.FILENAME,value)
    assert not modules.allowed(configured.storage,'EXAMPLE','future')
