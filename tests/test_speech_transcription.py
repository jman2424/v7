from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

import pytest

from routes import webchat_routes
from service.rate_limit import RateLimiter
from service import analytics_db, api_usage, speech_transcription


def test_transcription_requires_configuration_and_valid_audio(monkeypatch):
    audio = b"OggS" + b"\x00" * 32
    with pytest.raises(speech_transcription.SpeechTranscriptionError) as missing:
        speech_transcription.transcribe_audio(audio, "audio/ogg; codecs=opus")
    assert missing.value.code == "transcription_unavailable"

    with pytest.raises(speech_transcription.SpeechTranscriptionError) as wrong_format:
        speech_transcription.transcribe_audio(audio, "text/plain")
    assert wrong_format.value.code == "unsupported_audio"

    with pytest.raises(speech_transcription.SpeechTranscriptionError) as wrong_bytes:
        speech_transcription.transcribe_audio(b"not audio", "audio/ogg")
    assert wrong_bytes.value.code == "invalid_audio"


def test_transcription_uses_bounded_model_and_returns_text(monkeypatch):
    called = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            called["client"] = kwargs
            self.audio = SimpleNamespace(transcriptions=SimpleNamespace(create=self.create))

        def create(self, **kwargs):
            called["request"] = kwargs
            return SimpleNamespace(text="  Could I book a consultation?  ")

    monkeypatch.setenv("OPENAI_API_KEY", "test-only-value")
    monkeypatch.setenv("V7_TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe")
    monkeypatch.setattr(speech_transcription, "OpenAI", FakeOpenAI)

    assert speech_transcription.transcribe_audio(b"OggS" + b"\x00" * 32, "audio/ogg; codecs=opus") == "Could I book a consultation?"
    assert called["request"]["model"] == "gpt-4o-mini-transcribe"
    assert called["request"]["file"][0] == "message.ogg"
    assert called["client"]["max_retries"] == 0


def test_transcription_records_tenant_cost_without_audio(tmp_path, monkeypatch):
    class FakeOpenAI:
        def __init__(self, **_kwargs):
            self.audio = SimpleNamespace(transcriptions=SimpleNamespace(
                create=lambda **_params: SimpleNamespace(
                    text="Book a call", usage=SimpleNamespace(type="duration", seconds=12))))

    monkeypatch.setenv("OPENAI_API_KEY", "test-only-value")
    monkeypatch.setenv("V7_TRANSCRIPTION_MODEL", "gpt-transcribe")
    monkeypatch.setattr(analytics_db, "DB_PATH", str(tmp_path / "usage.db"))
    monkeypatch.setattr(speech_transcription, "OpenAI", FakeOpenAI)
    result = speech_transcription.transcribe_audio(
        b"OggS" + b"\x00" * 32, "audio/ogg", tenant="EXAMPLE", channel="web")
    assert result == "Book a call"
    usage = api_usage.summary("EXAMPLE", 30)
    assert usage["totals"]["audio_seconds"] == 12
    assert usage["totals"]["estimated_cost_usd"] == pytest.approx(0.0009)
    assert usage["breakdown"][0]["purpose"] == "transcription"


def test_widget_transcription_checks_token_origin_and_returns_reviewable_text(client, app, monkeypatch):
    monkeypatch.setattr(webchat_routes, "_transcription_limit", RateLimiter(capacity=3, refill_per_sec=3 / 60))
    monkeypatch.setattr(webchat_routes, "transcribe_audio", lambda _data, _mime, **_kwargs: "Please call me")
    with app.app_context():
        token = webchat_routes._transcription_signer().dumps({"tenant": "EXAMPLE"})
        other_token = webchat_routes._transcription_signer().dumps({"tenant": "OTHER"})

    def post(signed, origin=None):
        headers = {"X-V7-Transcription-Token": signed}
        if origin:
            headers["Origin"] = origin
        return client.post(
            "/chat/transcribe?tenant=EXAMPLE",
            data={"audio": (BytesIO(b"\x1a\x45\xdf\xa3" + b"\x00" * 32), "voice.webm", "audio/webm")},
            headers=headers,
        )

    assert post("").status_code == 403
    assert post(other_token).status_code == 403
    assert post(token, "https://unapproved.example").status_code == 403
    response = post(token)
    assert response.status_code == 200
    assert response.get_json() == {"text": "Please call me"}
    assert response.headers["Cache-Control"] == "no-store"


def test_widget_accepts_audio_above_normal_json_request_limit(client, app, monkeypatch):
    monkeypatch.setattr(webchat_routes, "transcribe_audio", lambda _data, _mime, **_kwargs: "Hello")
    with app.app_context():
        token = webchat_routes._transcription_signer().dumps({"tenant": "EXAMPLE"})
    audio = b"\x1a\x45\xdf\xa3" + b"\x00" * (1_200_000 - 4)
    response = client.post("/chat/transcribe?tenant=EXAMPLE",
        data={"audio": (BytesIO(audio), "voice.webm", "audio/webm")},
        headers={"X-V7-Transcription-Token": token})
    assert response.status_code == 200
    assert response.get_json() == {"text": "Hello"}
