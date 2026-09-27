from __future__ import annotations
import pytest
from tests.conftest import set_test_identity

from service.security import generate_totp_secret, generate_totp_token


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
