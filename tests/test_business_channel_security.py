"""CodeQL #90–94 regressions: bounded parsing, safe failures and real RBAC."""
import logging
import os
from pathlib import Path
import subprocess
import sys

import pytest

from routes import admin_api_routes as api
from service import business_channels as channels, business_operations as operations
from tests.conftest import set_test_identity
from tests.test_business_channel_providers import configured as _configured, owner, reviewed

configured = _configured
PRIVATE = 'private-password access_token=private-token C:/private/customer.db tenant=PRIVATE_CUSTOMER'


@pytest.mark.parametrize('value', [
    'a+b@example.co.uk', "a!#$%&'*+-/=?^_`{|}~z@example.com", 'a.b@example.com',
    'USER@Sub-Domain.Example.COM', 'a@xn--bcher-kva.example',
    'a'*64+'@'+'b'*63+'.'+'c'*63+'.'+'d'*61,  # Exactly 254 characters.
])
def test_supported_email_addresses_remain_valid(value):
    assert channels.address(value) == value.lower()


@pytest.mark.parametrize('value', [
    None, [], {}, 123, '', '!'*20000, '!'*64+'@'+'!'*180, '!'*64+'@'+'a.'*90+'!',
    'a'*65+'@example.com', 'a'*64+'@'+'b'*63+'.'+'c'*63+'.'+'d'*62,
    '.a@example.com', 'a.@example.com', 'a' + '.'*180 + '@example.com',
    'a..b@example.com', 'a@'+'a.'*120+'!', 'a@'+'a'*64+'.example',
    'a@a..example', 'a@-bad.example', 'a@bad-.example', 'a@bad_.example',
    'a@example.com.', 'a@localhost', 'a@example.123', 'a@b@c.example',
    'a@éxample.com', 'a@exam\x00ple.com', 'a@example.com\r\nBcc: other@example.com',
])
def test_adversarial_addresses_fail_closed(value):
    with pytest.raises(ValueError, match='^invalid_channel_address$'):
        channels.address(value)


def test_oversized_address_is_rejected_before_scanning():
    class ScanForbidden(str):
        def count(self, *args):
            pytest.fail('Length guard must run before character scanning')
        def split(self, *args):
            pytest.fail('Length guard must run before allocation/splitting')
    with pytest.raises(ValueError, match='invalid_channel_address'):
        channels.address(ScanForbidden('!'*100000))


def test_adversarial_validation_has_a_bounded_cpu_budget():
    # Isolated child, no inherited provider credentials, hard wall-clock timeout.
    root = str(Path(__file__).resolve().parents[1])
    program = f"""import sys
sys.path.insert(0, {root!r})
from service.business_channels import address
values=['!'*64+'@'+'a.'*90+'!', 'a'+'.'*180+'@example.com', '!'*20000]
for _ in range(1000):
    for value in values:
        try: address(value)
        except ValueError: pass
        else: raise AssertionError('malformed input accepted')
"""
    env = {key: os.environ[key] for key in ('SystemRoot', 'WINDIR') if key in os.environ}
    result = subprocess.run([sys.executable, '-I', '-c', program], env=env, cwd=root,
                            capture_output=True, timeout=10, check=False)
    assert result.returncode == 0, 'Bounded email-validation child failed'


@pytest.mark.parametrize('kind', ['settings', 'grants', 'decision', 'action'])
def test_reported_handlers_never_expose_exception_details(client, configured, monkeypatch, caplog, kind):
    job = reviewed(client, configured)
    owner(client)
    before = operations.get('EXAMPLE', job['id'])
    def fail(*args, **kwargs):
        raise ValueError(PRIVATE)
    if kind == 'settings':
        monkeypatch.setattr(channels, 'validate', fail)
        method, path, payload, code, status = 'put', '/business-channels', {'settings': {}}, 'invalid_channel_settings', 400
    elif kind == 'grants':
        with client.session_transaction() as state:
            set_test_identity(client, state, {'id':'operator','role':'platform_admin'})
        monkeypatch.setattr(channels, 'validate_grants', fail)
        method, path, payload, code, status = 'put', '/business-channel-grants', {}, 'invalid_channel_grants', 400
    else:
        monkeypatch.setattr(operations, 'decide' if kind == 'decision' else 'begin_action', fail)
        method, path, status, code = 'post', '/business-operations/'+job['id']+'/'+kind, 409, 'operation_changed'
        payload = {'version':job['version'], 'decision':'reject'} if kind == 'decision' else {
            'version':job['version'], 'action':{'action':'quote','consent':True}}
    with caplog.at_level(logging.WARNING, logger='ADMIN.API'):
        response = getattr(client, method)('/admin/api'+path+'?tenant=EXAMPLE', json=payload)
    assert response.status_code == status and response.json == {'error':code}
    assert PRIVATE not in response.text + caplog.text
    for secret in ('private-password','private-token','customer.db','PRIVATE_CUSTOMER'):
        assert secret not in response.text + caplog.text
    assert 'ValueError' in caplog.text
    assert operations.get('EXAMPLE', job['id']) == before


@pytest.mark.parametrize('payload', [None, [], {}, {'decision':[],'version':1},
    {'decision':'approve','version':True}, {'decision':'approve','version':0},
    {'decision':'refund','version':1}, {'decision':'approve','version':1,'tenant':'OTHER'},
    {'decision':'approve','version':1,'reply':{}}, {'decision':'approve','version':1,'reply':'a'*6001},
    {'decision':'approve','version':1,'reply':'bad\x00reply'}])
def test_invalid_decisions_are_bad_requests_without_mutation(client, configured, payload):
    job = reviewed(client, configured)
    owner(client)
    response = client.post('/admin/api/business-operations/'+job['id']+'/decision?tenant=EXAMPLE', json=payload)
    assert response.status_code == 400 and response.json['error'] == 'invalid_operation_decision'
    assert operations.get('EXAMPLE',job['id'])['version'] == job['version']


@pytest.mark.parametrize('change', [{'version':True}, {'version':0}, {'version':'2'},
    {'action':{'action':[],'consent':True}}, {'action':{'action':'refund','consent':True}},
    {'action':{'action':'quote','consent':'true'}}, {'action':{'action':'quote','consent':True,'tenant':'OTHER'}}])
def test_invalid_actions_cannot_enter_execution(client, configured, change):
    job = reviewed(client, configured)
    owner(client)
    payload = {'version':job['version'],'action':{'action':'quote','consent':True}, **change}
    response = client.post('/admin/api/business-operations/'+job['id']+'/action?tenant=EXAMPLE',json=payload)
    assert response.status_code == 400 and response.json['error'] == 'invalid_operation_action'
    assert operations.get('EXAMPLE',job['id'])['version'] == job['version']


@pytest.mark.parametrize('suffix', ['decision','action'])
def test_authentication_tenant_and_missing_operation_statuses(client, configured, suffix):
    job = reviewed(client, configured)
    payload = {'version':job['version'],'decision':'reject'} if suffix=='decision' else {
        'version':job['version'],'action':{'action':'quote','consent':True}}
    path = '/admin/api/business-operations/'+job['id']+'/'+suffix
    assert client.post(path+'?tenant=EXAMPLE',json=payload).status_code == 401
    owner(client)
    assert client.post(path+'?tenant=OTHER',json=payload).status_code == 403
    assert client.post(path.replace(job['id'],'f'*32)+'?tenant=EXAMPLE',json=payload).status_code == 404
    assert client.post(path.replace(job['id'],'invalid')+'?tenant=EXAMPLE',json=payload).status_code == 400
    assert operations.get('EXAMPLE',job['id'])['state'] == 'needs_review'


def test_owner_and_staff_cannot_grant_channels(client, configured):
    for role in ('business_owner','business_staff'):
        with client.session_transaction() as state:
            set_test_identity(client,state,{'id':'user','role':role,'tenant':'EXAMPLE'})
        response = client.put('/admin/api/business-channel-grants?tenant=EXAMPLE',json={'email':True,'phone':True})
        assert response.status_code == 403


def test_decision_audit_failure_cannot_approve_a_reply(client, configured, monkeypatch, caplog):
    job = reviewed(client, configured)
    owner(client)
    def fail(*args):
        raise OSError(PRIVATE)
    monkeypatch.setattr(api, '_audit_operation', fail)
    response = client.post('/admin/api/business-operations/'+job['id']+'/decision?tenant=EXAMPLE',json={
        'decision':'approve','version':job['version']})
    assert response.status_code == 503
    assert operations.get('EXAMPLE',job['id']) == job
    assert PRIVATE not in response.text + caplog.text


def test_approval_retains_audit_and_prevents_duplicate_execution(client, configured, monkeypatch):
    job = reviewed(client, configured)
    owner(client)
    recorded=[]
    original=api._audit_operation
    def record(*args):
        recorded.append(args)
        return original(*args)
    monkeypatch.setattr(api,'_audit_operation',record)
    path='/admin/api/business-operations/'+job['id']+'/decision?tenant=EXAMPLE'
    payload={'version':job['version'],'decision':'approve','reply':'Approved support reply'}
    first=client.post(path,json=payload)
    assert first.status_code == 200 and first.json['operation']['state']=='approved'
    assert recorded[0]==('EXAMPLE',job['id'],'business.operation.decision','approve')
    assert client.post(path,json=payload).status_code==409
    claimed=operations.claim('EXAMPLE')
    assert claimed['state']=='sending' and operations.claim('EXAMPLE') is None


@pytest.mark.parametrize('value', [None, [], {'unknown':{}}, {'email':{'daily_limit':True}},
    {'email':{'retention_days':10000}}, {'email':{'enabled':True,'privacy_confirmed':False}},
    {'email':{'provider_cleanup':'trash_handled','cleanup_confirmed':False}},
    {'email':{'api_key':'injected-token'}}])
def test_channel_json_cannot_bypass_server_validation(client, configured, value):
    owner(client)
    before=configured.storage.read_json('EXAMPLE',channels.FILENAME)
    response=client.put('/admin/api/business-channels?tenant=EXAMPLE',json={'settings':value})
    assert response.status_code==400 and response.json=={'error':'invalid_channel_settings'}
    assert configured.storage.read_json('EXAMPLE',channels.FILENAME)==before


@pytest.mark.parametrize('value', [None, [], {}, {'email':True}, {'email':'true','phone':False},
    {'email':True,'phone':True,'tenant':'OTHER'}])
def test_platform_grants_still_validate_the_complete_json_shape(client, configured, value):
    with client.session_transaction() as state:
        set_test_identity(client,state,{'id':'operator','role':'platform_admin'})
    before=configured.storage.read_json('EXAMPLE',channels.GRANTS_FILE)
    response=client.put('/admin/api/business-channel-grants?tenant=EXAMPLE',json=value)
    assert response.status_code==400 and response.json=={'error':'invalid_channel_grants'}
    assert configured.storage.read_json('EXAMPLE',channels.GRANTS_FILE)==before


def test_grants_succeed_only_for_an_authorized_operator(client, configured):
    with client.session_transaction() as state:
        set_test_identity(client,state,{'id':'operator','role':'platform_admin'})
    response=client.put('/admin/api/business-channel-grants?tenant=EXAMPLE',json={'email':False,'phone':True})
    assert response.status_code==200 and response.json['grants']=={'email':False,'phone':True}
    assert configured.storage.read_json('EXAMPLE',channels.GRANTS_FILE)=={'email':False,'phone':True}


def test_restricted_owner_permissions_and_csrf_remain_enforced(client, configured):
    job=reviewed(client,configured)
    with client.session_transaction() as state:
        set_test_identity(client,state,{'id':'restricted','role':'business_owner','tenant':'EXAMPLE',
            'permissions':sorted(['customers.read','integrations.read','business_settings.read'])})
    assert client.get('/admin/api/business-operations?tenant=EXAMPLE').status_code==200
    response=client.post('/admin/api/business-operations/'+job['id']+'/decision?tenant=EXAMPLE',json={
        'version':job['version'],'decision':'approve'})
    assert response.status_code==403
    owner(client)
    response=client.post('/admin/api/business-operations/'+job['id']+'/decision?tenant=EXAMPLE',json={
        'version':job['version'],'decision':'approve'},headers={'X-CSRF-Token':'incorrect'})
    assert response.status_code==403
    assert operations.get('EXAMPLE',job['id'])['state']=='needs_review'


@pytest.mark.parametrize('endpoint,attribute,error,code,status', [
    ('website-destinations','unused',ValueError,'invalid_website_destinations',400),
    ('website-knowledge/import','import_website',api.WebsiteImportError,'website_import_failed',422),
    ('sales-actions','validate_actions_config',ValueError,'invalid_sales_actions',400),
])
def test_adjacent_handlers_return_only_reviewed_errors(client, configured, monkeypatch, caplog, endpoint, attribute, error, code, status):
    owner(client)
    def fail(*args):
        raise error(PRIVATE)
    if endpoint == 'website-destinations':
        monkeypatch.setattr('service.website_destinations.validate',fail)
    else:
        monkeypatch.setattr(api,attribute,fail)
    method = client.post if endpoint.endswith('/import') else client.put
    response = method('/admin/api/'+endpoint+'?tenant=EXAMPLE',json={})
    assert response.status_code == status and response.json == {'error':code}
    assert PRIVATE not in response.text + caplog.text
