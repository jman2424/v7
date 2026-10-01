"""Signed provider batches are validated before any tenant receives a message."""
import hashlib
import hmac
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlunsplit

import pytest
import test_platform_security
from twilio.request_validator import RequestValidator
from werkzeug.datastructures import MultiDict

from connectors.whatsapp import parse_inbound, send_reply

platform = test_platform_security.platform


def _configure(platform):
    app = platform[0]
    app.container.settings = replace(
        app.container.settings, WHATSAPP_APP_SECRET="test-meta-secret",
        WHATSAPP_TOKEN="test-provider-token", WHATSAPP_PHONE_ID="11111",
        WHATSAPP_TENANT_MAP={"11111": "ALPHA", "22222": "BETA"},
    )
    return app


def _batch(second=None, *, second_recipient="22222"):
    return {"entry": [{"changes": [
        {"value": {"metadata": {"phone_number_id": "11111"}, "messages": [
            {"id": "wamid.first", "from": "447700900111", "type": "text", "text": {"body": "Hello Alpha"}},
        ]}},
        {"value": {"metadata": {"phone_number_id": second_recipient}, "messages": [second or
            {"id": "wamid.second", "from": "447700900222", "type": "text", "text": {"body": "Hello Beta"}},
        ]}},
    ]}]}


def _signed(client, payload):
    body = json.dumps(payload).encode()
    signature = hmac.new(b"test-meta-secret", body, hashlib.sha256).hexdigest()
    return client.post("/whatsapp/webhook", data=body, headers={
        "Content-Type": "application/json", "X-Hub-Signature-256": "sha256=" + signature,
    })


@pytest.mark.parametrize("second", [
    {"id": "wamid.second", "from": "not-a-phone", "type": "text", "text": {"body": "Hello"}},
    {"id": "wamid.second", "from": "Ù¤Ù¤Ù§Ù§Ù Ù Ù©Ù Ù Ù¡Ù¢Ù£", "type": "text", "text": {"body": "Hello"}},
    {"id": "wamid.second", "from": "447700900222", "type": "text", "text": {"body": "x" * 4001}},
    {"from": "447700900222", "type": "text", "text": {"body": "Hello"}},
    {"id": "x" * 201, "from": "447700900222", "type": "text", "text": {"body": "Hello"}},
    {"id": "wamid.second", "from": "447700900222", "type": "text", "text": {"body": 42}},
    {"id": "wamid.second", "from": "447700900222", "type": "text", "text": {"body": ""}},
    {"id": "wamid.second", "from": "", "type": "text", "text": {"body": "Hello"}},
    {"id": "wamid.second", "from": "447700900222", "type": "audio", "audio": {"id": "../secret"}},
    {"id": "wamid.second", "from": "447700900222", "type": "audio", "audio": []},
])
def test_bad_second_message_prevents_first_tenant_dispatch(platform, monkeypatch, second):
    app = _configure(platform)
    process = Mock(return_value="Reply")
    monkeypatch.setattr("routes.whatsapp_routes._process", process)
    response = _signed(app.test_client(), _batch(second))
    assert response.status_code == 400
    process.assert_not_called()


def test_unassigned_second_recipient_prevents_first_tenant_dispatch(platform, monkeypatch):
    app = _configure(platform)
    process = Mock(return_value="Reply")
    monkeypatch.setattr("routes.whatsapp_routes._process", process)
    assert _signed(app.test_client(), _batch(second_recipient="99999")).status_code == 403
    process.assert_not_called()


def test_valid_mapped_batch_preserves_tenant_and_audio_dispatch(platform, monkeypatch):
    app = _configure(platform)
    voice = {"id": "wamid.voice", "from": "447700900222", "type": "audio",
             "audio": {"id": "998877", "mime_type": "audio/ogg"}}
    process = Mock(return_value="Reply")
    monkeypatch.setattr("routes.whatsapp_routes._process", process)
    response = _signed(app.test_client(), _batch(voice))
    assert response.status_code == 200
    assert response.json == {"ok": True, "events": 2}
    assert [call.args[0].settings.BUSINESS_KEY for call in process.call_args_list] == ["ALPHA", "BETA"]
    assert process.call_args_list[1].args[1]["audio"]["id"] == "998877"
    assert process.call_args_list[1].args[1]["metadata"]["phone_number_id"] == "22222"


@pytest.mark.parametrize("payload", [{"entry": {}}, {"entry": [None]}, {"entry": [{"changes": {}}]},
    {"entry": [{"changes": [{"value": None}]}]},
    {"entry": [{"changes": [{"value": {"messages": {}}}]}]},
    {"entry": [{"changes": [{"value": {"metadata": []}}]}]},
])
def test_malformed_signed_provider_envelopes_return_safe_bad_request(platform, payload):
    response = _signed(_configure(platform).test_client(), payload)
    assert response.status_code == 400
    assert "Traceback" not in response.text


def test_duplicate_signed_twilio_fields_cannot_choose_a_different_recipient(platform, monkeypatch):
    app = platform[0]
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "test-twilio-secret")
    monkeypatch.setenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+447700900999")
    form = MultiDict([
        ("Body", "Hello"), ("From", "whatsapp:+447700900123"),
        ("To", "whatsapp:+447700900999"), ("MessageSid", "SMduplicate"),
        ("Body", "Different body"),
    ])
    process = Mock(return_value="Reply")
    monkeypatch.setattr("routes.whatsapp_routes._process", process)
    signature = RequestValidator("test-twilio-secret").compute_signature(
        app.container.settings.BASE_URL + "/whatsapp/webhook", form,
    )
    response = app.test_client().post("/whatsapp/webhook", data=form,
                                     headers={"X-Twilio-Signature": signature})
    assert response.status_code == 400
    process.assert_not_called()


@pytest.mark.parametrize("payload", [[], {"raw_form": ["Body"]}, {"raw_form": {"Body": 42}}])
def test_connector_rejects_malformed_direct_payloads(payload):
    with pytest.raises(ValueError):
        parse_inbound(payload)


# Build synthetic user-info at runtime while preserving the hostile URL case.
_SYNTHETIC_CREDENTIAL_URL = urlunsplit((
    'https', "{}:{}@{}".format('user', 'password', 'api.example.test'),
    '', '', '',
))

@pytest.mark.parametrize("base", ["http://api.example.test", _SYNTHETIC_CREDENTIAL_URL,
    "https://api.example.test?access_token=secret", "https://api.example.test#fragment",
    "https://api.example.test:invalid", "https://api.example.test\n/path",
    "https://api.example.test\\other.test/path", "https://api.example.test:8443/v1",
])
def test_outbound_provider_url_rejects_unsafe_configuration(monkeypatch, base):
    post = Mock()
    monkeypatch.setattr("connectors.whatsapp.requests.post", post)
    settings = SimpleNamespace(WHATSAPP_TOKEN="token", WHATSAPP_PHONE_ID="11111", WHATSAPP_API_URL=base)
    with pytest.raises((ValueError, RuntimeError), match="configuration"):
        send_reply({"from": "447700900123", "source": "cloud"}, "Hello", settings=settings)
    post.assert_not_called()


@pytest.mark.parametrize("phone", ["../secret", "12345?token=value", "12345/messages", "", []])
def test_outbound_phone_id_cannot_modify_provider_path(monkeypatch, phone):
    post = Mock()
    monkeypatch.setattr("connectors.whatsapp.requests.post", post)
    settings = SimpleNamespace(WHATSAPP_TOKEN="token", WHATSAPP_PHONE_ID=phone,
                               WHATSAPP_API_URL="https://api.example.test")
    with pytest.raises((ValueError, RuntimeError)):
        send_reply({"from": "447700900123", "source": "cloud"}, "Hello", settings=settings)
    post.assert_not_called()


def test_outbound_redirect_is_not_followed_and_errors_omit_provider_body(monkeypatch):
    post = Mock(return_value=SimpleNamespace(status_code=302, text="secret provider response"))
    monkeypatch.setattr("connectors.whatsapp.requests.post", post)
    settings = SimpleNamespace(WHATSAPP_TOKEN="private-test-token", WHATSAPP_PHONE_ID="default-phone-id",
                               WHATSAPP_API_URL="https://api.example.test:443/v1")
    with pytest.raises(RuntimeError) as error:
        send_reply({"from": "447700900123", "source": "cloud",
                    "metadata": {"phone_number_id": "mapped-phone-id"}}, "Hello", settings=settings)
    assert post.call_args.args[0] == "https://api.example.test:443/v1/mapped-phone-id/messages"
    assert post.call_args.kwargs["allow_redirects"] is False
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer private-test-token"
    assert "secret provider response" not in str(error.value)
    assert "private-test-token" not in str(error.value)
