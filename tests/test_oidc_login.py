"""Offline provider responses exercise signed tokens and existing account boundaries."""
import hashlib
import json
import time
from urllib.parse import parse_qs, urlsplit

import jwt
import pyotp
import pytest

from service import oidc_login, session_store
from service.account_service import AccountService

_TENANT = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'


@pytest.fixture
def oidc(client, monkeypatch):
    from routes.oidc_routes import bp
    if bp.name not in client.application.blueprints:
        client.application.register_blueprint(bp)
    for name in ('GOOGLE', 'MICROSOFT'):
        monkeypatch.setenv('V7_' + name + '_CLIENT_ID', name.lower() + '-unit-client')
        monkeypatch.setenv('V7_' + name + '_CLIENT_SECRET', 'unit-provider-secret')
    monkeypatch.setenv('V7_MICROSOFT_TENANT', 'common')
    # Rate limiting has separate route tests; flows below intentionally exercise retries.
    monkeypatch.setattr(session_store, 'allow_login', lambda ip: True)
    AccountService(client.application.container.storage).create_account('EXAMPLE', {
        'email': 'oidc-owner@example.test', 'password': 'Provider-test-password-123',
        'roles': ['business_owner'],
    })
    login = client.post('/auth/login', json={'email': 'oidc-owner@example.test',
        'password': 'Provider-test-password-123', 'tenant': 'EXAMPLE'})
    assert login.status_code == 202
    secret = login.json['mfa']['setup_key']
    assert client.post('/auth/mfa/confirm', json={'code': pyotp.TOTP(secret).now()}).status_code == 200
    return client, secret


@pytest.fixture(scope='module')
def signing_key():
    from cryptography.hazmat.primitives.asymmetric import rsa
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _begin(client, provider='google', intent='link', **data):
    response = client.post(f'/auth/oidc/{provider}/start', json={'intent': intent, 'tenant': 'EXAMPLE', **data})
    assert response.status_code == 200, response.json
    query = parse_qs(urlsplit(response.json['authorization_url']).query)
    return query


def _mock_token(monkeypatch, signing_key, query, provider='google', *, claims=None, header=None, key_fields=None):
    now = int(time.time())
    issuer = 'https://accounts.google.com' if provider == 'google' else f'https://login.microsoftonline.com/{_TENANT}/v2.0'
    payload = {'iss': issuer, 'aud': provider + '-unit-client', 'sub': 'provider-subject',
               'exp': now + 3600, 'iat': now, 'nonce': query['nonce'][0],
               'email': 'oidc-owner@example.test', 'email_verified': True}
    if provider == 'microsoft':
        payload.update(tid=_TENANT, ver='2.0')
    payload.update(claims or {})
    token = jwt.encode(payload, signing_key, algorithm='RS256', headers={'kid': 'unit-key', **(header or {})})
    key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key()))
    key.update(kid='unit-key', use='sig', alg='RS256')
    if provider == 'microsoft':
        key['issuer'] = 'https://login.microsoftonline.com/{tenantid}/v2.0'
    key.update(key_fields or {})
    monkeypatch.setattr(oidc_login, '_exchange', lambda config, code, verifier: token)
    monkeypatch.setattr(oidc_login, '_http_json', lambda method, url, **kwargs: {'keys': [key]})
    return token


def _callback(client, query, provider='google', **params):
    return client.get(f'/auth/oidc/{provider}/callback', query_string={
        'state': query['state'][0], 'code': 'unit-authorization-code', **params,
    })


def _rows(table):
    with session_store.connection() as db:
        return db.execute('SELECT * FROM ' + table).fetchall()


def test_missing_provider_credentials_are_disabled_and_fail_closed(client, monkeypatch):
    from routes.oidc_routes import bp
    if bp.name not in client.application.blueprints:
        client.application.register_blueprint(bp)
    for provider in ('GOOGLE', 'MICROSOFT'):
        monkeypatch.delenv('V7_' + provider + '_CLIENT_ID', raising=False)
        monkeypatch.delenv('V7_' + provider + '_CLIENT_SECRET', raising=False)
    status = client.get('/auth/oidc/providers')
    assert status.status_code == 200
    assert all(not row['configured'] and not row['linked'] for row in status.json['providers'])
    response = client.post('/auth/oidc/google/start', json={'intent': 'login'})
    assert response.status_code == 400 and response.json['error'] == 'provider_not_configured'


@pytest.mark.parametrize('provider', ['google', 'microsoft'])
def test_explicit_link_then_provider_login_keeps_mfa(oidc, monkeypatch, signing_key, provider):
    client, secret = oidc
    query = _begin(client, provider)
    assert query['response_type'] == ['code'] and query['code_challenge_method'] == ['S256']
    assert query['redirect_uri'] == [f'http://localhost:10000/auth/oidc/{provider}/callback']
    with client.session_transaction() as state:
        assert not any(key in state for key in ('verifier', 'nonce', 'id_token', 'access_token'))
    _mock_token(monkeypatch, signing_key, query, provider)
    result = _callback(client, query, provider)
    assert result.status_code == 303 and result.location == f'/console/?oidc=linked&provider={provider}'
    assert len(_rows('oidc_links')) == 1 and _rows('oidc_states') == []
    assert next(row for row in client.get('/auth/oidc/providers').json['providers'] if row['id'] == provider)['linked']
    assert 'unit-provider-secret' not in client.get('/auth/oidc/providers').text
    client.post('/auth/logout')
    query = _begin(client, provider, 'login')
    _mock_token(monkeypatch, signing_key, query, provider)
    result = _callback(client, query, provider)
    assert result.location == f'/console/?oidc=mfa_required&provider={provider}'
    state = client.get('/auth/session').json
    assert state['user'] is None and state['mfa']['enrollment'] is False
    assert client.get('/admin/api/catalog').status_code == 401
    # Enrollment spent the current step; a fresh allowed skew step proves normal MFA continuation.
    response = client.post('/auth/mfa/confirm', json={'code': pyotp.TOTP(secret).at(time.time() + 30)})
    assert response.status_code == 200 and response.json['user']['tenant'] == 'EXAMPLE'


def test_email_match_cannot_automatically_link_or_sign_in(oidc, monkeypatch, signing_key):
    client, _ = oidc
    client.post('/auth/logout')
    query = _begin(client, intent='login')
    _mock_token(monkeypatch, signing_key, query)
    result = _callback(client, query)
    assert result.location == '/console/?oidc=not_linked&provider=google'
    assert _rows('oidc_links') == []
    assert client.get('/auth/session').json['mfa'] is None
    assert client.get('/admin/api/catalog').status_code == 401


@pytest.mark.parametrize('claims', [
    {'iss': 'https://attacker.example'}, {'aud': 'other-client'}, {'nonce': 'wrong'},
    {'sub': ''}, {'exp': 1}, {'iat': 1}, {'azp': 'other-client'},
    {'aud': ['google-unit-client', 'other-client']}, {'iat': True},
])
def test_invalid_signed_claims_cannot_create_link(oidc, monkeypatch, signing_key, claims):
    client, _ = oidc
    query = _begin(client)
    _mock_token(monkeypatch, signing_key, query, claims=claims)
    result = _callback(client, query)
    assert result.location == '/console/?oidc=failed&provider=google'
    assert _rows('oidc_links') == [] and _rows('oidc_states') == []


@pytest.mark.parametrize('claims,key_fields', [
    ({'tid': 'not-a-guid'}, {}),
    ({'iss': f'https://login.microsoftonline.com/{_TENANT}/'}, {}),
    ({'ver': '1.0'}, {}),
    ({}, {'issuer': 'https://login.microsoftonline.com/11111111-2222-3333-4444-555555555555/v2.0'}),
    ({}, {'issuer': None}),
])
def test_microsoft_requires_matching_tenant_token_and_signing_key_issuer(oidc, monkeypatch, signing_key, claims, key_fields):
    client, _ = oidc
    query = _begin(client, 'microsoft')
    _mock_token(monkeypatch, signing_key, query, 'microsoft', claims=claims, key_fields=key_fields)
    result = _callback(client, query, 'microsoft')
    assert result.location == '/console/?oidc=failed&provider=microsoft'
    assert _rows('oidc_links') == []


def test_token_signature_and_allowed_algorithm_are_verified(oidc, monkeypatch, signing_key):
    from cryptography.hazmat.primitives.asymmetric import rsa
    client, _ = oidc
    query = _begin(client)
    _mock_token(monkeypatch, signing_key, query)
    wrong = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(wrong.public_key()))
    key.update(kid='unit-key')
    monkeypatch.setattr(oidc_login, '_http_json', lambda *args, **kwargs: {'keys': [key]})
    assert _callback(client, query).location == '/console/?oidc=failed&provider=google'
    query = _begin(client)
    token = jwt.encode({'iss': 'https://accounts.google.com'}, 'unit-hmac-secret-longer-than-thirty-two-bytes',
                       algorithm='HS256', headers={'kid': 'unit-key'})
    monkeypatch.setattr(oidc_login, '_exchange', lambda *args: token)
    assert _callback(client, query).location == '/console/?oidc=failed&provider=google'
    assert _rows('oidc_links') == []


def test_state_is_browser_bound_and_single_use(oidc, monkeypatch, signing_key):
    client, _ = oidc
    query = _begin(client)
    _mock_token(monkeypatch, signing_key, query)
    other = client.application.test_client()
    assert _callback(other, query).location == '/console/?oidc=failed&provider=google'
    assert len(_rows('oidc_states')) == 1
    assert _callback(client, query).location == '/console/?oidc=linked&provider=google'
    assert _callback(client, query).location == '/console/?oidc=failed&provider=google'
    assert len(_rows('oidc_links')) == 1


def test_link_requires_same_live_management_session_after_provider_exchange(oidc, monkeypatch, signing_key):
    client, _ = oidc
    query = _begin(client)
    token = _mock_token(monkeypatch, signing_key, query)
    def revoke_during_exchange(*args):
        from flask import session
        session_store.revoke(session['management_token'])
        return token
    monkeypatch.setattr(oidc_login, '_exchange', revoke_during_exchange)
    assert _callback(client, query).location == '/console/?oidc=failed&provider=google'
    assert _rows('oidc_links') == []


@pytest.mark.parametrize('intent', [None, [], {}, False, 'unknown'])
def test_invalid_start_body_fails_without_state_or_links(oidc, intent):
    client, _ = oidc
    response = client.post('/auth/oidc/google/start', json={'intent': intent})
    assert response.status_code == 400 and response.json['error'] == 'invalid_oidc_request'


def test_link_and_disconnect_require_authentication_and_csrf(oidc):
    client, _ = oidc
    with client.session_transaction() as state:
        csrf = state['_csrf']
    response = client.delete('/auth/oidc/google/link', headers={'X-CSRF-Token': csrf + 'wrong'})
    assert response.status_code == 403
    client.post('/auth/logout')
    assert client.post('/auth/oidc/google/start', json={'intent': 'link'}).status_code == 401
    assert client.delete('/auth/oidc/google/link').status_code == 401


def test_disconnect_removes_only_current_accounts_links(oidc, monkeypatch, signing_key):
    client, _ = oidc
    query = _begin(client)
    _mock_token(monkeypatch, signing_key, query)
    assert _callback(client, query).location == '/console/?oidc=linked&provider=google'
    with session_store.connection() as db:
        db.execute('INSERT INTO oidc_links VALUES (?,?,?,?,?,?,?)',
                   ('google', 'google-unit-client', 'https://accounts.google.com', 'another-subject',
                    '["another","another@example.test","EXAMPLE"]', '{}', time.time()))
    assert client.delete('/auth/oidc/google/link').status_code == 200
    rows = _rows('oidc_links')
    assert len(rows) == 1 and rows[0][3] == 'another-subject'


def test_provider_subject_cannot_be_claimed_by_second_account(oidc, monkeypatch, signing_key):
    from tests.conftest import set_test_identity
    client, _ = oidc
    query = _begin(client)
    _mock_token(monkeypatch, signing_key, query)
    assert _callback(client, query).location == '/console/?oidc=linked&provider=google'
    other = client.application.test_client()
    with other.session_transaction() as state:
        set_test_identity(other, state, {'id': 'another@example.test', 'email': 'another@example.test',
                                       'roles': ['business_owner'], 'tenant': 'EXAMPLE'})
    query = _begin(other)
    _mock_token(monkeypatch, signing_key, query)
    assert _callback(other, query).location == '/console/?oidc=failed&provider=google'
    assert len(_rows('oidc_links')) == 1


def test_flow_binds_configuration_and_expiry(oidc, monkeypatch, signing_key):
    client, _ = oidc
    query = _begin(client)
    _mock_token(monkeypatch, signing_key, query)
    monkeypatch.setenv('V7_GOOGLE_CLIENT_ID', 'changed-client')
    assert _callback(client, query).location == '/console/?oidc=failed&provider=google'
    monkeypatch.setenv('V7_GOOGLE_CLIENT_ID', 'google-unit-client')
    query = _begin(client)
    _mock_token(monkeypatch, signing_key, query)
    with session_store.connection() as db:
        db.execute('UPDATE oidc_states SET expires=?', (time.time() - 1,))
    assert _callback(client, query).location == '/console/?oidc=failed&provider=google'
    assert _rows('oidc_links') == []


def test_exchange_sends_pkce_and_exact_callback_to_fixed_endpoint(oidc, monkeypatch):
    client, _ = oidc
    query = _begin(client)
    with session_store.connection() as db:
        verifier = db.execute('SELECT verifier FROM oidc_states').fetchone()[0]
    import base64
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    assert query['code_challenge'] == [expected]
    received = {}
    class Response:
        status_code = 200
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def iter_content(self, size):
            yield b'{"id_token":"unit-id-token","access_token":"discarded"}'
    def request(method, url, **kwargs):
        received.update(method=method, url=url, **kwargs)
        return Response()
    monkeypatch.setattr(oidc_login.requests, 'request', request)
    with client.application.app_context():
        token = oidc_login._exchange(oidc_login._provider('google'), 'unit-code', verifier)
    assert token == 'unit-id-token'
    assert received['url'] == 'https://oauth2.googleapis.com/token'
    assert received['data']['code_verifier'] == verifier
    assert received['data']['redirect_uri'] == query['redirect_uri'][0]
    assert received['allow_redirects'] is False and received['timeout'] == (5, 15)


def test_disabled_linked_account_cannot_start_mfa_or_get_a_session(oidc, monkeypatch, signing_key):
    client, _ = oidc
    query = _begin(client)
    _mock_token(monkeypatch, signing_key, query)
    assert _callback(client, query).location == '/console/?oidc=linked&provider=google'
    identity = client.get('/auth/session').json['user']
    client.post('/auth/logout')
    AccountService(client.application.container.storage).update_account('EXAMPLE', identity['id'], {'active': False})
    query = _begin(client, intent='login')
    _mock_token(monkeypatch, signing_key, query)
    assert _callback(client, query).location == '/console/?oidc=failed&provider=google'
    assert client.get('/auth/session').json['mfa'] is None
    assert client.get('/admin/api/catalog').status_code == 401


def test_linked_business_subject_cannot_select_another_tenant(oidc, monkeypatch, signing_key):
    from service.tenant_service import TenantService
    client, _ = oidc
    query = _begin(client)
    _mock_token(monkeypatch, signing_key, query)
    assert _callback(client, query).location == '/console/?oidc=linked&provider=google'
    TenantService(client.application.container.storage).create_tenant('OTHER', 'Other business')
    client.post('/auth/logout')
    query = _begin(client, intent='login', tenant='OTHER')
    _mock_token(monkeypatch, signing_key, query)
    assert _callback(client, query).location == '/console/?oidc=failed&provider=google'
    assert client.get('/auth/session').json['mfa'] is None
    assert client.get('/admin/api/catalog?tenant=OTHER').status_code == 401


def test_linked_oidc_first_factor_rotates_same_account_device_without_extending_expiry(oidc, monkeypatch, signing_key):
    from service import trusted_devices
    from service.security import authenticate_user
    client, _ = oidc
    query = _begin(client)
    _mock_token(monkeypatch, signing_key, query)
    assert _callback(client, query).location == '/console/?oidc=linked&provider=google'
    with client.application.test_request_context():
        user = authenticate_user(client.application.container, email='oidc-owner@example.test',
                                 password='Provider-test-password-123', tenant='EXAMPLE')
        device, expires = trusted_devices.issue(user, 'EXAMPLE')
    client.set_cookie(trusted_devices.COOKIE_NAME, device)
    with client.session_transaction() as state:
        session_store.revoke(state['management_token'])
        state.clear()
    query = _begin(client, intent='login')
    _mock_token(monkeypatch, signing_key, query)
    response = _callback(client, query)
    assert response.location == '/console/?oidc=signed_in&provider=google'
    rotated = client.get_cookie(trusted_devices.COOKIE_NAME).value
    assert rotated != device
    assert client.get('/auth/session').json['user']['email'] == 'oidc-owner@example.test'
    assert client.get('/admin/api/catalog').status_code == 200
    rows = _rows('trusted_devices')
    assert len(rows) == 1 and rows[0][0] == hashlib.sha256(rotated.encode()).hexdigest()
    assert rows[0][1] == oidc_login.account_key(user) and rows[0][3] == expires
