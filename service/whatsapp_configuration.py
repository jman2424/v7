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


def setup_urls(settings) -> dict:
    """Use the configured public origin, never an untrusted request Host header."""
    origin = getattr(settings, "BASE_URL", "")
    valid = False
    if isinstance(origin, str) and not any(
            char.isspace() or ord(char) < 32 or ord(char) == 127 or char == "\\" for char in origin):
        try:
            parsed = urlsplit(origin)
            valid = bool(parsed.scheme == "https" and parsed.hostname and parsed.port != 0
                         and not (parsed.username or parsed.password or parsed.query or parsed.fragment)
                         and parsed.path in {"", "/"})
        except ValueError:
            pass
    origin = origin.rstrip("/") if valid else ""
    return {"webhook_url": origin + "/whatsapp/webhook" if origin else "",
            "status_callback_url": origin + "/whatsapp/status" if origin else "",
            "public_https": valid}


def setup_billing(tenant: str, *, include_costs: bool = False) -> dict:
    """Operational plan limits without invoice, payment or credential details."""
    from service import plan_usage, subscriptions, usage_wallet
    from service.plan_catalog import get_plan

    internal = subscriptions.internal_business(tenant)
    state = None if internal else subscriptions.plan_state(tenant)
    allowance = None
    ai_budget = None
    usage_credit = None
    ai_processing_paused = False
    plan = None
    message_usage_model = "message_count"
    kind = "internal" if internal else "unselected"
    if state:
        selected = get_plan(state["active_plan"] or state["selected_plan"])
        message_usage_model = selected.get("message_usage_model", "message_count")
        fields = ("id", "name", "monthly_pence", "setup_pence", "whatsapp_messages")
        plan = {field: selected[field] for field in fields}
        if include_costs:
            plan["ai_budget_pence"] = selected.get("ai_budget_pence", 0)
        usage = plan_usage.report(tenant, include_costs=include_costs)
        if usage:
            allowance = {"month": usage["month"], **usage["whatsapp_messages"]}
            if include_costs and "ai_budget" in usage and usage["ai_budget"].get("active", True):
                ai_budget = {"month": usage["month"], **usage["ai_budget"]}
        kind = "tiered"
    elif not internal:
        with subscriptions.connection(tenant) as db:
            if db.execute("SELECT 1 FROM billing_contracts WHERE tenant=? AND "
                          "(subscription IS NOT NULL OR implementation_paid=1 OR status!='not_started' OR checkout IS NOT NULL) LIMIT 1",
                          (tenant,)).fetchone():
                kind = "legacy"
    if not internal:
        # Central provider calls always use prepaid credit, including legacy
        # subscriptions. Setup permissions expose only operational status.
        credit = usage_wallet.report(tenant, include_costs=include_costs, limit=1)
        ai_processing_paused = credit["paused"]
        if include_costs:
            usage_credit = credit
    result = {"kind": kind, "plan": plan, "allowance": allowance,
            "included": internal or plan is not None,
            "whatsapp_paused": bool(state and state["whatsapp_paused"]),
            "vat_percent": subscriptions.VAT_PERCENT,
            "message_usage_model": message_usage_model,
            "ai_processing_paused": ai_processing_paused,
            "mode": "pause", "notifications": "dashboard"}
    if ai_budget is not None:
        result["ai_budget"] = ai_budget
    if usage_credit is not None:
        result["usage_credit"] = usage_credit
    return result


def setup_status(container, tenant: str, *, include_costs: bool = False) -> dict:
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
                               "recipient_kind": "phone_number_id" if provider == "meta" else "phone_number",
                               "display_recipients": sorted(recipients) if provider == "meta" else
                                   ["+" + normalize_recipient(number, provider) for number in sorted(recipients)],
                               "routing": routing, "missing_settings": missing,
                               "invalid_settings": ["WHATSAPP_API_URL"] if invalid else []}

    active = bool(activation(tenant)["active"])
    subscribed = bool(whatsapp_enabled(tenant))
    billing = setup_billing(tenant, include_costs=include_costs)
    quota_paused = bool(billing["allowance"] and billing["allowance"]["paused"])
    configured = any(item["configured"] for item in providers.values())
    blockers = []
    if not configured:
        blockers.append({"code": "whatsapp_not_configured",
                         "action": "Configure an enabled provider and assign its recipient to this company."})
    if not active:
        blockers.append({"code": "tenant_inactive", "action": "Complete company activation."})
    if not subscribed:
        blockers.append({"code": "whatsapp_subscription_inactive", "action": "Activate WhatsApp access for this company."})
    if quota_paused:
        blockers.append({"code": "whatsapp_allowance_exhausted",
                         "action": "The monthly inbound-message allowance is used up. Messages resume with next month's allowance; the admin can review this in Subscription."})
    voice = transcription_status()
    voice_configured = voice["configured"]
    from service.subscriptions import internal_business
    voice_processing_ready = voice["compressed_audio_supported"] and (internal_business(tenant) or (
        voice["bounded_audio_model"] and not billing["ai_processing_paused"]))
    meta_media = providers["meta"]["configured"] and valid_meta_api_url(settings.WHATSAPP_API_URL, media=True)
    media_configured = meta_media or providers["twilio"]["configured"]
    return {"provider_mode": getattr(settings, "WHATSAPP_PROVIDER_MODE", "auto"),
            "ready": configured and active and subscribed and not quota_paused, "check_type": "local_configuration",
            "blockers": blockers, "providers": providers,
            "setup": setup_urls(settings), "billing": billing,
            "voice": {"configured": voice_configured, "ready": voice_configured and voice_processing_ready and media_configured and active and subscribed and not quota_paused,
                      "transcription_model": voice["model"], "reply_mode": "text",
                      "bounded_audio_model": voice["bounded_audio_model"],
                      "compressed_audio_supported": voice["compressed_audio_supported"],
                      "supported_audio_formats": voice["supported_audio_formats"],
                      "missing_settings": voice["missing_settings"],
                      "meta_media_configured": meta_media,
                      "invalid_settings": ["WHATSAPP_API_URL"] if providers["meta"]["configured"] and not media_configured else []},
            "tenant_active": active, "subscription_enabled": subscribed}
