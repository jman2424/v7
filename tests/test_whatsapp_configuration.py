"""Offline provider setup/routing checks; all credentials and IDs are synthetic."""
import hashlib
import hmac
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlunsplit

import pytest
from twilio.request_validator import RequestValidator

from app.config import load_settings
from connectors.whatsapp import send_reply
from connectors.whatsapp_audio import AudioMediaError, download_audio
from service.whatsapp_configuration import recipient_tenant
from tests.test_platform_security import login, platform as platform_fixture

platform = platform_fixture


def configure(app, **overrides):
    app.container.settings = replace(app.container.settings,
        WHATSAPP_APP_SECRET="synthetic-meta-secret", WHATSAPP_VERIFY_TOKEN="synthetic-verify",
        WHATSAPP_TOKEN="synthetic-provider-token", WHATSAPP_PHONE_ID="12345",
        TWILIO_AUTH_TOKEN="synthetic-twilio-token", TWILIO_WHATSAPP_NUMBER="whatsapp:+447700900999",
        **overrides)
    return app


def cloud_post(client, phones):
    payload = {"entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": phone},
        "messages": [{"id": "wamid." + phone, "from": "447700900123", "type": "text",
                      "text": {"body": "Hello"}}]}} for phone in phones]}]}
    body = json.dumps(payload).encode()
    signature = hmac.new(b"synthetic-meta-secret", body, hashlib.sha256).hexdigest()
    return client.post("/whatsapp/webhook", data=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": "sha256=" + signature})


def test_settings_load_explicit_provider_maps_and_default_number():
    settings = load_settings({"SECRET_KEY": "test-secret-" * 4, "WHATSAPP_PROVIDER_MODE": "both",
        "WHATSAPP_META_TENANT_MAP_JSON": '{"12345":"ALPHA"}',
        "TWILIO_WHATSAPP_TENANT_MAP_JSON": '{"whatsapp:+447700900999":"BETA"}',
        "TWILIO_WHATSAPP_NUMBER": "whatsapp:+447700900888"})
    assert settings.WHATSAPP_PROVIDER_MODE == "both"
    assert settings.WHATSAPP_META_TENANT_MAP == {"12345": "ALPHA"}
    assert settings.TWILIO_WHATSAPP_TENANT_MAP == {"447700900999": "BETA"}
    assert settings.TWILIO_WHATSAPP_NUMBER == "whatsapp:+447700900888"


@pytest.mark.parametrize("overrides", [
    {"WHATSAPP_PROVIDER_MODE": "unknown"},
    {"WHATSAPP_META_TENANT_MAP_JSON": "[]"},
    {"WHATSAPP_TENANT_MAP_JSON": '{"+12345":"ALPHA","12345":"BETA"}'},
])
def test_invalid_or_ambiguous_configuration_fails_closed(overrides):
    with pytest.raises(RuntimeError):
        load_settings({"SECRET_KEY": "test-secret-" * 4, **overrides})


def test_empty_dedicated_map_prevents_fallback_to_legacy_recipient():
    settings = load_settings({"SECRET_KEY": "test-secret-" * 4,
        "WHATSAPP_TENANT_MAP_JSON": '{"12345":"ALPHA"}', "WHATSAPP_META_TENANT_MAP_JSON": "{}"})
    assert recipient_tenant(settings, "12345", "meta") is None


def test_default_twilio_recipient_uses_app_override(platform, monkeypatch):
    app = configure(platform[0], WHATSAPP_PROVIDER_MODE="twilio")
    monkeypatch.delenv("TWILIO_WHATSAPP_NUMBER", raising=False)
    handler = Mock(return_value={"reply": "Hello", "intent": "greeting"})
    monkeypatch.setattr(app.container.for_tenant("ALPHA").handler, "handle", handler)
    form = {"Body": "Hello", "From": "whatsapp:+447700900123", "To": "whatsapp:+447700900999",
            "MessageSid": "SMoverride"}
    signature = RequestValidator("synthetic-twilio-token").compute_signature(
        app.container.settings.BASE_URL + "/whatsapp/webhook", form)
    response = app.test_client().post("/whatsapp/webhook", data=form,
                                    headers={"X-Twilio-Signature": signature})
    assert response.status_code == 200
    assert handler.call_count == 1


def test_disabled_provider_rejects_even_signed_webhook(platform, monkeypatch):
    app = configure(platform[0], WHATSAPP_PROVIDER_MODE="twilio")
    handler = Mock(side_effect=AssertionError("Disabled Meta provider reached agent"))
    monkeypatch.setattr(app.container.for_tenant("ALPHA").handler, "handle", handler)
    assert cloud_post(app.test_client(), ["12345"]).status_code == 503
    assert app.test_client().get("/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=synthetic-verify").status_code == 503
    handler.assert_not_called()


def test_whitespace_only_signing_secrets_are_unconfigured(platform, monkeypatch):
    app = configure(platform[0])
    app.container.settings = replace(app.container.settings, WHATSAPP_APP_SECRET=" ", TWILIO_AUTH_TOKEN=" ")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", " ")
    client = app.test_client()
    assert cloud_post(client, ["12345"]).status_code == 503
    form = {"Body": "Hello", "From": "whatsapp:+447700900123", "To": "whatsapp:+447700900999",
            "MessageSid": "SMwhitespace"}
    signature = RequestValidator(" ").compute_signature(app.container.settings.BASE_URL + "/whatsapp/webhook", form)
    assert client.post("/whatsapp/webhook", data=form, headers={"X-Twilio-Signature": signature}).status_code == 503


def test_meta_batch_checks_all_recipients_before_any_processing(platform, monkeypatch):
    app = configure(platform[0])
    handler = Mock(side_effect=AssertionError("Partially validated batch reached agent"))
    monkeypatch.setattr(app.container.for_tenant("ALPHA").handler, "handle", handler)
    monkeypatch.setattr("routes.whatsapp_routes.send_reply", Mock())
    assert cloud_post(app.test_client(), ["12345", "unknown-recipient"]).status_code == 403
    handler.assert_not_called()


def test_provider_maps_route_to_distinct_tenants_without_legacy_fallback(platform, monkeypatch):
    app = configure(platform[0], WHATSAPP_PROVIDER_MODE="both",
        WHATSAPP_TENANT_MAP={"12345": "ALPHA", "447700900999": "ALPHA"},
        WHATSAPP_META_TENANT_MAP={"12345": "ALPHA"},
        TWILIO_WHATSAPP_TENANT_MAP={"447700900999": "BETA"})
    assert recipient_tenant(app.container.settings, "12345", "meta") == "ALPHA"
    assert recipient_tenant(app.container.settings, "12345", "twilio") is None
    handler = Mock(return_value={"reply": "Beta reply", "intent": "faq"})
    monkeypatch.setattr(app.container.for_tenant("BETA").handler, "handle", handler)
    form = {"Body": "Hello", "From": "whatsapp:+447700900123", "To": "whatsapp:+447700900999",
            "MessageSid": "SMdedicated"}
    signature = RequestValidator("synthetic-twilio-token").compute_signature(
        app.container.settings.BASE_URL + "/whatsapp/webhook", form)
    response = app.test_client().post("/whatsapp/webhook", data=form,
                                    headers={"X-Twilio-Signature": signature})
    assert response.status_code == 200
    assert handler.call_args.kwargs["tenant"] == "BETA"


def test_setup_status_is_authenticated_scoped_and_contains_no_credentials(platform, monkeypatch):
    app = configure(platform[0], WHATSAPP_PROVIDER_MODE="both",
        WHATSAPP_META_TENANT_MAP={"12345": "ALPHA", "beta-private-recipient": "BETA"},
        TWILIO_WHATSAPP_TENANT_MAP={"447700900999": "BETA"})
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-openai-secret")
    monkeypatch.setenv("V7_TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe")
    client = app.test_client()
    assert client.get("/admin/api/integrations?tenant=ALPHA").status_code == 401
    login(client)
    assert client.get("/admin/api/integrations?tenant=BETA").status_code == 403
    response = client.get("/admin/api/integrations?tenant=ALPHA")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    data = response.json
    assert {"whatsapp_assigned", "meta_configured", "twilio_configured", "ai_configured"} <= data.keys()
    assert data["meta_configured"] is True and data["twilio_configured"] is False
    assert data["whatsapp"]["providers"]["meta"]["recipients"] == ["12345"]
    assert data["whatsapp"]["providers"]["twilio"]["state"] == "unassigned"
    assert data["whatsapp"]["voice"]["ready"] is True
    assert "beta-private-recipient" not in response.text
    assert "447700900999" not in response.text
    for secret in ("synthetic-meta-secret", "synthetic-verify", "synthetic-provider-token",
                   "synthetic-twilio-token", "synthetic-openai-secret"):
        assert secret not in response.text


def test_setup_status_explains_missing_settings_and_activation(platform, monkeypatch):
    app = configure(platform[0], WHATSAPP_PROVIDER_MODE="meta")
    app.container.settings = replace(app.container.settings, WHATSAPP_TOKEN="")
    monkeypatch.setattr("service.tenant_access.activation", lambda tenant: {"active": False})
    monkeypatch.setattr("service.subscriptions.whatsapp_enabled", lambda tenant: False)
    client = app.test_client()
    login(client)
    data = client.get("/admin/api/integrations?tenant=ALPHA").json["whatsapp"]
    assert data["ready"] is False
    assert data["providers"]["meta"]["missing_settings"] == ["WHATSAPP_TOKEN"]
    assert data["providers"]["meta"]["state"] == "missing_settings"
    assert data["providers"]["twilio"]["state"] == "disabled"
    assert {row["code"] for row in data["blockers"]} == {
        "whatsapp_not_configured", "tenant_inactive", "whatsapp_subscription_inactive"}


def test_setup_status_does_not_repeat_an_invalid_transcription_setting(platform, monkeypatch):
    app = configure(platform[0], WHATSAPP_PROVIDER_MODE="meta")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-openai-secret")
    monkeypatch.setenv("V7_TRANSCRIPTION_MODEL", "synthetic-private-model-value")
    client = app.test_client()
    login(client)
    response = client.get("/admin/api/integrations?tenant=ALPHA")
    voice = response.json["whatsapp"]["voice"]
    assert voice["configured"] is voice["ready"] is False
    assert voice["transcription_model"] == ""
    assert voice["missing_settings"] == ["V7_TRANSCRIPTION_MODEL"]
    assert "synthetic-private-model-value" not in response.text


def test_custom_meta_send_endpoint_does_not_claim_voice_is_ready(platform, monkeypatch):
    app = configure(platform[0], WHATSAPP_PROVIDER_MODE="meta", WHATSAPP_API_URL="https://provider.example.test")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-openai-secret")
    monkeypatch.setenv("V7_TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe")
    client = app.test_client()
    login(client)
    data = client.get("/admin/api/integrations?tenant=ALPHA").json["whatsapp"]
    assert data["providers"]["meta"]["configured"] is True
    assert data["voice"]["configured"] is True
    assert data["voice"]["ready"] is False
    assert data["voice"]["invalid_settings"] == ["WHATSAPP_API_URL"]


def test_meta_send_does_not_follow_provider_redirects(monkeypatch):
    request = Mock(return_value=SimpleNamespace(status_code=302))
    monkeypatch.setattr("connectors.whatsapp.requests.post", request)
    settings = SimpleNamespace(WHATSAPP_TOKEN="synthetic-token", WHATSAPP_PHONE_ID="12345",
                               WHATSAPP_API_URL="https://graph.facebook.com/v21.0")
    with pytest.raises(RuntimeError, match="provider rejected"):
        send_reply({"source": "cloud", "from": "447700900123"}, "Hello", settings=settings)
    assert request.call_args.kwargs["allow_redirects"] is False


# Build synthetic user-info at runtime while preserving the hostile URL case.
_SYNTHETIC_CREDENTIAL_URL = urlunsplit((
    'https', "{}:{}@{}".format('user', 'password', 'graph.facebook.com'),
    '/v21.0', '', '',
))

@pytest.mark.parametrize("url", ["http://graph.facebook.com/v21.0",
    _SYNTHETIC_CREDENTIAL_URL, "https://graph.facebook.com:bad/v21.0",
    "https://graph.facebook.com/v21.0?token=synthetic-secret"])
def test_invalid_meta_api_url_is_rejected_before_sending(monkeypatch, url):
    request = Mock(side_effect=AssertionError("Invalid provider URL reached network"))
    monkeypatch.setattr("connectors.whatsapp.requests.post", request)
    settings = SimpleNamespace(WHATSAPP_TOKEN="synthetic-token", WHATSAPP_PHONE_ID="12345", WHATSAPP_API_URL=url)
    with pytest.raises(RuntimeError, match="configuration invalid"):
        send_reply({"source": "cloud", "from": "447700900123"}, "Hello", settings=settings)
    request.assert_not_called()


def test_meta_voice_rejects_credential_bearing_api_base_before_download(monkeypatch):
    download = Mock(side_effect=AssertionError("Invalid media API reached network"))
    monkeypatch.setattr("connectors.whatsapp_audio._get", download)
    settings = SimpleNamespace(WHATSAPP_TOKEN="synthetic-token",
        WHATSAPP_API_URL=_SYNTHETIC_CREDENTIAL_URL)
    event = {"source": "cloud", "audio": {"id": "998877", "phone_number_id": "12345"}}
    with pytest.raises(AudioMediaError, match="invalid_media_api"):
        download_audio(event, settings=settings)
    download.assert_not_called()
