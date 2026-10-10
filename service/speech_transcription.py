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
    return {"configured": not missing, "model": model if model in _MODELS else "", "missing_settings": missing}


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
    from service import api_usage, plan_usage
    reservation = None
    if tenant and plan_usage._plan(tenant) is not None:
        # Only duration-billed transcription with server-verifiable PCM audio
        # has a safe ceiling. Compressed recordings can contain arbitrarily long
        # audio; the browser's claimed duration is not a trusted billing input.
        if model != "gpt-transcribe" or media_type not in {"audio/wav", "audio/x-wav"}:
            raise SpeechTranscriptionError("audio_duration_unverified")
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
            # Canonicalize one verified audio segment; a second hidden data
            # chunk must not increase the provider input beyond its reservation.
            output = io.BytesIO()
            with wave.open(output, "wb") as recording:
                recording.setparams(parameters)
                recording.writeframes(frames)
            data = output.getvalue()
        except (wave.Error, EOFError, ValueError, ZeroDivisionError):
            raise SpeechTranscriptionError("audio_duration_unverified") from None
        billed_seconds = seconds.quantize(Decimal("1"), rounding=ROUND_CEILING) + 1
        ceiling = int(billed_seconds * api_usage._AUDIO_DURATION_RATES[model])
        try:
            reservation = plan_usage.reserve_ai(tenant, ceiling)
        except plan_usage.AllowancePaused:
            raise SpeechTranscriptionError("ai_allowance_paused") from None
    result = None
    status = "failed"
    try:
        result = OpenAI(api_key=api_key, timeout=30.0, max_retries=0).audio.transcriptions.create(
            model=model, file=(filename, data, media_type), response_format="json",
        )
        status = "completed"
    except OpenAIError as exc:
        logger.warning("Audio transcription provider error: %s", type(exc).__name__)
        raise SpeechTranscriptionError("transcription_failed") from exc
    finally:
        cost = None
        if tenant and channel:
            try:
                from service.api_usage import record_transcription, usage_context
                with usage_context(tenant, channel):
                    cost = record_transcription(result, model, status)
            except Exception as exc:
                # Usage storage must not discard a paid transcription.
                logger.error("Transcription usage recording failed (%s)", type(exc).__name__)
        try:
            plan_usage.settle_ai(reservation, cost)
        except Exception as exc:
            logger.error("Transcription allowance settlement failed (%s)", type(exc).__name__)
    transcript = getattr(result, "text", None)
    if not isinstance(transcript, str) or not transcript.strip():
        raise SpeechTranscriptionError("no_speech_detected")
    transcript = transcript.strip()
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        raise SpeechTranscriptionError("transcript_too_long")
    return transcript
