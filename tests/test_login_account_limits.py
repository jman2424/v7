"""Account bounds survive different browsers, addresses, workers and challenges."""
import re

from service import session_store
from service.account_service import AccountService
from service.login_limiter import LoginAttemptLimiter, LoginThrottled
from service.security import generate_totp_token
from service.tenant_service import TenantService

import pytest


def _post(client, path, payload, address):
    return client.post(path, json=payload, environ_overrides={'REMOTE_ADDR': address})


def _limit(app, *, maximum=3, window=120):
    app.extensions['auth_login_limiter'] = LoginAttemptLimiter(max_attempts=maximum, window_seconds=window)


def test_account_failures_are_shared_across_addresses_and_limiter_instances(app):
    _limit(app)
    credentials = {'email': 'unknown@example.test', 'password': 'Wrong-test-password', 'tenant': 'EXAMPLE'}
    for index in range(3):
        response = _post(app.test_client(), '/auth/login', credentials, f'192.0.2.{index+1}')
        assert response.status_code == 401
    # A new worker/facade still sees the same account's failures.
    _limit(app)
    blocked = _post(app.test_client(), '/auth/login', {
        **credentials, 'email': ' UNKNOWN@EXAMPLE.TEST ', 'tenant': 'example',
    }, '192.0.2.10')
    assert blocked.status_code == 429
    assert blocked.json['error'] == 'try_again_later'
    assert 0 < blocked.json['retry_after'] <= 120
    with session_store.connection() as db:
        rows = db.execute('SELECT subject_hash FROM auth_login_failures').fetchall()
    assert len(rows) == 3
    assert all(re.fullmatch(r'[a-f0-9]{64}', row[0]) for row in rows)


def test_platform_account_cannot_reset_its_bound_by_selecting_another_tenant(app, monkeypatch):
    _limit(app)
    monkeypatch.setenv('ADMIN_USERNAME', 'operator@example.test')
    monkeypatch.setenv('ADMIN_PASSWORD', 'Operator-test-password-123')
    TenantService(app.container.storage).create_tenant('OTHER', 'Other test company')
    credentials = {'email': 'operator@example.test', 'password': 'Wrong-test-password'}
    for index, tenant in enumerate(['EXAMPLE', 'OTHER', 'EXAMPLE']):
        assert _post(app.test_client(), '/auth/login', {**credentials, 'tenant': tenant},
                     f'192.0.2.{index+1}').status_code == 401
    response = _post(app.test_client(), '/auth/login', {**credentials, 'tenant': 'OTHER'}, '192.0.2.10')
    assert response.status_code == 429 and response.json['error'] == 'try_again_later'


def test_mfa_failures_survive_new_challenges_and_successful_password_checks(app):
    _limit(app)
    AccountService(app.container.storage).create_account('EXAMPLE', {
        'email': 'bounded-mfa@example.test', 'password': 'Bounded-MFA-test-password-123',
        'roles': ['business_owner'],
    })
    credentials = {'email': 'bounded-mfa@example.test', 'password': 'Bounded-MFA-test-password-123',
                   'tenant': 'EXAMPLE'}
    for index in range(3):
        browser = app.test_client()
        address = f'192.0.2.{index+1}'
        assert _post(browser, '/auth/login', credentials, address).status_code == 202
        rejected = _post(browser, '/auth/mfa/confirm', {'code': 'invalid'}, address)
        assert rejected.status_code == 401
    blocked = _post(app.test_client(), '/auth/login', credentials, '192.0.2.10')
    assert blocked.status_code == 429 and blocked.json['error'] == 'try_again_later'


def test_only_completed_mfa_resets_previous_account_failures(app):
    _limit(app)
    AccountService(app.container.storage).create_account('EXAMPLE', {
        'email': 'reset-mfa@example.test', 'password': 'Reset-MFA-test-password-123',
        'roles': ['business_owner'],
    })
    credentials = {'email': 'reset-mfa@example.test', 'password': 'Reset-MFA-test-password-123',
                   'tenant': 'EXAMPLE'}
    browser = app.test_client()
    for index in range(2):
        assert _post(browser, '/auth/login', {**credentials, 'password': 'wrong'},
                     f'192.0.2.{index+1}').status_code == 401
    challenge = _post(browser, '/auth/login', credentials, '192.0.2.3')
    assert challenge.status_code == 202
    with session_store.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM auth_login_failures').fetchone()[0] == 2
    confirmed = _post(browser, '/auth/mfa/confirm', {
        'code': generate_totp_token(challenge.json['mfa']['setup_key']),
    }, '192.0.2.4')
    assert confirmed.status_code == 200
    with session_store.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM auth_login_failures').fetchone()[0] == 0


def test_account_failure_window_expires_without_changing_attempt_count(app, monkeypatch):
    _limit(app, maximum=2, window=30)
    now = session_store.time.time()
    monkeypatch.setattr(session_store.time, 'time', lambda: now)
    credentials = {'email': 'window@example.test', 'password': 'wrong', 'tenant': 'EXAMPLE'}
    for index in range(2):
        assert _post(app.test_client(), '/auth/login', credentials, f'192.0.2.{index+1}').status_code == 401
    blocked = _post(app.test_client(), '/auth/login', credentials, '192.0.2.3')
    assert blocked.status_code == 429 and blocked.json['retry_after'] == 30
    monkeypatch.setattr(session_store.time, 'time', lambda: now+31)
    assert _post(app.test_client(), '/auth/login', credentials, '192.0.2.4').status_code == 401


def test_failed_in_flight_attempt_remains_counted_after_another_login_succeeds(app):
    limiter = LoginAttemptLimiter(max_attempts=1, window_seconds=120)
    with app.app_context():
        subject = limiter.key(tenant='EXAMPLE', identifier='in-flight@example.test')
        reserved = limiter.begin(subject)
        limiter.reset(subject)
        limiter.fail(subject, reserved)
        with pytest.raises(LoginThrottled):
            limiter.begin(subject)
