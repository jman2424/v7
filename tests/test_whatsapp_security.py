import hashlib
import hmac
import json
from dataclasses import replace
from unittest.mock import Mock

import pytest
from twilio.request_validator import RequestValidator

from tests.test_platform_security import platform as platform_fixture

platform = platform_fixture


def test_unconfigured_routes_remain_registered(platform):
    client = platform[0].test_client()
    assert client.get("/whatsapp/status").status_code == 200
    assert client.get("/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=dev").status_code == 503
    assert client.post("/whatsapp/webhook", json={}).status_code == 503
    assert client.post("/whatsapp/status", json={}).status_code == 503


def configure_meta(platform):
    app = platform[0]
    app.container.settings = replace(app.container.settings, WHATSAPP_APP_SECRET="test-meta-secret",
        WHATSAPP_VERIFY_TOKEN="test-verify", WHATSAPP_TOKEN="test-provider-token", WHATSAPP_PHONE_ID="12345")
    return app


def meta_payload(phone="12345"):
    return {"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": phone},
        "messages": [{"id": "wamid.test-1", "from": "447700900123", "type": "text", "text": {"body": "Hello"}}]}}]}]}


def signed_post(client, payload, signature=True):
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if signature:
        headers["X-Hub-Signature-256"] = "sha256=" + hmac.new(b"test-meta-secret", body, hashlib.sha256).hexdigest()
    return client.post("/whatsapp/webhook", data=body, headers=headers)


def test_meta_verification_and_signature_required(platform):
    client = configure_meta(platform).test_client()
    assert client.get("/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=test-verify&hub.challenge=123").text == "123"
    assert client.get("/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=wrong").status_code == 403
    assert signed_post(client, meta_payload(), signature=False).status_code == 403
    assert signed_post(client, meta_payload("other-company-number")).status_code == 403
    assert signed_post(client, []).status_code == 400


def test_meta_dispatch_deduplicates_signed_retries(platform, monkeypatch):
    app = configure_meta(platform)
    handler = Mock(return_value={"reply": "Welcome", "intent": "greeting"})
    send = Mock()
    monkeypatch.setattr(app.container.for_tenant("ALPHA").handler, "handle", handler)
    monkeypatch.setattr("routes.whatsapp_routes.send_reply", send)
    client = app.test_client()
    assert signed_post(client, meta_payload()).status_code == 200
    assert signed_post(client, meta_payload()).status_code == 200
    assert handler.call_count == send.call_count == 1


def test_meta_send_failure_is_retryable_and_visible(platform, monkeypatch):
    app = configure_meta(platform)
    monkeypatch.setattr(app.container.for_tenant("ALPHA").handler, "handle", Mock(return_value={"reply": "Welcome", "intent": "greeting"}))
    send = Mock(side_effect=[RuntimeError("provider unavailable"), None])
    monkeypatch.setattr("routes.whatsapp_routes.send_reply", send)
    client = app.test_client()
    assert signed_post(client, meta_payload()).status_code == 503
    assert signed_post(client, meta_payload()).status_code == 200
    from service.analytics_db import get_kpis
    assert get_kpis(tenant="ALPHA")["errors"] >= 1


def test_twilio_requires_signature_recipient_and_deduplicates(platform, monkeypatch):
    app = platform[0]
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "test-twilio-secret")
    monkeypatch.setenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+447700900999")
    handler = Mock(return_value={"reply": "<Hello & welcome>", "intent": "greeting"})
    monkeypatch.setattr(app.container.for_tenant("ALPHA").handler, "handle", handler)
    client = app.test_client()
    form = {"Body": "Hello", "From": "whatsapp:+447700900123", "To": "whatsapp:+447700900999", "MessageSid": "SMtest1"}
    assert client.post("/whatsapp/webhook", data=form).status_code == 403
    validator = RequestValidator("test-twilio-secret")
    signature = validator.compute_signature(app.container.settings.BASE_URL + "/whatsapp/webhook", form)
    first = client.post("/whatsapp/webhook", data=form, headers={"X-Twilio-Signature": signature})
    again = client.post("/whatsapp/webhook", data=form, headers={"X-Twilio-Signature": signature})
    assert first.status_code == again.status_code == 200
    assert b"&lt;Hello &amp; welcome&gt;" in first.data
    assert handler.call_count == 1
    assert first.data == again.data


def test_user_agent_cannot_bypass_cloud_signature(platform):
    client = configure_meta(platform).test_client()
    response = client.post("/whatsapp/webhook", json=meta_payload(), headers={"User-Agent": "TwilioProxy"})
    assert response.status_code == 403
