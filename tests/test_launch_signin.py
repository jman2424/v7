"""Launch checks for Google and Microsoft sign-in: no account creation, no approval bypass, safe expiry."""
import time

import pytest
import test_oidc_login as helpers

from service import oidc_login
from service.account_service import AccountService

oidc = helpers.oidc
signing_key = helpers.signing_key


@pytest.mark.parametrize('provider', ['google', 'microsoft'])
def test_unknown_provider_user_gets_no_account_session_or_route_to_payment(oidc, monkeypatch, signing_key, provider):
    client, _ = oidc
    client.post('/auth/logout')
    accounts_before = AccountService(client.application.container.storage).list_accounts('EXAMPLE')
    tenants_before = client.application.container.storage.tenant_keys()
    query = helpers._begin(client, provider, 'login')
    helpers._mock_token(monkeypatch, signing_key, query, provider,
                        claims={'sub': 'never-seen-before', 'email': 'stranger@example.test'})
    result = helpers._callback(client, query, provider)
    assert result.status_code == 303 and result.location == f'/console/?oidc=not_linked&provider={provider}'
    # No account, business or link was created, and the browser is not signed in.
    assert AccountService(client.application.container.storage).list_accounts('EXAMPLE') == accounts_before
    assert client.application.container.storage.tenant_keys() == tenants_before
    assert helpers._rows('oidc_links') == []
    assert not client.get('/auth/session').json.get('authenticated')
    # So a provider login alone can never reach checkout, activation or the application queue.
    for method, path in (('post', '/billing/checkout'), ('post', '/billing/select-plan'),
                         ('get', '/business-applications/current'), ('get', '/admin/api/activation')):
        response = getattr(client, method)(path, **({'json': {}} if method == 'post' else {}))
        assert response.status_code in {401, 403}, (path, response.status_code)


@pytest.mark.parametrize('provider', ['google', 'microsoft'])
def test_expired_or_future_dated_provider_token_is_refused(oidc, monkeypatch, signing_key, provider):
    client, _ = oidc
    now = int(time.time())
    for claims in ({'exp': now - 600, 'iat': now - 4000}, {'iat': now - 4000}):
        query = helpers._begin(client, provider)
        helpers._mock_token(monkeypatch, signing_key, query, provider, claims=claims)
        assert helpers._callback(client, query, provider).location == f'/console/?oidc=failed&provider={provider}'
    assert helpers._rows('oidc_links') == []


def test_a_sign_in_left_unfinished_for_too_long_cannot_be_completed(oidc, monkeypatch, signing_key):
    client, _ = oidc
    query = helpers._begin(client, 'google')
    helpers._mock_token(monkeypatch, signing_key, query)
    real = time.time
    monkeypatch.setattr(oidc_login.time, 'time', lambda: real() + oidc_login._FLOW_SECONDS + 5)
    assert helpers._callback(client, query).location == '/console/?oidc=failed&provider=google'
    assert helpers._rows('oidc_links') == []


def test_provider_error_or_cancelled_consent_never_signs_in(oidc, monkeypatch, signing_key):
    client, _ = oidc
    query = helpers._begin(client, 'microsoft')
    helpers._mock_token(monkeypatch, signing_key, query, 'microsoft')
    cancelled = client.get('/auth/oidc/microsoft/callback', query_string={'state': query['state'][0], 'error': 'access_denied'})
    assert cancelled.location == '/console/?oidc=failed&provider=microsoft'
    # The state was consumed by the failure: the code cannot be replayed afterwards.
    assert helpers._callback(client, query, 'microsoft').location == '/console/?oidc=failed&provider=microsoft'
    assert helpers._rows('oidc_links') == []


def test_password_sign_in_still_works_when_a_linked_provider_is_removed(oidc, monkeypatch, signing_key):
    """Account recovery: losing the provider never locks the owner out."""
    client, secret = oidc
    query = helpers._begin(client, 'google')
    helpers._mock_token(monkeypatch, signing_key, query)
    assert helpers._callback(client, query).location == '/console/?oidc=linked&provider=google'
    assert client.delete('/auth/oidc/google/link').status_code == 200
    client.post('/auth/logout')
    query = helpers._begin(client, 'google', 'login')
    helpers._mock_token(monkeypatch, signing_key, query)
    assert helpers._callback(client, query).location == '/console/?oidc=not_linked&provider=google'
    login = client.post('/auth/login', json={'email': 'oidc-owner@example.test',
                                             'password': 'Provider-test-password-123', 'tenant': 'EXAMPLE'})
    assert login.status_code in {200, 202}
