from __future__ import annotations

from service.security import generate_totp_secret, generate_totp_token


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
    }
    with client.session_transaction() as sess:
        assert sess["_csrf"] != "csrf_before_login"
        assert "untrusted_marker" not in sess
        assert "totp_secret" not in sess["user"]
        assert sess.permanent is True


def test_legacy_admin_login_never_serializes_totp_secret(client, monkeypatch):
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

    assert response.status_code == 302
    with client.session_transaction() as sess:
        assert sess["user"]["email"] == "owner@example.test"
        assert "totp_secret" not in sess["user"]


def test_login_throttle_blocks_repeated_failures(client):
    for _ in range(8):
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
    assert blocked.get_json()["error"] == "try_again_later"


def test_logout_clears_the_full_authenticated_session(client):
    with client.session_transaction() as sess:
        sess["user"] = {"id": "owner", "roles": ["business_owner"], "tenant": "EXAMPLE"}
        sess["admin_session_id"] = "owner"
        sess["_csrf"] = "csrf_token"

    response = client.post("/admin/logout?tenant=EXAMPLE")

    assert response.status_code == 302
    with client.session_transaction() as sess:
        assert not sess
