"""Synthetic privacy policy, permission and account-export regressions."""
import json
from dataclasses import replace
from unittest.mock import Mock

import pytest

from routes.privacy_routes import bp
from service import privacy_settings
from tests.conftest import set_test_identity
from tests.test_platform_security import login, platform as platform_fixture

platform = platform_fixture


@pytest.fixture
def privacy_app(platform, monkeypatch):
    app = platform[0]
    if bp.name not in app.blueprints:
        app.register_blueprint(bp)
    for name in ("V7_PRIVACY_CONTROLLER", "V7_PRIVACY_CONTACT_EMAIL", "V7_PRIVACY_RETENTION_DAYS",
                 "V7_PRIVACY_RETENTION_CRITERIA", "V7_PRIVACY_LAWFUL_BASIS", "RENDER",
                 "V7_GOOGLE_CLIENT_ID", "V7_GOOGLE_CLIENT_SECRET", "V7_MICROSOFT_CLIENT_ID",
                 "V7_MICROSOFT_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    return app


def valid_settings(**overrides):
    return {"controller_name": "Synthetic Controller Ltd", "contact_email": "privacy@example.test",
            "retention_days": None, "retention_criteria": "Review records when enquiries are resolved.",
            "lawful_basis": "Business-provided explanation awaiting its own review.", **overrides}


def save(client, settings, csrf):
    current = client.get("/admin/api/privacy?tenant=ALPHA").json
    return client.put("/admin/api/privacy?tenant=ALPHA",
        json={"settings": settings, "revision": current["revision"]}, headers={"X-CSRF-Token": csrf})


@pytest.mark.parametrize("payload", [None, [], "text", 1, True, {"unknown": "value"},
    {"retention_days": True}, {"retention_days": 1.5}, {"retention_days": 0}, {"retention_days": 36501},
    {"controller_name": "x" * 201}, {"controller_name": "Bad\x00name"},
    {"lawful_basis": "Hidden\u202etext"}, {"contact_email": "Not an email"},
    {"contact_email": "name@example.test\r\nBcc: other@example.test"}])
def test_settings_reject_unknown_fields_types_controls_and_bad_email(payload):
    with pytest.raises(ValueError):
        privacy_settings.validate_settings(payload)


def test_empty_details_are_a_draft_without_invented_legal_values(privacy_app):
    response = privacy_app.test_client().get("/privacy")
    assert response.status_code == 200
    assert "Draft" in response.text
    assert "Retention period or criteria not provided" in response.text
    assert "Not provided" in response.text
    assert "legitimate interests" not in response.text
    assert "privacy@example.test" not in response.text


def test_platform_environment_details_do_not_replace_tenant_controller(privacy_app, monkeypatch):
    monkeypatch.setenv("V7_PRIVACY_CONTROLLER", "Platform-only Controller")
    monkeypatch.setenv("V7_PRIVACY_CONTACT_EMAIL", "platform@example.test")
    monkeypatch.setenv("V7_PRIVACY_RETENTION_DAYS", "40")
    monkeypatch.setenv("V7_PRIVACY_LAWFUL_BASIS", "Platform-provided explanation")
    client = privacy_app.test_client()
    assert "Platform-only Controller" in client.get("/privacy").text
    assert "Platform-only Controller" not in client.get("/privacy?tenant=ALPHA").text
    assert "platform@example.test" not in client.get("/privacy?tenant=ALPHA").text


def test_owner_can_save_while_inactive_and_stale_writes_do_not_replace_data(privacy_app, monkeypatch):
    monkeypatch.setattr("service.tenant_access.activation", lambda tenant: {"active": False})
    client = privacy_app.test_client()
    csrf = login(client)
    initial = client.get("/admin/api/privacy?tenant=ALPHA").json
    assert initial["draft"] is True and initial["write_allowed"] is True
    result = save(client, valid_settings(), csrf)
    assert result.status_code == 200
    assert result.json["draft"] is False
    assert result.json["policy_url"] == "/privacy?tenant=ALPHA"
    stale = client.put("/admin/api/privacy?tenant=ALPHA",
        json={"settings": valid_settings(controller_name="Stale value"), "revision": initial["revision"]},
        headers={"X-CSRF-Token": csrf})
    assert stale.status_code == 409
    assert privacy_app.container.storage.read_json("ALPHA", "privacy.json")["controller_name"] == "Synthetic Controller Ltd"


def test_permission_and_csrf_boundaries_for_privacy_settings(privacy_app):
    client = privacy_app.test_client()
    assert client.get("/admin/api/privacy?tenant=ALPHA").status_code == 401
    csrf = login(client)
    assert client.get("/admin/api/privacy?tenant=BETA").status_code == 403
    assert client.put("/admin/api/privacy?tenant=BETA", json={}, headers={"X-CSRF-Token": csrf}).status_code == 403
    current = client.get("/admin/api/privacy").json
    assert client.put("/admin/api/privacy", json={"settings": valid_settings(), "revision": current["revision"]}).status_code == 403
    staff = privacy_app.test_client()
    with staff.session_transaction() as state:
        set_test_identity(staff, state, {"id": "staff", "email": "staff@example.test", "tenant": "ALPHA", "roles": ["business_staff"],
                                       "permissions": ["business_settings.read"]})
        token = state.get("_csrf", "")
    own = staff.get("/admin/api/privacy?tenant=ALPHA")
    assert own.status_code == 200 and own.json["write_allowed"] is False
    token = staff.get("/auth/session").json["csrf_token"]
    assert staff.put("/admin/api/privacy?tenant=ALPHA",
        json={"settings": valid_settings(), "revision": own.json["revision"]}, headers={"X-CSRF-Token": token}).status_code == 403
    admin = privacy_app.test_client()
    token = login(admin, "admin@example.test")
    current = admin.get("/admin/api/privacy?tenant=BETA").json
    assert admin.put("/admin/api/privacy?tenant=BETA",
        json={"settings": valid_settings(controller_name="Beta controller"), "revision": current["revision"]},
        headers={"X-CSRF-Token": token}).status_code == 200


@pytest.mark.parametrize("body", [None, [], "text", True, {}, {"settings": []},
    {"settings": {}, "revision": "bad"}, {"settings": {}, "revision": "0" * 64, "tenant": "BETA"}])
def test_invalid_put_bodies_never_write_or_audit(privacy_app, monkeypatch, body):
    client = privacy_app.test_client()
    csrf = login(client)
    writer = Mock(side_effect=AssertionError("Invalid body reached storage"))
    monkeypatch.setattr(type(privacy_app.container.storage), "_write_json", writer)
    audit = Mock()
    monkeypatch.setattr("routes.privacy_routes.AuditService", audit)
    response = client.put("/admin/api/privacy?tenant=ALPHA", json=body, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 400
    writer.assert_not_called()
    audit.assert_not_called()


def test_storage_validator_prevents_invalid_privacy_document_from_any_writer(privacy_app):
    with pytest.raises(ValueError, match="invalid_privacy"):
        privacy_app.container.storage.write_json("ALPHA", "privacy.json", {"password_hash": "synthetic-secret"})
    with pytest.raises(FileNotFoundError):
        privacy_app.container.storage.read_json("ALPHA", "privacy.json")


def test_public_notice_escapes_content_and_contains_no_other_business_or_credentials(privacy_app):
    storage = privacy_app.container.storage
    storage.write_json("ALPHA", "privacy.json", valid_settings(controller_name='<script>alert("x")</script>'))
    storage.write_json("BETA", "privacy.json", valid_settings(controller_name="Private other-tenant controller"))
    response = privacy_app.test_client().get("/privacy?tenant=ALPHA")
    assert response.status_code == 200
    assert '<script>alert("x")</script>' not in response.text
    assert "&lt;script&gt;" in response.text
    assert "Private other-tenant controller" not in response.text
    for value in ("password_hash", "management_token", "Alpha laptop", "Beta tablet", "owner@example.test"):
        assert value not in response.text
    assert privacy_app.test_client().get("/privacy?tenant=../BETA").status_code == 404


def test_invalid_saved_fields_do_not_become_public(privacy_app):
    path = privacy_app.container.storage.file_path("ALPHA", "privacy.json")
    path.write_text(json.dumps({"controller_name": "Bad stored name", "api_key": "synthetic-private-value"}))
    response = privacy_app.test_client().get("/privacy?tenant=ALPHA")
    assert response.status_code == 200 and "Draft" in response.text
    assert "Bad stored name" not in response.text
    assert "synthetic-private-value" not in response.text
    path.write_text('{"retention_days": NaN}')
    assert "Draft" in privacy_app.test_client().get("/privacy?tenant=ALPHA").text


def test_mailto_contact_is_encoded_as_one_address_not_header_parameters(privacy_app):
    settings = valid_settings(contact_email="name?subject=private@example.test")
    privacy_app.container.storage.write_json("ALPHA", "privacy.json", settings)
    text = privacy_app.test_client().get("/privacy?tenant=ALPHA").text
    assert 'href="mailto:name%3Fsubject%3Dprivate@example.test"' in text
    assert 'href="mailto:name?subject=' not in text


def test_privacy_updates_audit_field_names_without_document_contents(privacy_app, monkeypatch):
    client = privacy_app.test_client()
    csrf = login(client)
    audit = Mock()
    monkeypatch.setattr("routes.privacy_routes.AuditService", lambda: audit)
    result = save(client, valid_settings(controller_name="Synthetic private audit text"), csrf)
    assert result.status_code == 200
    assert audit.record.call_count == 2
    assert "Synthetic private audit text" not in str(audit.record.call_args_list)
    assert audit.record.call_args_list[0].kwargs["extra"]["result"] == "prepared"


def test_audit_failure_prevents_privacy_write(privacy_app, monkeypatch):
    client = privacy_app.test_client()
    csrf = login(client)
    audit = Mock()
    audit.record.side_effect = OSError("Synthetic audit failure")
    monkeypatch.setattr("routes.privacy_routes.AuditService", lambda: audit)
    response = save(client, valid_settings(), csrf)
    assert response.status_code == 500
    with pytest.raises(FileNotFoundError):
        privacy_app.container.storage.read_json("ALPHA", "privacy.json")


def test_cookie_notice_tracks_actual_cookie_and_effective_account_duration(privacy_app):
    from datetime import timedelta
    privacy_app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=12)
    response = privacy_app.test_client().get("/cookies")
    assert response.status_code == 200
    assert "up to 12 hours" in response.text
    assert "limited to 8 hours" in response.text
    assert "30 days" in response.text and "180 days" in response.text
    assert "does not sign you in silently" in response.text
    assert "only after" in response.text and "Essential only" in response.text


def test_configured_processors_are_named_without_keys_or_private_connection_strings(privacy_app, monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-private-openai-token")
    monkeypatch.setenv("V7_GOOGLE_CLIENT_ID", "synthetic-client-id")
    monkeypatch.setenv("V7_GOOGLE_CLIENT_SECRET", "synthetic-google-secret")
    privacy_app.container.settings = replace(privacy_app.container.settings, BASE_URL="https://platform.example.test")
    response = privacy_app.test_client().get("/privacy")
    assert "Render" in response.text and "OpenAI" in response.text and "Google" in response.text
    assert "synthetic-private-openai-token" not in response.text
    assert "synthetic-google-secret" not in response.text
    assert "synthetic-client-id" not in response.text


def test_own_account_export_requires_current_session_and_ignores_other_tenant(privacy_app):
    client = privacy_app.test_client()
    assert client.get("/auth/privacy/export").status_code == 401
    login(client)
    client.set_cookie("v7_preferences", "all")
    client.set_cookie("v7_language", "fr")
    response = client.get("/auth/privacy/export?tenant=BETA&email=admin@example.test")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json["identity"]["email"] == "owner@example.test"
    assert response.json["identity"]["tenant"] == "ALPHA"
    assert response.json["preferences"] == {"choice": "all", "saved_language": "fr"}
    for value in ("admin@example.test", "password_hash", "totp_secret", "management_token", "token_hash", "Beta tablet"):
        assert value not in response.text
    assert set(response.json) == {"identity", "trusted_devices", "preferences", "exported_at", "scope"}
    client.set_cookie("v7_preferences", "essential")
    assert client.get("/auth/privacy/export").json["preferences"]["saved_language"] == ""


def test_privacy_doc_stays_out_of_raw_file_api(privacy_app):
    client = privacy_app.test_client()
    login(client)
    assert client.get("/files/raw/privacy.json?tenant=ALPHA").status_code == 404
