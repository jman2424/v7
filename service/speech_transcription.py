"""Bounded, in-memory transcription for customer voice messages."""

from __future__ import annotations

import logging
import os
import io
import wave
from decimal import Decimal, ROUND_CEILING

from openai import OpenAI, OpenAIError

logger = logging.getLogger(__name__)

MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_TRANSCRIPT_CHARS = 4000
_FORMATS = {
    "audio/ogg": ("message.ogg", b"OggS"),
    "audio/webm": ("message.webm", b"\x1a\x45\xdf\xa3"),
    "audio/wav": ("message.wav", b"RIFF"),
    "audio/x-wav": ("message.wav", b"RIFF"),
    "audio/mpeg": ("message.mp3", None),
    "audio/mp3": ("message.mp3", None),
    "audio/mp4": ("message.m4a", None),
    "audio/m4a": ("message.m4a", None),
    "audio/x-m4a": ("message.m4a", None),
}
_MODELS = {"gpt-transcribe", "gpt-4o-transcribe", "gpt-4o-mini-transcribe"}


def transcription_status() -> dict:
    """Safe local setup details shared by management and transcription runtime."""
    model = os.getenv("V7_TRANSCRIPTION_MODEL", "gpt-transcribe").strip()
    missing = [] if os.getenv("OPENAI_API_KEY", "").strip() else ["OPENAI_API_KEY"]
    if model not in _MODELS:
        missing.append("V7_TRANSCRIPTION_MODEL")
    from service.audio_decoder import compressed_formats
    compressed = compressed_formats()
    return {"configured": not missing, "model": model if model in _MODELS else "", "missing_settings": missing,
            "bounded_audio_model": model == "gpt-transcribe",
            "compressed_audio_supported": bool(compressed),
            "supported_audio_formats": ["audio/wav", "audio/x-wav"] + compressed}


class SpeechTranscriptionError(Exception):
    """Safe error code for callers; provider details stay in server logs."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _format(data: bytes, mime_type: str) -> tuple[str, str]:
    media_type = (mime_type or "").split(";", 1)[0].strip().lower()
    details = _FORMATS.get(media_type)
    if details is None:
        raise SpeechTranscriptionError("unsupported_audio")
    filename, magic = details
    if not data or (magic is not None and not data.startswith(magic)):
        raise SpeechTranscriptionError("invalid_audio")
    if filename.endswith(".wav") and data[8:12] != b"WAVE":
        raise SpeechTranscriptionError("invalid_audio")
    if filename.endswith(".mp3") and not (
        data.startswith(b"ID3") or (len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0)
    ):
        raise SpeechTranscriptionError("invalid_audio")
    if filename.endswith(".m4a") and (len(data) < 12 or data[4:8] != b"ftyp"):
        raise SpeechTranscriptionError("invalid_audio")
    return filename, media_type


def transcribe_audio(data: bytes, mime_type: str, *, tenant: str | None = None,
                     channel: str | None = None) -> str:
    """Return a bounded transcript, without saving the recording on the server."""
    if not isinstance(data, bytes) or not data:
        raise SpeechTranscriptionError("invalid_audio")
    if len(data) > MAX_AUDIO_BYTES:
        raise SpeechTranscriptionError("audio_too_large")
    filename, media_type = _format(data, mime_type)
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise SpeechTranscriptionError("transcription_unavailable")
    setup = transcription_status()
    if not setup["configured"]:
        raise SpeechTranscriptionError("transcription_unavailable")
    model = setup["model"]
    from service import api_usage, subscriptions, usage_wallet, session_store
    from service.usage_pricing import snapshot
    if (not isinstance(tenant, str) or not session_store._TENANT_KEY.fullmatch(tenant)
            or not isinstance(channel, str) or not channel or len(channel) > 64):
        raise SpeechTranscriptionError("transcription_unavailable")
    try:
        pricing = snapshot()
    except ValueError:
        raise SpeechTranscriptionError("transcription_unavailable") from None
    reservation = None
    # The operator's internal agent also gets the same input bound. A compressed
    # recording's claimed duration never controls the provider side effect.
    if media_type not in {"audio/wav", "audio/x-wav"}:
        from service.audio_decoder import AudioDecodeError, decode_wav
        try:
            data = decode_wav(data, media_type)
        except AudioDecodeError as exc:
            raise SpeechTranscriptionError(exc.code) from None
        filename, media_type = "message.wav", "audio/wav"
    try:
        with wave.open(io.BytesIO(data), "rb") as recording:
            seconds = Decimal(recording.getnframes()) / recording.getframerate()
            if (recording.getcomptype() != "NONE" or not 0 < seconds <= 60
                    or recording.getnchannels() not in (1, 2)
                    or recording.getsampwidth() not in (1, 2, 3, 4)
                    or not 8000 <= recording.getframerate() <= 192000):
                raise ValueError("unbounded_audio")
            parameters = recording.getparams()
            frames = recording.readframes(parameters.nframes)
            if len(frames) != parameters.nframes * parameters.sampwidth * parameters.nchannels:
                raise ValueError("truncated_audio")
        # Only one verified segment goes to the provider, excluding hidden chunks.
        output = io.BytesIO()
        with wave.open(output, "wb") as recording:
            recording.setparams(parameters)
            recording.writeframes(frames)
        data = output.getvalue()
    except (wave.Error, EOFError, ValueError, ZeroDivisionError):
        raise SpeechTranscriptionError("audio_duration_unverified") from None
    if not subscriptions.internal_business(tenant):
        if model != "gpt-transcribe":
            raise SpeechTranscriptionError("audio_duration_unverified")
        billed_seconds = seconds.quantize(Decimal("1"), rounding=ROUND_CEILING) + 1
        rate = pricing.audio_duration.get(model)
        ceiling = int(billed_seconds * rate) if rate is not None else None
        try:
            reservation = usage_wallet.reserve_usage(tenant, ceiling,
                {"requested_model": model, "channel": channel, "purpose": "transcription",
                 "status": "pending", "price_version": pricing.version,
                 "rate_snapshot": {"audio_second": rate} if rate is not None else {}})
        except usage_wallet.UsagePaused:
            raise SpeechTranscriptionError("ai_allowance_paused") from None
    result = None
    status = "failed"
    try:
        result = OpenAI(api_key=api_key, timeout=30.0, max_retries=0).audio.transcriptions.create(
            model=model, file=(filename, data, media_type), response_format="json",
        )
        status = "completed"
    except OpenAIError as exc:
        if api_usage.rejected_before_inference(exc):
            # An explicit pre-inference provider rejection releases the hold;
            # uncertain failures still retain funds for review.
            result = {"usage": {"type": "duration", "seconds": 0}}
        logger.warning("Audio transcription provider error: %s", type(exc).__name__)
        raise SpeechTranscriptionError("transcription_failed") from exc
    finally:
        details = api_usage.transcription_usage(result, model, status, pricing=pricing)
        details["channel"] = channel
        try:
            with api_usage.usage_context(tenant, channel):
                api_usage.record_transcription(result, model, status, pricing=pricing)
        except Exception as exc:
            # Financial settlement does not depend on analytics persistence.
            logger.error("Transcription usage recording failed (%s)", type(exc).__name__)
        try:
            usage_wallet.settle_usage(reservation, details["cost_nano_usd"], details)
        except Exception as exc:
            logger.error("Transcription credit settlement failed (%s)", type(exc).__name__)
    transcript = getattr(result, "text", None)
    if not isinstance(transcript, str) or not transcript.strip():
        raise SpeechTranscriptionError("no_speech_detected")
    transcript = transcript.strip()
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        raise SpeechTranscriptionError("transcript_too_long")
    return transcript
