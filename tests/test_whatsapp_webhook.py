"""
WhatsApp webhook tests:
- GET verification handshake
- POST inbound message with signature verification bypassed via monkeypatch
"""

from __future__ import annotations
import json
import hmac
import hashlib
import logging
import shutil
from pathlib import Path
from types import SimpleNamespace
import pytest
from dataclasses import replace
from twilio.request_validator import RequestValidator


@pytest.fixture(autouse=True)
def whatsapp_config(app, monkeypatch):
    app.container.settings = replace(app.container.settings, WHATSAPP_APP_SECRET="configured-secret",
        WHATSAPP_TOKEN="test-token", WHATSAPP_PHONE_ID="phone-id", WHATSAPP_VERIFY_TOKEN="testtoken")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "configured-token")
    monkeypatch.setenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+447700900999")
    monkeypatch.setattr("routes.whatsapp_routes.send_reply", lambda *args, **kwargs: None)


def cloud_post(client, payload):
    body = json.dumps(payload).encode()
    signature = hmac.new(b"configured-secret", body, hashlib.sha256).hexdigest()
    return client.post("/whatsapp/webhook", data=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": "sha256=" + signature})


def _cloud_payload(phone_number_id: str = "phone-id"):
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": phone_number_id},
                            "messages": [{"id": "wamid.test-1", "type": "text", "from": "447700900123", "text": {"body": "hello there"}}],
                        }
                    }
                ]
            }
        ]
    }


def test_webhook_verify_challenge(client, app, monkeypatch):
    # Ensure app has a known verify token
    app.config["WA_VERIFY_TOKEN"] = "testtoken"
    r = client.get("/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=testtoken&hub.challenge=12345")
    # Some frameworks return text/plain, others JSON; status 200 is key
    assert r.status_code == 200
    # Body should contain the challenge or echo JSON
    body = r.get_data(as_text=True)
    assert "12345" in body or r.is_json and (r.get_json() or {}).get("challenge") == "12345"


def test_webhook_inbound_dispatch_ok(client):
    response = cloud_post(client, _cloud_payload())
    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "events": 1}


@pytest.mark.parametrize('provider', ['cloud', 'twilio'])
def test_assistant_disclosure_survives_retries_without_duplicate_answers(client, app, monkeypatch, provider):
    from service.ai_disclosure import MESSAGE_LABEL
    from xml.etree import ElementTree
    answer = 'Small £100\nMedium £150\nLarge £200'
    calls, sends = [], []
    def handle(*args, **kwargs):
        calls.append(kwargs)
        return {'reply': answer, 'intent': 'question'}
    monkeypatch.setattr(app.container.for_tenant('EXAMPLE').handler, 'handle', handle)
    monkeypatch.setattr('routes.whatsapp_routes.send_reply', lambda event, reply, **kwargs: sends.append(reply))
    if provider == 'cloud':
        assert cloud_post(client, _cloud_payload()).status_code == 200
        assert cloud_post(client, _cloud_payload()).status_code == 200
        assert len(sends) == 1
        reply = sends[0]
    else:
        form = {'Body': 'What are your prices?', 'From': 'whatsapp:+447700900123',
                'To': 'whatsapp:+447700900999', 'MessageSid': 'SMdisclosure'}
        signed = RequestValidator('configured-token').compute_signature(app.container.settings.BASE_URL+'/whatsapp/webhook', form)
        first = client.post('/whatsapp/webhook', data=form, headers={'X-Twilio-Signature': signed})
        replay = client.post('/whatsapp/webhook', data=form, headers={'X-Twilio-Signature': signed})
        assert first.status_code == replay.status_code == 200
        reply = ElementTree.fromstring(first.data).find('Message').text
        assert ElementTree.fromstring(replay.data).find('Message').text == reply
    assert len(calls) == 1
    assert reply == MESSAGE_LABEL+'\n\n'+answer


def test_twilio_webhook_keeps_customer_content_out_of_operational_logs(client, app, caplog):
    caplog.set_level(logging.INFO)
    caplog.clear()
    message = "Please call +447123456789 or email customer@example.test"

    form = {"Body": message, "From": "whatsapp:+447123456789", "To": "whatsapp:+447700900999", "MessageSid": "SMtest-1"}
    signature = RequestValidator("configured-token").compute_signature(app.container.settings.BASE_URL + "/whatsapp/webhook", form)
    response = client.post("/whatsapp/webhook", data=form, headers={"X-Twilio-Signature": signature})

    logs = "\n".join(record.getMessage() for record in caplog.records)
    assert response.status_code == 200
    assert message not in logs
    assert "+447123456789" not in logs
    assert "customer@example.test" not in logs
    assert "message_len=" in logs


def test_cloud_webhook_uses_mapped_tenant_runtime(client, app):
    business_root = Path(app.container.storage.business_root)
    shutil.copytree(business_root / "EXAMPLE", business_root / "ALT")
    object.__setattr__(app.container.settings, "WHATSAPP_TENANT_MAP", {"alternate-phone-id": "ALT"})

    calls = []
    app.container.for_tenant("ALT").handler.handle = lambda *_args, **kwargs: calls.append(kwargs) or {
        "reply": "Alternate tenant reply",
        "intent": "faq",
    }

    response = cloud_post(client, _cloud_payload("alternate-phone-id"))

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "events": 1}
    assert calls == [
        {
            "tenant": "ALT",
            "session_id": "wa:447700900123",
            "channel": "whatsapp",
            "metadata": {"wa_id": "447700900123", "source": "cloud", "phone_number_id": "alternate-phone-id"},
        }
    ]


def test_cloud_webhook_rejects_unsigned_requests_in_production(client, app, monkeypatch):
    object.__setattr__(app.container.settings, "ENVIRONMENT", "production")
    object.__setattr__(app.container.settings, "WHATSAPP_APP_SECRET", "configured-secret")
    app.config["TESTING"] = False
    app.config["DEBUG"] = False

    response = client.post("/whatsapp/webhook", json=_cloud_payload())

    assert response.status_code == 403


def test_twilio_webhook_rejects_unsigned_requests_in_production(client, app):
    object.__setattr__(app.container.settings, "ENVIRONMENT", "production")
    object.__setattr__(app.container.settings, "TWILIO_AUTH_TOKEN", "configured-token")
    app.config["TESTING"] = False
    app.config["DEBUG"] = False

    response = client.post(
        "/whatsapp/webhook",
        data={"Body": "hello", "From": "whatsapp:+447700900123"},
        content_type="application/x-www-form-urlencoded",
    )

    assert response.status_code == 403


def test_cloud_reply_uses_the_inbound_business_phone_id(monkeypatch):
    from connectors.whatsapp import send_reply

    sent = {}

    class Response:
        status_code = 200

    def fake_post(url, **kwargs):
        sent["url"] = url
        sent["payload"] = kwargs["json"]
        return Response()

    monkeypatch.setattr("connectors.whatsapp.requests.post", fake_post)
    settings = SimpleNamespace(
        WHATSAPP_TOKEN="token",
        WHATSAPP_PHONE_ID="default-phone-id",
        WHATSAPP_API_URL="https://api.example.test",
    )

    send_reply(
        {"from": "447700900123", "metadata": {"phone_number_id": "alternate-phone-id"}, "source": "cloud"},
        "Hello",
        settings=settings,
    )

    assert sent["url"] == "https://api.example.test/alternate-phone-id/messages"
    assert sent["payload"]["to"] == "447700900123"
