"""Server-only WhatsApp routing and safe management setup diagnostics."""
from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

_META_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
_PHONE = re.compile(r"[0-9]{5,20}")


def normalize_recipient(value: object, provider: str) -> str:
    if not isinstance(value, str):
        return ""
    number = value.strip().removeprefix("whatsapp:").lstrip("+")
    pattern = _META_ID if provider == "meta" else _PHONE
    return number if pattern.fullmatch(number) else ""


def provider_enabled(settings, provider: str) -> bool:
    mode = getattr(settings, "WHATSAPP_PROVIDER_MODE", "auto")
    return mode in {"auto", "both", provider}


def has_secret(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def twilio_token(settings) -> str:
    token = os.getenv("TWILIO_AUTH_TOKEN", "") or settings.TWILIO_AUTH_TOKEN
    return token if has_secret(token) else ""


def recipient_routes(settings, provider: str) -> tuple[dict[str, str], str]:
    field = "WHATSAPP_META_TENANT_MAP" if provider == "meta" else "TWILIO_WHATSAPP_TENANT_MAP"
    dedicated = getattr(settings, field, None)
    if dedicated is not None:
        return dedicated, "dedicated_map"
    if settings.WHATSAPP_TENANT_MAP:
        return settings.WHATSAPP_TENANT_MAP, "legacy_map"
    recipient = (settings.WHATSAPP_PHONE_ID if provider == "meta" else
                 getattr(settings, "TWILIO_WHATSAPP_NUMBER", "") or os.getenv("TWILIO_WHATSAPP_NUMBER", ""))
    number = normalize_recipient(recipient, provider)
    return ({number: settings.BUSINESS_KEY} if number else {}), "default_recipient"


def recipient_tenant(settings, recipient: object, provider: str) -> str | None:
    if not provider_enabled(settings, provider):
        return None
    number = normalize_recipient(recipient, provider)
    mapping, _ = recipient_routes(settings, provider)
    return mapping.get(number) if number else None


def valid_meta_api_url(value: object, *, media: bool = False) -> bool:
    if not isinstance(value, str) or any(ord(char) < 33 or ord(char) == 127 for char in value):
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    return bool(parsed.scheme == "https" and parsed.hostname and port in {None, 443}
                and not (parsed.username or parsed.password or parsed.query or parsed.fragment)
                and (not media or parsed.hostname == "graph.facebook.com"))


def setup_status(container, tenant: str) -> dict:
    """Describe local configuration; never imply a live provider connection check."""
    from service.tenant_access import activation
    from service.subscriptions import whatsapp_enabled
    from service.speech_transcription import transcription_status

    settings = container.settings
    providers = {}
    for provider in ("meta", "twilio"):
        mapping, routing = recipient_routes(settings, provider)
        recipients = []
        for number, mapped_tenant in mapping.items():
            try:
                canonical = container.storage.canonical_tenant_key(mapped_tenant)
            except ValueError:
                continue
            if canonical == tenant and normalize_recipient(number, provider):
                recipients.append(number)
        enabled = provider_enabled(settings, provider)
        required = ({"WHATSAPP_APP_SECRET": settings.WHATSAPP_APP_SECRET,
                     "WHATSAPP_TOKEN": settings.WHATSAPP_TOKEN,
                     "WHATSAPP_VERIFY_TOKEN": settings.WHATSAPP_VERIFY_TOKEN}
                    if provider == "meta" else {"TWILIO_AUTH_TOKEN": twilio_token(settings)})
        missing = [name for name, value in required.items() if not has_secret(value)]
        if not recipients and routing == "default_recipient":
            missing.append("WHATSAPP_PHONE_ID" if provider == "meta" else "TWILIO_WHATSAPP_NUMBER")
        invalid = provider == "meta" and not valid_meta_api_url(settings.WHATSAPP_API_URL)
        configured = enabled and bool(recipients) and not missing and not invalid
        state = ("disabled" if not enabled else "unassigned" if not recipients else
                 "missing_settings" if missing else "invalid_configuration" if invalid else "configured")
        providers[provider] = {"enabled": enabled, "configured": configured, "state": state,
                               "channel": "whatsapp", "recipients": sorted(recipients),
                               "routing": routing, "missing_settings": missing,
                               "invalid_settings": ["WHATSAPP_API_URL"] if invalid else []}

    active = bool(activation(tenant)["active"])
    subscribed = bool(whatsapp_enabled(tenant))
    configured = any(item["configured"] for item in providers.values())
    blockers = []
    if not configured:
        blockers.append({"code": "whatsapp_not_configured",
                         "action": "Configure an enabled provider and assign its recipient to this company."})
    if not active:
        blockers.append({"code": "tenant_inactive", "action": "Complete company activation."})
    if not subscribed:
        blockers.append({"code": "whatsapp_subscription_inactive", "action": "Activate the WhatsApp add-on."})
    voice = transcription_status()
    voice_configured = voice["configured"]
    meta_media = providers["meta"]["configured"] and valid_meta_api_url(settings.WHATSAPP_API_URL, media=True)
    media_configured = meta_media or providers["twilio"]["configured"]
    return {"provider_mode": getattr(settings, "WHATSAPP_PROVIDER_MODE", "auto"),
            "ready": configured and active and subscribed, "check_type": "local_configuration",
            "blockers": blockers, "providers": providers,
            "voice": {"configured": voice_configured, "ready": voice_configured and media_configured and active and subscribed,
                      "transcription_model": voice["model"], "reply_mode": "text",
                      "missing_settings": voice["missing_settings"],
                      "meta_media_configured": meta_media,
                      "invalid_settings": ["WHATSAPP_API_URL"] if providers["meta"]["configured"] and not media_configured else []},
            "tenant_active": active, "subscription_enabled": subscribed}
