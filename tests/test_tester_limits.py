from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock

import pytest

from service import tester_limits, session_store, subscriptions
from tests.conftest import set_test_identity
from tests.test_widget_tenancy import _add_tenant


@pytest.fixture
def demo(app, monkeypatch):
    app.container.settings = replace(app.container.settings, PUBLIC_WIDGET_TENANT='EXAMPLE')
    handler = Mock(return_value={'reply': 'ok', 'intent': 'faq'})
    monkeypatch.setattr(app.container.handler, 'handle', handler)
    return handler


def identity(client, role='business_owner'):
    with client.session_transaction() as state:
        set_test_identity(client, state, {'id': 'owner', 'email': 'owner@example.test',
                                        'tenant': 'EXAMPLE', 'roles': [role]})


def test_anonymous_limit_survives_new_sessions_and_ignores_paid_flags(app, client, demo):
    for i in range(10):
        response = client.post('/chat_api', json={'tenant': 'EXAMPLE', 'message': 'hello',
                                                'paid': True, 'channel': 'test'})
        assert response.status_code == 200, response.json
    fresh = app.test_client()
    response = fresh.post('/chat_api', json={'tenant': 'EXAMPLE', 'message': 'hello'},
                          headers={'X-Forwarded-For': '203.0.113.2'})
    assert response.status_code == 429, response.json
    assert response.json['error'] == 'tester_daily_limit'
    assert response.json['limit'] == 10
    assert response.headers['Retry-After'] == str(response.json['retry_after'])
    assert demo.call_count == 10
    assert fresh.post('/chat_api', json={'tenant': 'EXAMPLE', 'message': 'hello'},
                      environ_overrides={'REMOTE_ADDR': '203.0.113.3'}).status_code == 200


@pytest.mark.parametrize('status,invoice', [('active', False), ('canceled', True), ('past_due', True)])
def test_unpaid_or_inactive_account_not_exempt(client, demo, status, invoice):
    identity(client)
    with subscriptions.connection('EXAMPLE') as db:
        db.execute("INSERT INTO billing_contracts(tenant,kind,ref,status,subscription) VALUES('EXAMPLE','platform','ref',?,'sub_test')", (status,))
        if invoice:
            db.execute("INSERT INTO billing_invoices VALUES('invoice','EXAMPLE','platform','2026-10',1,NULL,9900,9900,0,'paid','[]',NULL)")
    for _ in range(10):
        assert client.post('/admin/api/test-agent?tenant=EXAMPLE', json={'message': 'hello'}).status_code == 200
    assert client.post('/admin/api/test-agent?tenant=EXAMPLE', json={'message': 'hello'}).status_code == 429


def test_blocked_request_has_no_agent_or_usage_side_effects(client, demo, monkeypatch):
    from routes import webchat_routes
    from service import plan_usage
    for _ in range(10):
        assert client.post('/chat_api', json={'tenant': 'EXAMPLE', 'message': 'hello'}).status_code == 200
    lead = Mock()
    allowance = Mock()
    monkeypatch.setattr(webchat_routes, 'upsert_lead', lead)
    monkeypatch.setattr(plan_usage, 'use_resource', allowance)
    assert client.post('/chat_api', json={'tenant': 'EXAMPLE', 'message': 'hello'}).status_code == 429
    assert demo.call_count == 10
    assert not lead.called and not allowance.called


def test_provider_failures_cannot_bypass_attempt_cap(client, demo):
    identity(client)
    demo.side_effect = RuntimeError('provider failed')
    for _ in range(10):
        assert client.post('/admin/api/test-agent?tenant=EXAMPLE', json={'message': 'hello'}).status_code == 503
    assert client.post('/admin/api/test-agent?tenant=EXAMPLE', json={'message': 'hello'}).status_code == 429
    assert demo.call_count == 10


def test_customer_widgets_are_not_capped(app, client, demo, monkeypatch):
    _add_tenant(app)
    other = Mock(return_value={'reply': 'customer', 'intent': 'faq'})
    monkeypatch.setattr(app.container.for_tenant('ALT').handler, 'handle', other)
    for _ in range(12):
        assert client.post('/chat_api', json={'tenant': 'ALT', 'message': 'hello'}).status_code == 200
    assert other.call_count == 12


def test_forged_cookie_identity_cannot_grant_paid_exemption(app, demo):
    with app.test_request_context('/'):
        from flask import session
        session['user'] = {'id': 'fake', 'roles': ['platform_admin'], 'tenant': 'EXAMPLE'}
        for _ in range(10):
            assert tester_limits.enforce('EXAMPLE') is None
        assert tester_limits.enforce('EXAMPLE').status_code == 429


def test_revoked_session_cannot_grant_paid_exemption(app, client, demo):
    identity(client, 'platform_admin')
    with client.session_transaction() as state:
        state['_csrf'] = 'test-request-token'
        session_store.revoke(state['management_token'])
    for _ in range(10):
        assert client.post('/chat_api', json={'tenant': 'EXAMPLE', 'message': 'hello'}).status_code == 200
    assert client.post('/chat_api', json={'tenant': 'EXAMPLE', 'message': 'hello'}).status_code == 429


def test_invalid_messages_and_conversation_tokens_do_not_consume_quota(client, demo):
    for _ in range(11):
        assert client.post('/chat_api', json={'tenant': 'EXAMPLE', 'message': ''}).status_code == 400
        assert client.post('/chat_api', json={'tenant': 'EXAMPLE', 'message': 'hello',
                                             'conversation_token': 'forged'}).status_code == 403
    for _ in range(10):
        assert client.post('/chat_api', json={'tenant': 'EXAMPLE', 'message': 'hello'}).status_code == 200
    assert demo.call_count == 10


def test_account_quota_shared_across_console_homepage_and_networks(client, demo):
    identity(client)
    for _ in range(5):
        assert client.post('/admin/api/test-agent?tenant=EXAMPLE', json={'message': 'hello'}).status_code == 200
    for i in range(5):
        assert client.post('/chat_api', json={'tenant': 'EXAMPLE', 'message': 'hello'},
                           environ_overrides={'REMOTE_ADDR': f'203.0.113.{i}'}).status_code == 200
    response = client.post('/admin/api/test-agent?tenant=EXAMPLE', json={'message': 'hello'})
    assert response.status_code == 429, response.json
    assert response.json['error'] == 'tester_daily_limit'
    assert demo.call_count == 10


@pytest.mark.parametrize('paid,role', [(True, 'business_owner'), (False, 'platform_admin')])
def test_verified_paid_and_platform_accounts_exempt(client, app, demo, paid, role):
    identity(client, role)
    if paid:
        with subscriptions.connection('EXAMPLE') as db:
            db.execute("INSERT INTO billing_contracts(tenant,kind,ref,status,subscription) VALUES('EXAMPLE','platform','paid-ref','active','sub_verified')")
            db.execute("INSERT INTO billing_invoices VALUES('invoice','EXAMPLE','platform','2026-10',1,NULL,9900,9900,0,'paid','[]',NULL)")
    for _ in range(12):
        assert client.post('/admin/api/test-agent?tenant=EXAMPLE', json={'message': 'hello'}).status_code == 200
    assert demo.call_count == 12


def test_anonymous_does_not_inherit_public_business_paid_status(client, demo):
    with subscriptions.connection('EXAMPLE') as db:
        db.execute("INSERT INTO billing_contracts(tenant,kind,ref,status,subscription) VALUES('EXAMPLE','platform','paid-ref','active','sub_verified')")
        db.execute("INSERT INTO billing_invoices VALUES('invoice','EXAMPLE','platform','2026-10',1,NULL,9900,9900,0,'paid','[]',NULL)")
    for _ in range(10):
        assert client.post('/chat_api', json={'tenant': 'EXAMPLE', 'message': 'hello'}).status_code == 200
    assert client.post('/chat_api', json={'tenant': 'EXAMPLE', 'message': 'hello'}).status_code == 429


def test_daily_reset_and_no_raw_identity_storage(app, demo, monkeypatch):
    today = datetime(2026, 10, 21, 23, 59, tzinfo=timezone.utc)
    monkeypatch.setattr(tester_limits, '_now', lambda: today)
    with app.test_request_context('/', environ_overrides={'REMOTE_ADDR': '203.0.113.5'}):
        for _ in range(10):
            assert tester_limits.enforce('EXAMPLE') is None
        limited = tester_limits.enforce('EXAMPLE')
        assert limited.status_code == 429
        assert limited.json['retry_after'] == 60
        assert limited.json['resets_at'] == '2026-10-22T00:00:00Z'
        assert tester_limits.enforce('EXAMPLE', consume=False).status_code == 429
        monkeypatch.setattr(tester_limits, '_now', lambda: today + timedelta(minutes=1))
        assert tester_limits.enforce('EXAMPLE') is None
    with session_store.connection() as db:
        hashes = [r[0] for r in db.execute('SELECT subject_hash FROM auth_login_failures')]
    assert len(set(hashes)) == 2
    assert all(len(value) == 64 and '203.0.113.5' not in value for value in hashes)


def test_limit_storage_failure_blocks_before_provider(client, demo, monkeypatch, caplog):
    def fail(*args, **kwargs):
        raise RuntimeError('private-IP-203.0.113.5')
    monkeypatch.setattr(session_store, 'reserve_login_attempt', fail)
    response = client.post('/chat_api', json={'tenant': 'EXAMPLE', 'message': 'hello'})
    assert response.status_code == 503
    assert response.json['error'] == 'tester_limit_unavailable'
    assert not demo.called
    assert 'private-IP' not in response.get_data(as_text=True)
    assert 'private-IP' not in caplog.text


def _race(app, tenant):
    def reserve(_):
        with app.test_request_context('/'):
            response = tester_limits.enforce(tenant, console=True)
            assert response is None or response.status_code == 429
            return response is None
    with ThreadPoolExecutor(max_workers=6) as pool:
        assert sum(pool.map(reserve, range(24))) == 10


def test_sqlite_concurrent_daily_limit(app, demo):
    _race(app, 'EXAMPLE')


def test_daily_namespace_does_not_block_login(app, demo):
    with app.test_request_context('/'):
        for _ in range(10):
            assert tester_limits.enforce('EXAMPLE') is None
    unrelated = 'a' * 64
    attempt, retry = session_store.reserve_login_attempt(unrelated, max_attempts=1, window_seconds=300)
    assert attempt and retry == 0
    session_store.reset_login_failures(unrelated)
    with app.test_request_context('/'):
        assert tester_limits.enforce('EXAMPLE').status_code == 429
