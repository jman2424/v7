from __future__ import annotations
import pytest
import json
from tests.conftest import set_test_identity

from service.security import generate_totp_secret, generate_totp_token


def test_unicode_email_is_rejected_without_crashing_configured_login(client, monkeypatch):
    monkeypatch.setenv('ADMIN_USERNAME', 'operator@example.test')
    monkeypatch.setenv('ADMIN_PASSWORD', 'Operator-test-password-123')
    response = client.post('/auth/login', json={
        'email': 'üser@example.test', 'password': 'Unknown-test-password-123', 'tenant': 'EXAMPLE',
    })
    assert response.status_code == 401
    assert response.json['error'] == 'invalid_credentials'


def test_configured_business_account_accepts_full_unicode_password(client, monkeypatch):
    from service.security import hash_password
    password = 'Unicode-test-password-🔐-123'
    monkeypatch.setenv('BUSINESS_USERS_JSON', json.dumps([{
        'id': 'unicode-owner', 'email': 'unicode-owner@example.test', 'tenant': 'EXAMPLE',
        'roles': ['business_owner'], 'password_hash': hash_password(password),
    }]))
    response = client.post('/auth/login', json={
        'email': 'unicode-owner@example.test', 'password': password, 'tenant': 'EXAMPLE',
    })
    assert response.status_code == 202
    assert response.json['mfa_required'] is True
    assert password not in response.text


@pytest.mark.parametrize('source', ['registry', 'environment'])
def test_legacy_account_tenant_alias_preserves_assignment_and_enrollment(client, monkeypatch, source):
    from pathlib import Path
    import os
    from service.security import hash_password
    password = 'Legacy-assignment-test-password-123'
    email = 'legacy-assignment@example.test'
    if source == 'registry':
        Path(os.environ['ADMIN_USERS_FILE']).write_text(json.dumps({'users': [{
            'email': email, 'tenant': 'example', 'role': 'business_owner',
            'password_hash': hash_password(password),
        }]}), encoding='utf-8')
    else:
        monkeypatch.setenv('BUSINESS_USERS_JSON', json.dumps([{
            'id': 'legacy-assignment', 'email': email, 'tenant': 'example',
            'roles': ['business_owner'], 'password_hash': hash_password(password),
        }]))
    challenge = client.post('/auth/login', json={'email': email, 'password': password, 'tenant': 'EXAMPLE'})
    assert challenge.status_code == 202
    confirmed = client.post('/auth/mfa/confirm', json={
        'code': generate_totp_token(challenge.json['mfa']['setup_key']),
    })
    assert confirmed.status_code == 200
    assert confirmed.json['user']['tenant'] == 'EXAMPLE'
    from service.tenant_service import TenantService
    TenantService(client.application.container.storage).create_tenant('OTHER', 'Other test company')
    assert client.post('/auth/login', json={
        'email': email, 'password': password, 'tenant': 'OTHER',
    }).status_code == 401


def test_linked_account_resolution_requires_immutable_id_email_and_tenant(app):
    from service.account_service import AccountService
    from service.security import resolve_linked_account
    service = AccountService(app.container.storage)
    account = service.create_account('EXAMPLE', {
        'email': 'linked-owner@example.test', 'password': 'Linked-owner-test-password-123',
        'roles': ['business_owner'],
    })
    reference = {'id': account['id'], 'email': account['email'], 'tenant': 'EXAMPLE'}
    with app.app_context():
        resolved = resolve_linked_account(reference)
        assert resolved['roles'] == ['business_owner'] and resolved['tenant'] == 'EXAMPLE'
        for changed in [{'id': 'different-id'}, {'email': 'different@example.test'}, {'tenant': 'OTHER'}, {'tenant': None}]:
            assert resolve_linked_account({**reference, **changed}) is None
        service.update_account('EXAMPLE', account['id'], {'active': False})
        assert resolve_linked_account(reference) is None


def test_disabled_registry_link_never_falls_back_to_environment_admin(app, monkeypatch):
    from pathlib import Path
    import os
    from service.security import hash_password, resolve_linked_account
    email = 'linked-operator@example.test'
    monkeypatch.setenv('ADMIN_USERNAME', email)
    monkeypatch.setenv('ADMIN_PASSWORD', 'Linked-operator-test-password-123')
    Path(os.environ['ADMIN_USERS_FILE']).write_text(json.dumps({'users': [{
        'email': email, 'role': 'platform_admin', 'password_hash': hash_password('Registry-test-password-123'),
        'disabled': True,
    }]}), encoding='utf-8')
    with app.app_context():
        assert resolve_linked_account({'id': 'admin', 'email': email, 'tenant': None}) is None
        assert resolve_linked_account({'id': email, 'email': email, 'tenant': None}) is None


def test_platform_link_resolution_requires_global_reference_and_refreshes_roles(app, monkeypatch):
    from service.security import resolve_linked_account
    monkeypatch.setenv('ADMIN_USERNAME', 'linked-platform@example.test')
    monkeypatch.setenv('ADMIN_PASSWORD', 'Linked-platform-test-password-123')
    reference = {'id': 'admin', 'email': 'linked-platform@example.test', 'tenant': None}
    with app.app_context():
        assert resolve_linked_account(reference)['roles'] == ['platform_admin']
        assert resolve_linked_account({**reference, 'tenant': 'EXAMPLE'}) is None


def test_configured_platform_link_remains_global_after_resolving_its_current_account(app, monkeypatch):
    from service.account_mfa import begin, pending
    from service.security import _revision, hash_password, resolve_linked_account
    reference = {'id': 'configured-operator', 'email': 'configured-operator@example.test', 'tenant': None}
    monkeypatch.setenv('BUSINESS_USERS_JSON', json.dumps([{
        **reference, 'tenant': 'EXAMPLE', 'roles': ['platform_admin'],
        'password_hash': hash_password('Configured-operator-test-password-123'),
        'totp_secret': generate_totp_secret(),
    }]))
    with app.test_request_context():
        user = resolve_linked_account(reference)
        assert user['roles'] == ['platform_admin'] and user['tenant'] is None
        assert _revision({**user, 'tenant': 'OTHER'}) == _revision(user)
        assert begin(user, 'OTHER')['enrollment'] is False
        assert pending()['email'] == reference['email']
        assert resolve_linked_account({**reference, 'tenant': 'EXAMPLE'}) is None


@pytest.mark.parametrize('role', [['platform_admin'], {'platform_admin': True}])
def test_malformed_registry_role_fails_closed_for_password_and_linked_login(client, role):
    from pathlib import Path
    import os
    from service.security import hash_password, resolve_linked_account
    email = 'malformed-role@example.test'
    password = 'Malformed-role-test-password-123'
    Path(os.environ['ADMIN_USERS_FILE']).write_text(json.dumps({'users': [{
        'email': email, 'role': role, 'password_hash': hash_password(password),
    }]}), encoding='utf-8')
    assert client.post('/auth/login', json={
        'email': email, 'password': password, 'tenant': 'EXAMPLE',
    }).status_code == 401
    with client.application.app_context():
        assert resolve_linked_account({'id': email, 'email': email, 'tenant': None}) is None


@pytest.mark.parametrize('length', [254, 255, 320])
def test_login_email_boundary_matches_account_creation(client, monkeypatch, length):
    attempts = []
    monkeypatch.setattr('service.security.authenticate_user',
                        lambda container, **credentials: attempts.append(credentials) or None)
    email = 'a' * (length - len('@example.test')) + '@example.test'
    response = client.post('/auth/login', json={
        'email': email, 'password': 'Account-test-password-123', 'tenant': 'EXAMPLE',
    })
    assert response.status_code == (401 if length == 254 else 400)
    assert len(attempts) == (1 if length == 254 else 0)


def test_api_login_replaces_anonymous_session_and_excludes_server_secrets(client, monkeypatch):
    secret = generate_totp_secret()
    monkeypatch.setenv("ADMIN_USERNAME", "owner@example.test")
    monkeypatch.setenv("ADMIN_PASSWORD", "strong-test-password")
    monkeypatch.setenv("ADMIN_TOTP_SECRET", secret)

    with client.session_transaction() as sess:
        sess["untrusted_marker"] = "present"
        sess["_csrf"] = "csrf_before_login"

    response = client.post(
        "/auth/login",
        json={
            "email": "owner@example.test",
            "password": "strong-test-password",
            "tenant": "EXAMPLE",
            "totp": generate_totp_token(secret),
        },
    )

    assert response.status_code == 200
    assert response.get_json()["user"] == {
        "id": "admin",
        "email": "owner@example.test",
        "roles": ["platform_admin"],
        "tenant": "EXAMPLE",
        "permissions": ["view_costs", "view_subscriptions"],
    }
    with client.session_transaction() as sess:
        assert sess["_csrf"] != "csrf_before_login"
        assert "untrusted_marker" not in sess
        assert "totp_secret" not in sess["user"]
        assert sess.permanent is True


def test_retired_admin_login_does_not_process_credentials(client, monkeypatch):
    secret = generate_totp_secret()
    monkeypatch.setenv("ADMIN_USERNAME", "owner@example.test")
    monkeypatch.setenv("ADMIN_PASSWORD", "strong-test-password")
    monkeypatch.setenv("ADMIN_TOTP_SECRET", secret)

    response = client.post(
        "/admin/login?tenant=EXAMPLE",
        data={
            "email": "owner@example.test",
            "password": "strong-test-password",
            "totp": generate_totp_token(secret),
        },
    )

    assert response.status_code == 303
    with client.session_transaction() as sess:
        assert "user" not in sess
    assert response.headers["Location"] == "/console/"
    assert secret not in response.text


def test_login_throttle_blocks_repeated_failures(client):
    for _ in range(5):
        response = client.post(
            "/auth/login",
            json={"email": "unknown@example.test", "password": "wrong", "tenant": "EXAMPLE"},
        )
        assert response.status_code == 401

    blocked = client.post(
        "/auth/login",
        json={"email": "unknown@example.test", "password": "wrong", "tenant": "EXAMPLE"},
    )

    assert blocked.status_code == 429
    assert blocked.get_json()["error"] == "too_many_requests"


def test_logout_clears_the_full_authenticated_session(client):
    with client.session_transaction() as sess:
        set_test_identity(client, sess, {"id": "owner", "roles": ["business_owner"], "tenant": "EXAMPLE"})
        sess["admin_session_id"] = "owner"
        sess["_csrf"] = "csrf_token"

    response = client.post("/admin/logout?tenant=EXAMPLE")

    assert response.status_code == 303
    with client.session_transaction() as sess:
        assert not sess
