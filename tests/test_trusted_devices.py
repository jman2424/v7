"""Thirty-day proofs supplement passwords and never replace initial MFA."""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pyotp
import pytest

from service import security, session_store, trusted_devices
from service.account_service import AccountService

PASSWORD = 'Trusted-device-test-password-123'
EMAIL = 'trusted-owner@example.test'
CREDENTIALS = {'email': EMAIL, 'password': PASSWORD, 'tenant': 'EXAMPLE'}


@pytest.fixture
def account(app, monkeypatch):
    clock = [1_900_000_000.0]
    monkeypatch.setattr(session_store.time, 'time', lambda: clock[0])
    record = AccountService(app.container.storage).create_account('EXAMPLE', {
        'email': EMAIL, 'password': PASSWORD, 'roles': ['business_owner'],
    })
    return record, clock


def enroll(client, account, *, remember=True):
    challenge = client.post('/auth/login', json={**CREDENTIALS, 'remember_device': remember})
    assert challenge.status_code == 202
    assert client.get_cookie(trusted_devices.COOKIE_NAME) is None
    secret = challenge.json['mfa']['setup_key']
    response = client.post('/auth/mfa/confirm', json={
        'code': pyotp.TOTP(secret).at(account[1][0]), 'remember_device': remember,
    })
    assert response.status_code == 200
    return secret, response


def forget_session(client):
    client.delete_cookie(client.application.config['SESSION_COOKIE_NAME'])


def test_trust_is_opt_in_and_is_issued_only_after_successful_mfa(client, account):
    challenge = client.post('/auth/login', json={**CREDENTIALS, 'remember_device': True})
    assert challenge.status_code == 202
    assert client.get_cookie(trusted_devices.COOKIE_NAME) is None
    assert client.post('/auth/mfa/confirm', json={'code': 'invalid', 'remember_device': True}).status_code == 401
    assert client.get_cookie(trusted_devices.COOKIE_NAME) is None
    response = client.post('/auth/mfa/confirm', json={
        'code': pyotp.TOTP(challenge.json['mfa']['setup_key']).at(account[1][0]),
    })
    assert response.status_code == 200
    assert client.get_cookie(trusted_devices.COOKIE_NAME) is None
    forget_session(client)
    assert client.post('/auth/login', json=CREDENTIALS).status_code == 202


def test_trusted_cookie_has_absolute_30_day_expiry_and_only_hash_is_persisted(client, account):
    client.application.config['SESSION_COOKIE_SECURE'] = True
    _, response = enroll(client, account)
    raw = client.get_cookie(trusted_devices.COOKIE_NAME).value
    header = next(value for value in response.headers.getlist('Set-Cookie')
                  if value.startswith(trusted_devices.COOKIE_NAME+'='))
    for expected in ['Max-Age=2592000', 'HttpOnly', 'Secure', 'SameSite=Lax', 'Path=/']:
        assert expected in header
    assert raw not in response.text
    with client.session_transaction() as state:
        assert raw not in json.dumps(dict(state))
    with session_store.connection() as db:
        saved, expires = db.execute('SELECT token_hash,expires FROM trusted_devices').fetchone()
        session_expiry = db.execute('SELECT expires FROM management_sessions').fetchone()[0]
    assert saved == hashlib.sha256(raw.encode()).hexdigest() and saved != raw
    assert expires == account[1][0]+30*86400
    assert session_expiry == account[1][0]+8*3600


def test_valid_same_account_proof_rotates_after_password_without_extending_expiry(client, account):
    enroll(client, account)
    old = client.get_cookie(trusted_devices.COOKIE_NAME).value
    with session_store.connection() as db:
        original_expiry = db.execute('SELECT expires FROM trusted_devices').fetchone()[0]
    account[1][0] += 60
    forget_session(client)
    response = client.post('/auth/login', json=CREDENTIALS)
    assert response.status_code == 200
    assert 'mfa' not in response.json
    new = client.get_cookie(trusted_devices.COOKIE_NAME).value
    assert new != old
    assert client.get('/admin/api/catalog').status_code == 200
    with session_store.connection() as db:
        rows = db.execute('SELECT token_hash,expires FROM trusted_devices').fetchall()
    assert rows == [(hashlib.sha256(new.encode()).hexdigest(), original_expiry)]
    replay = client.application.test_client()
    replay.set_cookie(trusted_devices.COOKIE_NAME, old)
    assert replay.post('/auth/login', json=CREDENTIALS,
                       environ_overrides={'REMOTE_ADDR': '192.0.2.20'}).status_code == 202
    assert replay.get('/admin/api/catalog').status_code == 401


def test_expired_normal_session_keeps_the_device_proof_until_explicit_logout(client, account):
    enroll(client, account)
    token = client.get_cookie(trusted_devices.COOKIE_NAME).value
    with session_store.connection() as db:
        db.execute('UPDATE management_sessions SET expires=?', (account[1][0]-1,))
    assert client.get('/auth/session').status_code == 401
    assert client.get_cookie(trusted_devices.COOKIE_NAME).value == token
    assert client.post('/auth/login', json=CREDENTIALS).status_code == 200


def test_device_proof_never_authenticates_without_the_password(client, account):
    enroll(client, account)
    forget_session(client)
    assert client.get('/admin/api/catalog').status_code == 401
    assert client.get('/auth/session').json['user'] is None
    assert client.post('/auth/login', json={**CREDENTIALS, 'password': 'wrong'}).status_code == 401
    assert client.get('/admin/api/catalog').status_code == 401


def test_device_proof_is_bound_to_account_and_cannot_skip_another_accounts_enrollment(client, account):
    enroll(client, account)
    AccountService(client.application.container.storage).create_account('EXAMPLE', {
        'email': 'other-owner@example.test', 'password': PASSWORD, 'roles': ['business_owner'],
    })
    forget_session(client)
    response = client.post('/auth/login', json={**CREDENTIALS, 'email': 'other-owner@example.test'})
    assert response.status_code == 202 and response.json['mfa']['enrollment']
    assert client.get_cookie(trusted_devices.COOKIE_NAME) is None


@pytest.mark.parametrize('logout_path', ['/auth/logout', '/admin/logout'])
def test_logout_revokes_server_proof_even_if_cookie_is_copied(client, account, logout_path):
    enroll(client, account)
    raw = client.get_cookie(trusted_devices.COOKIE_NAME).value
    assert client.post(logout_path).status_code in {200, 303}
    assert client.get_cookie(trusted_devices.COOKIE_NAME) is None
    replay = client.application.test_client()
    replay.set_cookie(trusted_devices.COOKIE_NAME, raw)
    assert replay.post('/auth/login', json=CREDENTIALS).status_code == 202
    with session_store.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM trusted_devices').fetchone()[0] == 0


@pytest.mark.parametrize('edit', [{'password': 'Changed-trusted-password-123'}, {'active': False}, {'permissions': ['view_costs']}])
def test_account_edits_revoke_all_its_device_proofs(client, account, edit):
    enroll(client, account)
    raw = client.get_cookie(trusted_devices.COOKIE_NAME).value
    AccountService(client.application.container.storage).update_account('EXAMPLE', account[0]['id'], edit)
    with session_store.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM trusted_devices').fetchone()[0] == 0
    replay = client.application.test_client()
    replay.set_cookie(trusted_devices.COOKIE_NAME, raw)
    credentials = {**CREDENTIALS, 'password': edit.get('password', PASSWORD)}
    response = replay.post('/auth/login', json=credentials)
    assert response.status_code == (401 if edit.get('active') is False else 202)


def test_external_registry_credential_changes_invalidate_existing_proof(client, account, monkeypatch):
    monkeypatch.setenv('ADMIN_USERNAME', 'trusted-operator@example.test')
    monkeypatch.setenv('ADMIN_PASSWORD', PASSWORD)
    secret = security.generate_totp_secret()
    monkeypatch.setenv('ADMIN_TOTP_SECRET', secret)
    credentials = {**CREDENTIALS, 'email': 'trusted-operator@example.test'}
    response = client.post('/auth/login', json={
        **credentials, 'totp': pyotp.TOTP(secret).at(account[1][0]), 'remember_device': True,
    })
    assert response.status_code == 200
    monkeypatch.setenv('ADMIN_PASSWORD', 'Changed-operator-password-123')
    forget_session(client)
    response = client.post('/auth/login', json={**credentials, 'password': 'Changed-operator-password-123'})
    assert response.status_code == 202
    assert client.get_cookie(trusted_devices.COOKIE_NAME) is None


def test_proof_expires_at_original_deadline_after_rotation(client, account):
    enroll(client, account)
    deadline = account[1][0]+trusted_devices.TRUST_SECONDS
    account[1][0] = deadline-1
    forget_session(client)
    assert client.post('/auth/login', json=CREDENTIALS).status_code == 200
    account[1][0] = deadline
    forget_session(client)
    assert client.post('/auth/login', json=CREDENTIALS).status_code == 202
    assert client.get_cookie(trusted_devices.COOKIE_NAME) is None


def test_device_management_is_authenticated_csrf_protected_and_scoped_to_own_account(client, account):
    assert client.get('/auth/devices').status_code == 401
    assert client.delete('/auth/devices').status_code == 401
    secret, _ = enroll(client, account)
    other = client.application.test_client()
    assert other.post('/auth/login', json={
        **CREDENTIALS, 'totp': pyotp.TOTP(secret).at(account[1][0]+30), 'remember_device': True,
    }, environ_overrides={'REMOTE_ADDR': '192.0.2.20'}).status_code == 200
    response = client.get('/auth/devices')
    assert response.status_code == 200 and response.json['count'] == 2
    assert sum(row['current'] for row in response.json['devices']) == 1
    assert all(set(row) == {'expires_utc', 'current'} for row in response.json['devices'])
    assert 'token_hash' not in response.text and EMAIL not in response.text
    # Another account's proof survives an own-account revoke-all operation.
    AccountService(client.application.container.storage).create_account('EXAMPLE', {
        'email': 'independent-owner@example.test', 'password': PASSWORD, 'roles': ['business_owner'],
    })
    independent = client.application.test_client()
    challenge = independent.post('/auth/login', json={**CREDENTIALS, 'email': 'independent-owner@example.test'},
                                 environ_overrides={'REMOTE_ADDR': '192.0.2.30'})
    assert independent.post('/auth/mfa/confirm', json={
        'code': pyotp.TOTP(challenge.json['mfa']['setup_key']).at(account[1][0]), 'remember_device': True,
    }, environ_overrides={'REMOTE_ADDR': '192.0.2.30'}).status_code == 200
    assert client.delete('/auth/devices', headers={'X-CSRF-Token': 'invalid'}).status_code == 403
    assert client.delete('/auth/devices', json={'account': 'someone-else'}).status_code == 200
    assert client.get('/auth/devices').json == {'count': 0, 'devices': []}
    assert client.get_cookie(trusted_devices.COOKIE_NAME) is None
    assert independent.get('/auth/devices').json['count'] == 1
    # Removing device proofs does not silently remove an already verified session.
    assert client.get('/admin/api/catalog').status_code == 200


def test_simultaneous_use_of_one_device_proof_skips_mfa_only_once(app, account, monkeypatch):
    original = app.test_client()
    enroll(original, account)
    raw = original.get_cookie(trusted_devices.COOKIE_NAME).value
    barrier = Barrier(2)
    authenticate = security.authenticate_user

    def authenticate_together(*args, **kwargs):
        user = authenticate(*args, **kwargs)
        barrier.wait(timeout=10)
        return user

    monkeypatch.setattr(security, 'authenticate_user', authenticate_together)

    def sign_in(index):
        browser = app.test_client()
        browser.set_cookie(trusted_devices.COOKIE_NAME, raw)
        return browser.post('/auth/login', json=CREDENTIALS,
                            environ_overrides={'REMOTE_ADDR': f'192.0.2.{index+1}'})

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(sign_in, range(2)))
    assert sorted(response.status_code for response in responses) == [200, 202]
    with session_store.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM trusted_devices').fetchone()[0] == 1


@pytest.mark.parametrize('path,payload', [
    ('/auth/login', {**CREDENTIALS, 'remember_device': 'true'}),
    ('/auth/mfa/confirm', {'code': '123456', 'remember_device': 1}),
])
def test_remember_device_requires_a_boolean_choice(client, path, payload):
    assert client.post(path, json=payload).status_code == 400
    assert client.get_cookie(trusted_devices.COOKIE_NAME) is None


def test_credential_change_after_mfa_cannot_issue_a_fresh_device_proof(client, account, monkeypatch):
    issue = trusted_devices.issue

    def change_password_then_issue(user, tenant):
        AccountService(client.application.container.storage).update_account(
            'EXAMPLE', account[0]['id'], {'password': 'Changed-device-proof-password-456'})
        return issue(user, tenant)

    monkeypatch.setattr(trusted_devices, 'issue', change_password_then_issue)
    challenge = client.post('/auth/login', json={**CREDENTIALS, 'remember_device': True})
    assert challenge.status_code == 202
    response = client.post('/auth/mfa/confirm', json={
        'code': pyotp.TOTP(challenge.json['mfa']['setup_key']).at(account[1][0]),
        'remember_device': True,
    })
    assert response.status_code == 401
    assert client.get_cookie(trusted_devices.COOKIE_NAME) is None
    assert client.get('/admin/api/catalog').status_code == 401
    with session_store.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM management_sessions').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM trusted_devices').fetchone()[0] == 0
