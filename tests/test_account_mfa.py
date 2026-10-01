import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pyotp
import pytest
from service.security import generate_totp_token
from service.account_service import AccountService


@pytest.mark.parametrize('role', ['platform_admin', 'business_owner', 'business_staff'])
def test_every_role_enrolls_before_access_and_requires_code_on_next_login(client, monkeypatch, role):
    now = int(time.time())
    monkeypatch.setattr('service.security.time.time', lambda: now)
    email, password = 'mfa@example.test', 'Only-a-test-password-42!'
    if role == 'platform_admin':
        monkeypatch.setenv('ADMIN_USERNAME', email)
        monkeypatch.setenv('ADMIN_PASSWORD', password)
        monkeypatch.delenv('ADMIN_TOTP_SECRET', raising=False)
    else:
        AccountService(client.application.container.storage).create_account('EXAMPLE', {'email':email,'password':password,'roles':[role],
            **({'permissions': ['offerings.read']} if role == 'business_staff' else {})})
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
    code = pyotp.TOTP(secret).at(now)
    verified = client.post('/auth/mfa/confirm', json={'code':code})
    assert verified.status_code == 200
    assert secret not in verified.text
    assert client.get('/admin/api/catalog').status_code == 200
    client.post('/auth/logout')
    second = client.post('/auth/login', json=credentials)
    assert second.status_code == 202
    assert second.json['mfa']['enrollment'] is False
    assert 'setup_key' not in second.text
    assert client.get('/admin/api/catalog').status_code == 401
    assert client.post('/auth/mfa/confirm', json={'code':code}).status_code == 401
    now += 30
    assert client.post('/auth/mfa/confirm', json={'code':pyotp.TOTP(secret).at(now)}).status_code == 200


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


@pytest.mark.parametrize('logout_path', ['/auth/logout', '/admin/logout'])
def test_logout_revokes_pending_mfa_even_if_cookie_is_replayed(client, logout_path):
    AccountService(client.application.container.storage).create_account('EXAMPLE', {
        'email': 'logout-mfa@example.test', 'password': 'Logout-MFA-test-password-123',
        'roles': ['business_owner'],
    })
    challenge = client.post('/auth/login', json={
        'email': 'logout-mfa@example.test', 'password': 'Logout-MFA-test-password-123',
        'tenant': 'EXAMPLE',
    })
    assert challenge.status_code == 202
    cookie_name = client.application.config['SESSION_COOKIE_NAME']
    copied_cookie = client.get_cookie(cookie_name).value
    code = generate_totp_token(challenge.json['mfa']['setup_key'])
    assert client.post(logout_path).status_code in {200, 303}

    replay = client.application.test_client()
    replay.set_cookie(cookie_name, copied_cookie)
    assert replay.get('/auth/session').json['mfa'] is None
    assert replay.post('/auth/mfa/confirm', json={'code': code}).status_code == 401
    assert replay.get('/admin/api/catalog').status_code == 401


def test_changed_account_revokes_pending_enrollment_before_showing_setup_key(client):
    service = AccountService(client.application.container.storage)
    account = service.create_account('EXAMPLE', {
        'email': 'changed-mfa@example.test', 'password': 'Changed-MFA-test-password-123',
        'roles': ['business_owner'],
    })
    challenge = client.post('/auth/login', json={
        'email': 'changed-mfa@example.test', 'password': 'Changed-MFA-test-password-123',
        'tenant': 'EXAMPLE',
    })
    assert challenge.status_code == 202
    service.update_account('EXAMPLE', account['id'], {'active': False})
    response = client.get('/auth/session')
    assert response.status_code == 200
    assert response.json['mfa'] is None
    assert 'setup_key' not in response.text


def test_enrollment_and_combined_login_codes_cannot_be_reused(client, monkeypatch):
    from service import account_mfa
    now = 1_900_000_000.0
    monkeypatch.setattr(account_mfa.time, 'time', lambda: now)
    AccountService(client.application.container.storage).create_account('EXAMPLE', {
        'email': 'single-use@example.test', 'password': 'Single-use-MFA-password-123',
        'roles': ['business_owner'],
    })
    credentials = {'email': 'single-use@example.test', 'password': 'Single-use-MFA-password-123',
                   'tenant': 'EXAMPLE'}
    challenge = client.post('/auth/login', json=credentials)
    secret = challenge.json['mfa']['setup_key']
    code = pyotp.TOTP(secret).at(now)
    assert client.post('/auth/mfa/confirm', json={'code': code}).status_code == 200
    client.post('/auth/logout')
    # An enrollment code is spent for both challenge and combined login paths.
    rejected = client.post('/auth/login', json={**credentials, 'totp': code})
    assert rejected.status_code == 401 and rejected.json['error'] == 'authenticator_code_reused'
    assert client.post('/auth/login', json=credentials).status_code == 202
    rejected = client.post('/auth/mfa/confirm', json={'code': code})
    assert rejected.status_code == 401 and rejected.json['error'] == 'authenticator_code_reused'
    assert client.get('/admin/api/catalog').status_code == 401
    fresh = pyotp.TOTP(secret).at(now+30)
    assert client.post('/auth/mfa/confirm', json={'code': fresh},
                       environ_overrides={'REMOTE_ADDR': '192.0.2.10'}).status_code == 200
    client.post('/auth/logout')
    # A future skew-step code remains spent without deleting the current step.
    other = client.application.test_client()
    for reused in (code, fresh):
        rejected = other.post('/auth/login', json={**credentials, 'totp': reused},
                              environ_overrides={'REMOTE_ADDR': '192.0.2.20'})
        assert rejected.status_code == 401 and rejected.json['error'] == 'authenticator_code_reused'


def test_combined_login_rolls_back_code_use_if_session_creation_fails(client, monkeypatch):
    from service import session_store
    from service.security import generate_totp_secret
    secret = generate_totp_secret()
    monkeypatch.setenv('ADMIN_USERNAME', 'atomic-mfa@example.test')
    monkeypatch.setenv('ADMIN_PASSWORD', 'Atomic-MFA-test-password-123')
    monkeypatch.setenv('ADMIN_TOTP_SECRET', secret)
    credentials = {'email': 'atomic-mfa@example.test', 'password': 'Atomic-MFA-test-password-123',
                   'tenant': 'EXAMPLE', 'totp': generate_totp_token(secret)}

    def fail_session(*args, **kwargs):
        raise RuntimeError('disposable session failure')

    with monkeypatch.context() as patch:
        patch.setattr('service.security.start_management_session', fail_session)
        assert client.post('/auth/login', json=credentials).status_code == 500
    with session_store.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM mfa_code_uses').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM management_sessions').fetchone()[0] == 0
    assert client.post('/auth/login', json=credentials).status_code == 200


def test_simultaneous_combined_code_submissions_create_only_one_session(app, monkeypatch):
    from service import security, session_store
    secret = security.generate_totp_secret()
    monkeypatch.setenv('ADMIN_USERNAME', 'simultaneous-mfa@example.test')
    monkeypatch.setenv('ADMIN_PASSWORD', 'Simultaneous-MFA-test-password-123')
    monkeypatch.setenv('ADMIN_TOTP_SECRET', secret)
    barrier = Barrier(2)
    authenticate = security.authenticate_user

    def authenticate_together(*args, **kwargs):
        user = authenticate(*args, **kwargs)
        barrier.wait(timeout=10)
        return user

    monkeypatch.setattr(security, 'authenticate_user', authenticate_together)
    credentials = {'email': 'simultaneous-mfa@example.test', 'password': 'Simultaneous-MFA-test-password-123',
                   'tenant': 'EXAMPLE', 'totp': generate_totp_token(secret)}

    def sign_in(index):
        return app.test_client().post('/auth/login', json=credentials,
                                      environ_overrides={'REMOTE_ADDR': f'192.0.2.{index+1}'})

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(sign_in, range(2)))
    assert sorted(response.status_code for response in results) == [200, 401]
    assert next(response for response in results if response.status_code == 401).json['error'] == 'authenticator_code_reused'
    with session_store.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM management_sessions').fetchone()[0] == 1
        assert db.execute('SELECT COUNT(*) FROM mfa_code_uses').fetchone()[0] == 1


@pytest.mark.parametrize('change', [
    {'password': 'Changed-linked-account-password-456'},
    {'permissions': ['offerings.read']},
])
def test_linked_account_proof_cannot_authorize_a_later_credential_revision(client, change):
    from werkzeug.exceptions import Unauthorized
    from service.security import resolve_linked_account, start_management_session

    service = AccountService(client.application.container.storage)
    account = service.create_account('EXAMPLE', {
        'email': 'linked-proof@example.test', 'password': 'Linked-account-password-123',
        'roles': ['business_owner'],
    })
    first = client.post('/auth/login', json={
        'email': account['email'], 'password': 'Linked-account-password-123', 'tenant': 'EXAMPLE',
    })
    secret = first.json['mfa']['setup_key']
    assert client.post('/auth/mfa/confirm', json={'code': generate_totp_token(secret)}).status_code == 200
    with client.application.test_request_context('/auth/oidc/google/callback'):
        user = resolve_linked_account({'id': account['id'], 'email': account['email'], 'tenant': 'EXAMPLE'})
        assert user and user['_credential_revision'] and user['_account_revision']
        service.update_account('EXAMPLE', account['id'], change)
        with pytest.raises(Unauthorized):
            start_management_session(user, 'EXAMPLE', mfa_verified=True)


@pytest.mark.parametrize('role', ['business_staff'])
def test_staff_cannot_create_tenants(client, role):
    from tests.conftest import set_test_identity
    with client.session_transaction() as state:
        set_test_identity(client, state, {'id':'owner','roles':[role],'tenant':'EXAMPLE'})
    assert client.post('/admin/api/tenants', json={'key':'NEW','name':'Another company'}).status_code == 403
    assert not client.application.container.storage.tenant_dir('NEW').exists()
