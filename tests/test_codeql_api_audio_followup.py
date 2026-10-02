"""Provider URL parsing and literal validation errors reported by CodeQL."""
import json
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlunsplit

import pytest

from connectors import whatsapp_audio
from tests import test_platform_security

platform = test_platform_security.platform

ACCOUNT = "AC" + "a" * 32
MESSAGE = "SM" + "b" * 32
MEDIA = "ME" + "c" * 32
TWILIO_PATH = f"/2010-04-01/Accounts/{ACCOUNT}/Messages/{MESSAGE}/Media/{MEDIA}"


def credential_url(host, path, username="user", password="password"):
    # Keep the hostile test URL exact without committing a credential-shaped URI.
    return urlunsplit(("https", "{}:{}@{}".format(username, password, host), path, "", ""))


@pytest.mark.parametrize("url", [
    "https://lookaside.fbsbx.com:invalid/voice",
    "https://[invalid/voice",
    "https://lookaside.fbsbx.com/vo\nice",
    "https://lookaside.fbsbx.com/vo\tice",
    "https://lookaside.fbsbx.com/voice\x7f",
    "https://lookaside.fbsbx.com/voice with spaces",
    "https://lookaside.fbsbx.com/voice\\other",
    " https://lookaside.fbsbx.com/voice",
    "https://lookaside.fbsbx.com/voice#fragment",
    "http://lookaside.fbsbx.com/voice",
    "https://localhost/voice",
    "https://127.0.0.1/voice",
    "https://10.0.0.1/voice",
    "https://[::1]/voice",
    "https://[::ffff:127.0.0.1]/voice",
    "https://169.254.169.254/voice",
    "https://lookaside.fbsbx.com@attacker.test/voice",
    "https://lookaside.fbsbx.com%2eattacker.test/voice",
    "https://lookaside.fbsbx.com.attacker.test/voice",
    credential_url("lookaside.fbsbx.com", "/voice"),
])
def test_meta_rejects_malformed_media_url_before_credentialed_download(monkeypatch, url):
    download = Mock(side_effect=[json.dumps({"id": "998877", "file_size": 3,
        "mime_type": "audio/ogg", "url": url}).encode(), b"ogg"])
    monkeypatch.setattr(whatsapp_audio, "_get", download)
    event = {"source": "cloud", "audio": {"id": "998877", "phone_number_id": "12345"}}
    settings = SimpleNamespace(WHATSAPP_TOKEN="synthetic-token",
                               WHATSAPP_API_URL="https://graph.facebook.com/v21.0")
    with pytest.raises(whatsapp_audio.AudioMediaError, match="invalid_media_url"):
        whatsapp_audio.download_audio(event, settings=settings)
    assert download.call_count == 1


@pytest.mark.parametrize("url", [
    "https://api.twilio.com:invalid" + TWILIO_PATH,
    "https://[invalid" + TWILIO_PATH,
    "https://api.twilio.com" + TWILIO_PATH.replace("Accounts", "Acco\nunts"),
    "https://api.twilio.com" + TWILIO_PATH.replace("Accounts", "Acco\tunts"),
    " https://api.twilio.com" + TWILIO_PATH,
    "https://api.twilio.com" + TWILIO_PATH + "?token=secret",
    "http://api.twilio.com" + TWILIO_PATH,
    "https://localhost" + TWILIO_PATH,
    "https://127.0.0.1" + TWILIO_PATH,
    "https://10.0.0.1" + TWILIO_PATH,
    "https://[::1]" + TWILIO_PATH,
    "https://[::ffff:127.0.0.1]" + TWILIO_PATH,
    "https://169.254.169.254" + TWILIO_PATH,
    "https://api.twilio.com@attacker.test" + TWILIO_PATH,
    "https://api.twilio.com%2eattacker.test" + TWILIO_PATH,
    "https://api.twilio.com.attacker.test" + TWILIO_PATH,
    credential_url("api.twilio.com", TWILIO_PATH),
])
def test_twilio_rejects_malformed_media_url_before_credentialed_download(monkeypatch, url):
    download = Mock(return_value=b"ogg")
    monkeypatch.setattr(whatsapp_audio, "_get", download)
    event = {"source": "twilio", "audio": {"url": url, "account_sid": ACCOUNT,
             "message_sid": MESSAGE, "mime_type": "audio/ogg"}}
    with pytest.raises(whatsapp_audio.AudioMediaError, match="invalid_media_url"):
        whatsapp_audio.download_audio(event, settings=SimpleNamespace(TWILIO_AUTH_TOKEN="synthetic-token"))
    download.assert_not_called()


def test_signed_meta_cdn_queries_and_exact_provider_url_are_preserved(monkeypatch):
    url = "https://lookaside.fbsbx.com/voice?asset_id=123&signature=synthetic-signature"
    download = Mock(side_effect=[json.dumps({"id": "998877", "file_size": 3,
        "mime_type": "audio/ogg", "url": url}).encode(), b"ogg"])
    monkeypatch.setattr(whatsapp_audio, "_get", download)
    event = {"source": "cloud", "audio": {"id": "998877", "phone_number_id": "12345"}}
    settings = SimpleNamespace(WHATSAPP_TOKEN="synthetic-token",
                               WHATSAPP_API_URL="https://graph.facebook.com:443/v21.0")
    assert whatsapp_audio.download_audio(event, settings=settings) == (b"ogg", "audio/ogg")
    assert download.call_args.args[0] == url
    assert download.call_args.kwargs["headers"] == {"Authorization": "Bearer synthetic-token"}


def test_media_transport_never_follows_redirects_or_exposes_provider_body(monkeypatch):
    response = SimpleNamespace(status_code=302, text="private provider detail", close=Mock())
    request = Mock(return_value=response)
    monkeypatch.setattr(whatsapp_audio.requests, "get", request)
    with pytest.raises(whatsapp_audio.AudioMediaError, match="^media_unavailable$"):
        whatsapp_audio._get("https://lookaside.fbsbx.com/voice")
    assert request.call_args.kwargs["allow_redirects"] is False
    response.close.assert_called_once()


def test_website_validation_response_never_echoes_url_or_credentials(platform):
    app = platform[0]
    app.container.storage.write_json("ALPHA", "store_info.json", {
        "name": "Alpha", "website": credential_url("business.example", "/", "private-user", "private-password"),
    })
    client = app.test_client()
    csrf = test_platform_security.login(client)
    response = client.post("/admin/api/website-knowledge/import", json={}, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 422
    assert response.json == {"error": "Only public HTTPS websites on the standard port can be imported."}
    assert "private-password" not in response.text


def test_action_validation_response_never_echoes_customer_text(platform):
    app = platform[0]
    client = app.test_client()
    csrf = test_platform_security.login(client)
    response = client.put("/admin/api/sales-actions", json={
        "consultation": {"enabled": True, "slots": [
            {"id": "first", "start_at": "private-customer-record", "label": "Consultation"},
        ]}, "quote": {"enabled": False}, "callback": {"enabled": False},
    }, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 400
    assert response.json == {"error": "A slot needs a valid ISO start time"}
    assert "private-customer-record" not in response.text
