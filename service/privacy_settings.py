"""Validated business-provided privacy information; never a deletion schedule."""
from __future__ import annotations

import os
import re
import unicodedata
from urllib.parse import urlsplit

from service.business_management import revision

FILENAME = "privacy.json"
DEFAULTS = {"controller_name": "", "contact_email": "", "retention_days": None,
            "retention_criteria": "", "lawful_basis": ""}
_LIMITS = {"controller_name": 200, "contact_email": 254, "retention_criteria": 2000, "lawful_basis": 2000}
_EMAIL = re.compile(r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}")


def validate_settings(value: object) -> dict:
    if not isinstance(value, dict) or any(key not in DEFAULTS for key in value):
        raise ValueError("invalid_privacy_settings")
    result = dict(DEFAULTS)
    for key, limit in _LIMITS.items():
        text = value.get(key, "")
        if (not isinstance(text, str) or len(text) > limit
                or any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in text)):
            raise ValueError("invalid_privacy_" + key)
        result[key] = text.strip()
    email = result["contact_email"]
    if email and (not _EMAIL.fullmatch(email) or len(email.split("@", 1)[0]) > 64
                  or email.startswith(".") or ".." in email or ".@" in email):
        raise ValueError("invalid_privacy_contact_email")
    days = value.get("retention_days")
    if days is not None and (type(days) is not int or not 1 <= days <= 36500):
        raise ValueError("invalid_privacy_retention_days")
    result["retention_days"] = days
    return result


def platform_settings() -> dict:
    raw_days = os.getenv("V7_PRIVACY_RETENTION_DAYS", "").strip()
    try:
        days = int(raw_days) if raw_days else None
    except ValueError:
        days = raw_days  # Validation marks an invalid operator setting as a draft.
    return {"controller_name": os.getenv("V7_PRIVACY_CONTROLLER", ""),
            "contact_email": os.getenv("V7_PRIVACY_CONTACT_EMAIL", ""),
            "retention_days": days, "retention_criteria": os.getenv("V7_PRIVACY_RETENTION_CRITERIA", ""),
            "lawful_basis": os.getenv("V7_PRIVACY_LAWFUL_BASIS", "")}


def status(storage=None, tenant: str | None = None) -> dict:
    state = "saved"
    if tenant is None:
        raw = platform_settings()
    else:
        try:
            raw = storage.read_json(tenant, FILENAME)
        except FileNotFoundError:
            raw, state = dict(DEFAULTS), "missing"
        except ValueError:
            raw, state = {"invalid_document": True}, "invalid"
    try:
        settings = validate_settings(raw)
    except ValueError:
        settings, state = dict(DEFAULTS), "invalid"
    missing = [name for name in ("controller_name", "contact_email", "lawful_basis") if not settings[name]]
    if settings["retention_days"] is None and not settings["retention_criteria"]:
        missing.append("retention")
    try:
        current_revision = revision(raw)
    except (ValueError, TypeError, RecursionError):
        current_revision = revision({"invalid_document": True})
    return {"settings": settings, "revision": current_revision, "draft": bool(missing) or state == "invalid",
            "missing_details": missing, "state": state}


def processors(container, tenant: str | None) -> list[dict[str, str]]:
    """Configured processor categories without credentials, IDs or private URLs."""
    from service import registration_mail
    from service.whatsapp_configuration import has_secret, provider_enabled, recipient_routes, twilio_token
    result = []
    from app.config import valid_ga4_measurement_id
    if tenant is None and valid_ga4_measurement_id(getattr(container.settings, "GA4_MEASUREMENT_ID", "")):
        result.append({"name": "Google Analytics", "purpose": "Optional public marketing page views after analytics opt-in; no chat or account data."})
    if os.getenv("RENDER") == "true":
        result.append({"name": "Render", "purpose": "Application hosting and infrastructure logs."})
    else:
        result.append({"name": "Hosting provider selected by the operator", "purpose": "Hosting details need confirmation from the controller."})
    if os.getenv("V7_STORAGE_BACKEND", "sqlite").strip().lower() == "postgres":
        try:
            host = urlsplit(os.getenv("V7_POSTGRES_DSN", "")).hostname or ""
        except ValueError:
            host = ""
        name = "Supabase" if host.endswith((".supabase.com", ".supabase.co")) else "Configured PostgreSQL hosting provider"
        result.append({"name": name, "purpose": "Durable account, business, conversation and CRM storage."})
    if os.getenv("OPENAI_API_KEY", "").strip():
        result.append({"name": "OpenAI", "purpose": "Message excerpts for enabled AI responses; recordings when voice transcription is used."})
    if registration_mail.configured():
        result.append({"name": "Resend" if registration_mail._uses_resend_api() else "Configured email delivery provider",
                       "purpose": "Account verification email delivery."})
    if os.getenv("STRIPE_API_KEY", "").strip() and os.getenv("BILLING_PROVIDER", "stripe") == "stripe":
        result.append({"name": "Stripe", "purpose": "Payment checkout, invoicing and subscription administration."})
    for provider, name in (("meta", "Meta WhatsApp"), ("twilio", "Twilio")):
        configured = has_secret(container.settings.WHATSAPP_APP_SECRET) if provider == "meta" else bool(twilio_token(container.settings))
        routes, _ = recipient_routes(container.settings, provider)
        assigned = tenant is None and bool(routes)
        if tenant is not None:
            for mapped in routes.values():
                try:
                    assigned = assigned or container.storage.canonical_tenant_key(mapped) == tenant
                except ValueError:
                    continue
        if configured and assigned and provider_enabled(container.settings, provider):
            result.append({"name": name, "purpose": "WhatsApp message transport and inbound voice-media delivery."})
    from service.oidc_login import providers_status
    for provider in providers_status()["providers"]:
        if provider["configured"]:
            result.append({"name": provider["name"], "purpose": "Optional sign-in using an explicitly linked provider account."})
    return result
