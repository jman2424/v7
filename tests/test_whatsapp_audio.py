"""Voice notes use the same signed, tenant-scoped WhatsApp path as text."""
import hashlib
import hmac
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from twilio.request_validator import RequestValidator

from connectors.whatsapp import parse_inbound
from connectors import whatsapp_audio


@pytest.fixture
def wa_config(app, monkeypatch):
    app.container.settings = replace(app.container.settings, WHATSAPP_APP_SECRET="configured-secret",
        WHATSAPP_TOKEN="test-token", WHATSAPP_PHONE_ID="phone-id", WHATSAPP_VERIFY_TOKEN="testtoken")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "configured-token")
    monkeypatch.setenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+447700900999")
    monkeypatch.setattr("routes.whatsapp_routes.send_reply", lambda *args, **kwargs: None)


def test_parse_cloud_voice_note():
    payload = {"entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": "12345"},
        "messages": [{"id": "wamid.voice", "from": "447700900123", "type": "audio",
                      "audio": {"id": "998877", "mime_type": "audio/ogg; codecs=opus"}}],
    }}]}]}
    events = parse_inbound(payload)
    assert len(events) == 1
    assert events[0]["text"] == ""
    assert events[0]["audio"]["id"] == "998877"
    assert events[0]["audio"]["phone_number_id"] == "12345"


def test_parse_twilio_voice_note():
    form = {"From": "whatsapp:+447700900123", "Body": "", "NumMedia": "1",
            "MediaContentType0": "audio/ogg", "MediaUrl0": "https://api.twilio.com/voice",
            "MessageSid": "SMvoice"}
    events = parse_inbound({"raw_form": form})
    assert len(events) == 1
    assert events[0]["source"] == "twilio"
    assert events[0]["audio"]["mime_type"] == "audio/ogg"


def test_meta_download_rejects_untrusted_url(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return json.dumps({"id": "998877", "file_size": 3, "mime_type": "audio/ogg",
                           "url": "https://attacker.example/audio"}).encode()

    monkeypatch.setattr(whatsapp_audio, "_get", fake_get)
    settings = SimpleNamespace(WHATSAPP_TOKEN="test", WHATSAPP_API_URL="https://graph.facebook.com/v21.0")
    event = {"source": "cloud", "audio": {"id": "998877", "mime_type": "audio/ogg",
                                           "phone_number_id": "12345"}}
    with pytest.raises(whatsapp_audio.AudioMediaError, match="invalid_media_url"):
        whatsapp_audio.download_audio(event, settings=settings)
    assert len(calls) == 1


def test_meta_download_uses_verified_media_id_and_phone(monkeypatch):
    calls = []
    voice = b"OggS" + b"\x00" * 4

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        if len(calls) == 1:
            return json.dumps({"id": "998877", "file_size": len(voice),
                "mime_type": "audio/ogg", "url": "https://lookaside.fbsbx.com/voice"}).encode()
        return voice

    monkeypatch.setattr(whatsapp_audio, "_get", fake_get)
    settings = SimpleNamespace(WHATSAPP_TOKEN="test", WHATSAPP_API_URL="https://graph.facebook.com/v21.0")
    event = {"source": "cloud", "audio": {"id": "998877", "mime_type": "audio/ogg",
                                           "phone_number_id": "12345"}}
    assert whatsapp_audio.download_audio(event, settings=settings) == (voice, "audio/ogg")
    assert calls[0][0].endswith("/998877?phone_number_id=12345")
    assert calls[1][0] == "https://lookaside.fbsbx.com/voice"
    assert calls[1][1]["headers"]["Authorization"] == "Bearer test"


def test_twilio_download_rejects_media_sid_mismatch(monkeypatch):
    account = "AC" + "a" * 32
    message = "SM" + "b" * 32
    media = "ME" + "c" * 32
    settings = SimpleNamespace(TWILIO_AUTH_TOKEN="test")
    event = {"source": "twilio", "audio": {
        "url": f"https://api.twilio.com/2010-04-01/Accounts/{account}/Messages/{message}/Media/{media}",
        "account_sid": account, "message_sid": "SM" + "d" * 32,
        "mime_type": "audio/ogg"}}
    monkeypatch.setattr(whatsapp_audio, "_get", Mock(side_effect=AssertionError("network used")))
    with pytest.raises(whatsapp_audio.AudioMediaError, match="media_identity_mismatch"):
        whatsapp_audio.download_audio(event, settings=settings)


def test_twilio_download_uses_provider_auth(monkeypatch):
    account = "AC" + "a" * 32
    message = "SM" + "b" * 32
    media = "ME" + "c" * 32
    calls = []
    monkeypatch.delenv("TWILIO_API_KEY", raising=False)
    monkeypatch.delenv("TWILIO_API_SECRET", raising=False)
    monkeypatch.setattr(whatsapp_audio, "_get", lambda url, **kwargs: calls.append((url, kwargs)) or b"OggS")
    settings = SimpleNamespace(TWILIO_AUTH_TOKEN="test-token")
    event = {"source": "twilio", "audio": {
        "url": f"https://api.twilio.com/2010-04-01/Accounts/{account}/Messages/{message}/Media/{media}",
        "account_sid": account, "message_sid": message, "mime_type": "audio/ogg"}}
    assert whatsapp_audio.download_audio(event, settings=settings) == (b"OggS", "audio/ogg")
    assert calls[0][1]["auth"] == (account, "test-token")


def test_audio_read_caps_stream_without_content_length():
    class Response:
        status_code = 200
        headers = {}
        closed = False

        def iter_content(self, _size):
            yield b"x" * 7
            yield b"y" * 7

        def close(self):
            self.closed = True

    response = Response()
    with pytest.raises(whatsapp_audio.AudioMediaError, match="audio_too_large"):
        whatsapp_audio._read(response, 10)
    assert response.closed


def test_cloud_voice_note_is_transcribed_after_signature_and_tenant_checks(client, app, monkeypatch, wa_config):
    calls = []
    runtime = app.container.for_tenant("EXAMPLE")
    runtime.handler.handle = lambda message, **kwargs: calls.append((message, kwargs)) or {
        "reply": "A useful reply", "intent": "faq"}
    monkeypatch.setattr("routes.whatsapp_routes.download_audio", lambda event, settings: (b"voice", "audio/ogg"))
    monkeypatch.setattr("service.speech_transcription.transcribe_audio", lambda data, mime, **kwargs: "Do you offer consultations?")
    payload = {"entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": "phone-id"},
        "messages": [{"id": "wamid.voice-new", "from": "447700900123", "type": "audio",
                      "audio": {"id": "998877", "mime_type": "audio/ogg"}}],
    }}]}]}
    body = json.dumps(payload).encode()
    signature = hmac.new(b"configured-secret", body, hashlib.sha256).hexdigest()
    response = client.post("/whatsapp/webhook", data=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": "sha256=" + signature})
    assert response.status_code == 200
    assert calls[0][0] == "Do you offer consultations?"
    assert calls[0][1]["metadata"]["input_method"] == "voice"


def test_twilio_voice_note_uses_signed_form(client, app, monkeypatch, wa_config):
    calls = []
    runtime = app.container.for_tenant("EXAMPLE")
    runtime.handler.handle = lambda message, **kwargs: calls.append(message) or {
        "reply": "Yes, we can help", "intent": "faq"}
    monkeypatch.setattr("routes.whatsapp_routes.download_audio", lambda event, settings: (b"voice", "audio/ogg"))
    monkeypatch.setattr("service.speech_transcription.transcribe_audio", lambda data, mime, **kwargs: "Can you help me?")
    form = {"Body": "", "From": "whatsapp:+447700900123", "To": "whatsapp:+447700900999",
            "MessageSid": "SMvoice-new", "NumMedia": "1", "MediaContentType0": "audio/ogg",
            "MediaUrl0": "https://api.twilio.com/voice"}
    signature = RequestValidator("configured-token").compute_signature(
        app.container.settings.BASE_URL + "/whatsapp/webhook", form)
    response = client.post("/whatsapp/webhook", data=form, headers={"X-Twilio-Signature": signature})
    assert response.status_code == 200
    assert calls == ["Can you help me?"]
