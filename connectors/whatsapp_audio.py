"""Bounded, authenticated downloads for signed WhatsApp voice webhooks."""
from __future__ import annotations

import json
import os
import re
from urllib.parse import urlsplit

import requests

from app.config import Settings

MAX_AUDIO_BYTES = 10 * 1024 * 1024
_MIME_TYPES = {"audio/ogg", "audio/mpeg", "audio/mp4", "audio/wav", "audio/webm"}
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_TWILIO_ACCOUNT = re.compile(r"^AC[0-9a-fA-F]{32}$")
_TWILIO_MESSAGE = re.compile(r"^(?:SM|MM)[0-9a-fA-F]{32}$")
_TWILIO_PATH = re.compile(
    r"^/2010-04-01/Accounts/(AC[0-9a-fA-F]{32})/Messages/"
    r"((?:SM|MM)[0-9a-fA-F]{32})/Media/(ME[0-9a-fA-F]{32})$"
)


class AudioMediaError(ValueError):
    """A voice message cannot safely be downloaded or transcribed."""


def _mime(value: object) -> str:
    mime = str(value or "").split(";", 1)[0].strip().lower()
    if mime not in _MIME_TYPES:
        raise AudioMediaError("unsupported_audio_type")
    return mime


def _read(response: requests.Response, limit: int) -> bytes:
    try:
        if response.status_code != 200:
            raise AudioMediaError("media_unavailable")
        length = response.headers.get("Content-Length")
        if length:
            try:
                declared_size = int(length)
            except ValueError as exc:
                raise AudioMediaError("invalid_media_length") from exc
            if declared_size < 0:
                raise AudioMediaError("invalid_media_length")
            if declared_size > limit:
                raise AudioMediaError("audio_too_large")
        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_content(64 * 1024):
            size += len(chunk)
            if size > limit:
                raise AudioMediaError("audio_too_large")
            chunks.append(chunk)
        if not size:
            raise AudioMediaError("empty_audio")
        return b"".join(chunks)
    finally:
        response.close()


def _get(url: str, *, headers: dict[str, str] | None = None,
         auth: tuple[str, str] | None = None, limit: int = MAX_AUDIO_BYTES) -> bytes:
    try:
        response = requests.get(url, headers=headers, auth=auth, stream=True,
                                allow_redirects=False, timeout=(3, 12))
        return _read(response, limit)
    except requests.RequestException as exc:
        raise AudioMediaError("media_unavailable") from exc


def _meta(event: dict, settings: Settings) -> tuple[bytes, str]:
    audio = event.get("audio") or {}
    media_id = audio.get("id")
    phone_id = audio.get("phone_number_id")
    if not isinstance(media_id, str) or not _SAFE_ID.fullmatch(media_id):
        raise AudioMediaError("invalid_media_id")
    if not isinstance(phone_id, str) or not _SAFE_ID.fullmatch(phone_id):
        raise AudioMediaError("invalid_phone_id")
    if not settings.WHATSAPP_TOKEN:
        raise AudioMediaError("media_not_configured")
    base = settings.WHATSAPP_API_URL.rstrip("/")
    parsed_base = urlsplit(base)
    if parsed_base.scheme != "https" or parsed_base.hostname != "graph.facebook.com" or parsed_base.port:
        raise AudioMediaError("invalid_media_api")
    headers = {"Authorization": f"Bearer {settings.WHATSAPP_TOKEN}"}
    metadata_bytes = _get(f"{base}/{media_id}?phone_number_id={phone_id}",
                          headers=headers, limit=16 * 1024)
    try:
        metadata = json.loads(metadata_bytes)
    except (ValueError, TypeError) as exc:
        raise AudioMediaError("invalid_media_metadata") from exc
    if not isinstance(metadata, dict) or str(metadata.get("id")) != media_id:
        raise AudioMediaError("invalid_media_metadata")
    size = metadata.get("file_size")
    if not isinstance(size, int) or size <= 0 or size > MAX_AUDIO_BYTES:
        raise AudioMediaError("audio_too_large")
    mime = _mime(metadata.get("mime_type"))
    if audio.get("mime_type") and _mime(audio["mime_type"]) != mime:
        raise AudioMediaError("audio_type_mismatch")
    url = metadata.get("url")
    if not isinstance(url, str):
        raise AudioMediaError("invalid_media_url")
    parsed_url = urlsplit(url)
    if (parsed_url.scheme != "https" or parsed_url.hostname not in
            {"lookaside.fbsbx.com", "graph.facebook.com"} or parsed_url.port or
            parsed_url.username or parsed_url.password):
        raise AudioMediaError("invalid_media_url")
    data = _get(url, headers=headers)
    if len(data) != size:
        raise AudioMediaError("media_size_mismatch")
    return data, mime


def _twilio(event: dict, settings: Settings) -> tuple[bytes, str]:
    audio = event.get("audio") or {}
    mime = _mime(audio.get("mime_type"))
    url = audio.get("url")
    if not isinstance(url, str):
        raise AudioMediaError("invalid_media_url")
    parsed = urlsplit(url)
    match = _TWILIO_PATH.fullmatch(parsed.path)
    if (parsed.scheme != "https" or parsed.hostname != "api.twilio.com" or
            parsed.port or parsed.username or parsed.password or parsed.query or
            parsed.fragment or not match):
        raise AudioMediaError("invalid_media_url")
    account_sid, message_sid, _ = match.groups()
    if (account_sid != audio.get("account_sid") or
            message_sid != audio.get("message_sid") or
            not _TWILIO_ACCOUNT.fullmatch(account_sid) or
            not _TWILIO_MESSAGE.fullmatch(message_sid)):
        raise AudioMediaError("media_identity_mismatch")
    configured_account = os.getenv("TWILIO_ACCOUNT_SID", "")
    if configured_account and configured_account != account_sid:
        raise AudioMediaError("media_identity_mismatch")
    api_key = os.getenv("TWILIO_API_KEY", "")
    api_secret = os.getenv("TWILIO_API_SECRET", "")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "") or settings.TWILIO_AUTH_TOKEN
    if api_key and api_secret:
        auth = (api_key, api_secret)
    elif auth_token:
        auth = (account_sid, auth_token)
    else:
        raise AudioMediaError("media_not_configured")
    return _get(url, auth=auth), mime


def download_audio(event: dict, *, settings: Settings) -> tuple[bytes, str]:
    """Return transient audio bytes and MIME type from a verified webhook event."""
    if event.get("source") == "cloud":
        return _meta(event, settings)
    if event.get("source") == "twilio":
        return _twilio(event, settings)
    raise AudioMediaError("unsupported_provider")
