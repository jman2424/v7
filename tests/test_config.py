from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest

from app.config import load_settings
from services.security import hash_password


def test_production_rejects_default_secret_key():
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        load_settings({"ENVIRONMENT": "production", "SECRET_KEY": "change-me"})


def test_https_base_url_enables_secure_session_cookie():
    from app import create_app

    app = create_app({"BASE_URL": "https://platform.example.test", "SECRET_KEY": "test-secret"})
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert app.config["SESSION_COOKIE_SECURE"] is True


def test_render_runtime_enables_secure_session_cookie(monkeypatch):
    from app import create_app

    monkeypatch.setenv("RENDER", "true")
    app = create_app({"BASE_URL": "http://localhost:10000", "SECRET_KEY": "test-secret"})
    assert app.config["SESSION_COOKIE_SECURE"] is True


def test_whatsapp_cloud_settings_are_loaded():
    settings = load_settings(
        {
            "SECRET_KEY": "test-secret",
            "WHATSAPP_TOKEN": "token",
            "WHATSAPP_PHONE_ID": "phone-id",
            "WHATSAPP_API_URL": "https://api.example.test",
        }
    )
    assert settings.WHATSAPP_TOKEN == "token"
    assert settings.WHATSAPP_PHONE_ID == "phone-id"
    assert settings.WHATSAPP_API_URL == "https://api.example.test"


def test_gunicorn_configuration_uses_render_port(monkeypatch):
    monkeypatch.setenv("PORT", "15321")
    monkeypatch.delenv("BIND", raising=False)

    config = runpy.run_path(Path(__file__).resolve().parents[1] / "gunicorn.conf.py")

    assert config["bind"] == "0.0.0.0:15321"


def test_auth_api_session_returns_tenant_scoped_identity(client, monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "owner@example.test")
    monkeypatch.setenv("ADMIN_PASSWORD", "strong-test-password")

    login = client.post(
        "/auth/login",
        json={"email": "owner@example.test", "password": "strong-test-password", "tenant": "EXAMPLE"},
    )
    assert login.status_code == 200
    assert login.get_json()["user"]["tenant"] == "EXAMPLE"
    assert login.get_json()["csrf_token"]

    current = client.get("/auth/session")
    assert current.status_code == 200
    assert current.get_json()["user"]["email"] == "owner@example.test"


def test_business_owner_login_is_bound_to_its_tenant(client, monkeypatch):
    owner = {
        "email": "owner@example.test",
        "tenant": "EXAMPLE",
        "password_hash": hash_password("owner-test-password"),
        "roles": ["business_owner"],
    }
    monkeypatch.setenv("BUSINESS_USERS_JSON", json.dumps([owner]))

    allowed = client.post(
        "/auth/login",
        json={"email": owner["email"], "password": "owner-test-password", "tenant": "EXAMPLE"},
    )
    assert allowed.status_code == 200
    assert allowed.get_json()["user"]["roles"] == ["business_owner"]

    rejected = client.post(
        "/auth/login",
        json={"email": owner["email"], "password": "owner-test-password", "tenant": "TARIQ"},
    )
    assert rejected.status_code in {401, 404}
