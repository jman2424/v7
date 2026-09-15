import json

import pytest
from service.security import generate_totp_token
from service.account_service import AccountService


@pytest.mark.parametrize('role', ['platform_admin', 'business_owner', 'business_staff'])
def test_every_role_enrolls_before_access_and_requires_code_on_next_login(client, monkeypatch, role):
    email, password = 'mfa@example.test', 'Only-a-test-password-42!'
    if role == 'platform_admin':
        monkeypatch.setenv('ADMIN_USERNAME', email)
        monkeypatch.setenv('ADMIN_PASSWORD', password)
        monkeypatch.delenv('ADMIN_TOTP_SECRET', raising=False)
    else:
        AccountService(client.application.container.storage).create_account('EXAMPLE', {'email':email,'password':password,'roles':[role]})
    credentials = {'email':email,'password':password,'tenant':'EXAMPLE'}
    first = client.post('/auth/login', json=credentials)
    assert first.status_code == 202
    secret = first.json['mfa']['setup_key']
    assert first.json['mfa']['enrollment']
    assert first.json['mfa']['qr_image'].startswith('data:image/svg+xml;base64,')
    assert client.get('/admin/api/catalog').status_code == 401
    with client.session_transaction() as cookie:
        assert secret not in json.dumps(dict(cookie))
        assert password not in json.dumps(dict(cookie))
        assert 'user' not in cookie
    verified = client.post('/auth/mfa/confirm', json={'code':generate_totp_token(secret)})
    assert verified.status_code == 200
    assert secret not in verified.text
    assert client.get('/admin/api/catalog').status_code == 200
    client.post('/auth/logout')
    second = client.post('/auth/login', json=credentials)
    assert second.status_code == 202
    assert second.json['mfa']['enrollment'] is False
    assert 'setup_key' not in second.text
    assert client.get('/admin/api/catalog').status_code == 401
    assert client.post('/auth/mfa/confirm', json={'code':generate_totp_token(secret)}).status_code == 200


def test_mfa_challenge_requires_same_browser_and_active_unchanged_account(client):
    service = AccountService(client.application.container.storage)
    account = service.create_account('EXAMPLE', {'email':'mfa@example.test','password':'Only-test-password-42!','roles':['business_owner']})
    response = client.post('/auth/login', json={'email':'mfa@example.test','password':'Only-test-password-42!','tenant':'EXAMPLE'})
    code = generate_totp_token(response.json['mfa']['setup_key'])
    other = client.application.test_client()
    assert other.post('/auth/mfa/confirm', json={'code':code}).status_code == 401
    service.update_account('EXAMPLE', account['id'], {'active':False})
    assert client.post('/auth/mfa/confirm', json={'code':code}).status_code == 401
    assert client.get('/admin/api/catalog').status_code == 401


def test_mfa_challenge_expires_and_cannot_be_replayed(client, monkeypatch):
    from service import account_mfa
    monkeypatch.setenv('ADMIN_USERNAME','mfa@example.test')
    monkeypatch.setenv('ADMIN_PASSWORD','Only-test-password-42!')
    monkeypatch.delenv('ADMIN_TOTP_SECRET', raising=False)
    response = client.post('/auth/login', json={'email':'mfa@example.test','password':'Only-test-password-42!','tenant':'EXAMPLE'})
    code = generate_totp_token(response.json['mfa']['setup_key'])
    now = account_mfa.time.time()
    monkeypatch.setattr(account_mfa.time, 'time', lambda:now+301)
    assert client.post('/auth/mfa/confirm', json={'code':code}).status_code == 401
    assert client.get('/auth/session').json['user'] is None


@pytest.mark.parametrize('role', ['business_staff'])
def test_staff_cannot_create_tenants(client, role):
    from tests.conftest import set_test_identity
    with client.session_transaction() as state:
        set_test_identity(client, state, {'id':'owner','roles':[role],'tenant':'EXAMPLE'})
    assert client.post('/admin/api/tenants', json={'key':'NEW','name':'Another company'}).status_code == 403
    assert not client.application.container.storage.tenant_dir('NEW').exists()
