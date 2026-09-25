"""Bounded, in-memory transcription for customer voice messages."""

from __future__ import annotations

import logging
import os

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
    model = os.getenv("V7_TRANSCRIPTION_MODEL", "gpt-transcribe").strip()
    if model not in _MODELS:
        raise SpeechTranscriptionError("transcription_unavailable")
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
        if tenant and channel:
            try:
                from service.api_usage import record_transcription, usage_context
                with usage_context(tenant, channel):
                    record_transcription(result, model, status)
            except Exception as exc:
                # Usage storage must not discard a paid transcription.
                logger.error("Transcription usage recording failed (%s)", type(exc).__name__)
    transcript = getattr(result, "text", None)
    if not isinstance(transcript, str) or not transcript.strip():
        raise SpeechTranscriptionError("no_speech_detected")
    transcript = transcript.strip()
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        raise SpeechTranscriptionError("transcript_too_long")
    return transcript
