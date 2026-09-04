# routes/admin_api_routes.py
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List
from urllib.parse import quote

from flask import Blueprint, abort, jsonify, request, session
from jsonschema.exceptions import ValidationError

from connectors.web_widget import allowed_origins_from_branding, canonical_origin
from routes.tenancy import is_platform_operator, require_admin_role, require_platform_operator, resolve_admin_tenant, user_roles

logger = logging.getLogger("ADMIN.API")
bp = Blueprint("admin_api", __name__, url_prefix="/admin/api")


@bp.before_request
def _require_admin_session() -> None:
    if not session.get("user"):
        abort(401, description="unauthorized")
    require_admin_role()


def _safe_import(name: str, fallback: Callable[..., Any]) -> Callable[..., Any]:
    """
    Always import analytics_db lazily so app boots even if analytics module is missing.
    """
    try:
        from service import analytics_db  # type: ignore

        fn = getattr(analytics_db, name, None)
        if callable(fn):
            return fn  # type: ignore[return-value]
        logger.warning("analytics_db.%s missing; using fallback", name)
        return fallback
    except Exception as e:
        logger.exception("Failed importing analytics_db.%s (%s); using fallback", name, e)
        return fallback


def _fb_dict(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    return {}


def _fb_list(*args: Any, **kwargs: Any) -> List[Dict[str, Any]]:
    return []


# Canonical analytics functions (pulled from service/analytics_db.py)
get_kpis = _safe_import("get_kpis", _fb_dict)
get_timeseries = _safe_import("get_timeseries", _fb_list)
get_sessions_timeseries = _safe_import("get_sessions_timeseries", _fb_list)
get_channels_split = _safe_import("get_channels_split", _fb_dict)
get_top_intents = _safe_import("get_top_intents", _fb_list)
get_fallbacks = _safe_import("get_fallbacks", _fb_list)
get_errors = _safe_import("get_errors", _fb_list)
get_common_questions = _safe_import("get_common_questions", _fb_list)
get_leads = _safe_import("get_leads", _fb_list)

# NEW: per-day overview used by charts.js (overview chart)
get_overview_daily = _safe_import("get_overview_daily", _fb_list)

# Optional extras
get_channel_breakdown = _safe_import("get_channel_breakdown", _fb_dict)
get_whatsapp_store_share = _safe_import("get_whatsapp_store_share", _fb_list)


def _tenant() -> str:
    try:
        from routes import get_container

        c = get_container()
        return resolve_admin_tenant(
            request.args.get("tenant") or "",
            str(getattr(c.settings, "BUSINESS_KEY", "") or "default"),
        )
    except Exception:
        raise


def _int_arg(name: str, default: int) -> int:
    try:
        return int(request.args.get(name) or default)
    except Exception:
        return default


def _storage():
    from routes import get_container

    c = get_container()
    return c.storage


def _invalidate_tenant(tenant: str) -> None:
    from routes import get_container

    get_container().invalidate_tenant(tenant)


def _audit(action: str, target: str, before: Any = None, after: Any = None) -> None:
    try:
        from services.audit import AuditService

        user = session.get("user") or {}
        AuditService().record(
            user=str(user.get("email") or user.get("username") or user.get("id") or "admin"),
            role=str((user.get("roles") or [user.get("role") or "admin"])[0]),
            ip=request.remote_addr or "",
            action=action,
            target=target,
            before=before if isinstance(before, dict) else None,
            after=after if isinstance(after, dict) else None,
        )
    except Exception:
        logger.exception("audit failed action=%s target=%s", action, target)


@bp.get("/tenants")
def api_tenants_get():
    require_platform_operator()
    from service.tenant_service import TenantService

    return jsonify({"tenants": TenantService(_storage()).list_tenants()})


@bp.post("/tenants")
def api_tenants_post():
    require_platform_operator()
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "tenant_payload_must_be_object"}), 400

    from service.tenant_service import TenantService

    try:
        created = TenantService(_storage()).create_tenant(data.get("key") or "", data.get("name") or "")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    _audit("tenant.create", created["key"], after=created)
    return jsonify({"ok": True, "tenant": created}), 201


def _may_manage_accounts() -> bool:
    return is_platform_operator() or "business_owner" in user_roles()


def _account_roles(data: Dict[str, Any]) -> List[str]:
    roles = data.get("roles")
    return roles if isinstance(roles, list) else []


@bp.get("/accounts")
def api_accounts_get():
    if not _may_manage_accounts():
        abort(403, description="account_management_forbidden")
    from service.account_service import AccountService

    return jsonify({"accounts": AccountService(_storage()).list_accounts(_tenant())})


@bp.post("/accounts")
def api_accounts_post():
    if not _may_manage_accounts():
        abort(403, description="account_management_forbidden")

    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "account_payload_must_be_object"}), 400

    roles = _account_roles(data)
    if not is_platform_operator() and set(roles) != {"business_staff"}:
        abort(403, description="owner_can_only_create_staff")

    tenant = _tenant()
    from service.account_service import AccountService

    try:
        account = AccountService(_storage()).create_account(tenant, data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    _audit("account.create", f"{tenant}/{account['id']}", after=account)
    return jsonify({"ok": True, "account": account}), 201


@bp.get("/catalog")
def api_catalog_get():
    return jsonify(_storage().read_json(_tenant(), "catalog.json"))


@bp.put("/catalog")
def api_catalog_put():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "catalog_must_be_object"}), 400

    tenant = _tenant()
    before = _storage().read_json(tenant, "catalog.json")
    try:
        snap = _storage().write_json(tenant, "catalog.json", data, schema="catalog.schema.json")
    except ValidationError as exc:
        return jsonify({"error": "invalid_catalog", "detail": exc.message}), 400
    _invalidate_tenant(tenant)
    _audit("catalog.update", f"{tenant}/catalog.json", before=before, after={"snapshot": snap})
    return jsonify({"ok": True, "snapshot": snap})


@bp.get("/faq")
def api_faq_get():
    return jsonify(_storage().read_json(_tenant(), "faq.json"))


@bp.put("/faq")
def api_faq_put():
    data = request.get_json(silent=True)
    if not isinstance(data, list):
        return jsonify({"error": "faq_must_be_array"}), 400

    tenant = _tenant()
    before = _storage().read_json(tenant, "faq.json")
    try:
        snap = _storage().write_json(tenant, "faq.json", data, schema="faq.schema.json")
    except ValidationError as exc:
        return jsonify({"error": "invalid_faq", "detail": exc.message}), 400
    _invalidate_tenant(tenant)
    _audit("faq.update", f"{tenant}/faq.json", before={"items": before}, after={"snapshot": snap})
    return jsonify({"ok": True, "snapshot": snap})


@bp.get("/offers")
def api_offers_get():
    try:
        offers = _storage().read_json(_tenant(), "offers.json")
    except FileNotFoundError:
        # Existing tenants created before offers support get a clean empty list.
        offers = []
    return jsonify(offers if isinstance(offers, list) else [])


@bp.put("/offers")
def api_offers_put():
    data = request.get_json(silent=True)
    if not isinstance(data, list):
        return jsonify({"error": "offers_must_be_array"}), 400

    from retrieval.offer_store import OfferStore

    try:
        OfferStore.validate(data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    tenant = _tenant()
    storage = _storage()
    try:
        before = storage.read_json(tenant, "offers.json")
    except FileNotFoundError:
        before = []
    try:
        snap = storage.write_json(tenant, "offers.json", data, schema="offers.schema.json")
    except ValidationError as exc:
        return jsonify({"error": "invalid_offers", "detail": exc.message}), 400
    _invalidate_tenant(tenant)
    _audit("offers.update", f"{tenant}/offers.json", before={"items": before}, after={"snapshot": snap})
    return jsonify({"ok": True, "snapshot": snap})


@bp.get("/delivery")
def api_delivery_get():
    return jsonify(_storage().read_json(_tenant(), "delivery.json"))


@bp.put("/delivery")
def api_delivery_put():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "delivery_must_be_object"}), 400

    tenant = _tenant()
    before = _storage().read_json(tenant, "delivery.json")
    try:
        snap = _storage().write_json(tenant, "delivery.json", data, schema="delivery.schema.json")
    except ValidationError as exc:
        return jsonify({"error": "invalid_delivery", "detail": exc.message}), 400
    _invalidate_tenant(tenant)
    _audit("delivery.update", f"{tenant}/delivery.json", before=before, after={"snapshot": snap})
    return jsonify({"ok": True, "snapshot": snap})


@bp.get("/profile")
def api_profile_get():
    return jsonify(_storage().read_json(_tenant(), "store_info.json"))


@bp.put("/profile")
def api_profile_put():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "profile_must_be_object"}), 400

    tenant = _tenant()
    before = _storage().read_json(tenant, "store_info.json")
    try:
        snap = _storage().write_json(tenant, "store_info.json", data, schema="store_info.schema.json")
    except ValidationError as exc:
        return jsonify({"error": "invalid_profile", "detail": exc.message}), 400
    _invalidate_tenant(tenant)
    _audit("profile.update", f"{tenant}/store_info.json", before=before, after={"snapshot": snap})
    return jsonify({"ok": True, "snapshot": snap})


@bp.get("/branches")
def api_branches_get():
    return jsonify(_storage().read_json(_tenant(), "branches.json"))


@bp.put("/branches")
def api_branches_put():
    data = request.get_json(silent=True)
    if not isinstance(data, list):
        return jsonify({"error": "branches_must_be_array"}), 400

    tenant = _tenant()
    before = _storage().read_json(tenant, "branches.json")
    try:
        snap = _storage().write_json(tenant, "branches.json", data, schema="branches.schema.json")
    except ValidationError as exc:
        return jsonify({"error": "invalid_branches", "detail": exc.message}), 400
    _invalidate_tenant(tenant)
    _audit("branches.update", f"{tenant}/branches.json", before={"items": before}, after={"snapshot": snap})
    return jsonify({"ok": True, "snapshot": snap})


_TONE_STYLES = {"friendly", "professional", "concise"}


@bp.get("/agent-settings")
def api_agent_settings_get():
    overrides = _storage().read_json(_tenant(), "overrides.json")
    overrides = overrides if isinstance(overrides, dict) else {}
    tone = overrides.get("tone") or {}
    tone = tone if isinstance(tone, dict) else {}
    return jsonify(
        {
            "tone": {
                "style": str(tone.get("style") or "friendly"),
                "max_sentences": int(tone.get("max_sentences") or 2),
            }
        }
    )


@bp.put("/agent-settings")
def api_agent_settings_put():
    data = request.get_json(silent=True)
    tone = data.get("tone") if isinstance(data, dict) else None
    if not isinstance(tone, dict):
        return jsonify({"error": "tone_must_be_object"}), 400

    style = str(tone.get("style") or "").strip().lower()
    if style not in _TONE_STYLES:
        return jsonify({"error": "invalid_tone_style"}), 400
    try:
        max_sentences = int(tone.get("max_sentences") or 2)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid_max_sentences"}), 400
    if not 1 <= max_sentences <= 4:
        return jsonify({"error": "invalid_max_sentences"}), 400

    tenant = _tenant()
    storage = _storage()
    before = storage.read_json(tenant, "overrides.json")
    overrides = dict(before) if isinstance(before, dict) else {}
    overrides["tone"] = {"style": style, "max_sentences": max_sentences}
    snapshot = storage.write_json(tenant, "overrides.json", overrides)
    _invalidate_tenant(tenant)
    _audit("agent_settings.update", f"{tenant}/overrides.json", before=before, after={"snapshot": snapshot, "tone": overrides["tone"]})
    return jsonify({"ok": True, "snapshot": snapshot, "tone": overrides["tone"]})


def _clean_widget_text(value: Any, field: str, maximum: int) -> str:
    cleaned = str(value or "").strip()
    if len(cleaned) > maximum:
        abort(400, description=f"{field}_too_long")
    return cleaned


def _clean_widget_avatar(value: Any) -> str:
    avatar = _clean_widget_text(value, "avatar", 500)
    if not avatar:
        return ""
    if avatar.startswith("/"):
        return avatar
    if not avatar.startswith("https://"):
        abort(400, description="avatar_must_be_https_or_relative")
    return avatar


def _clean_allowed_origins(value: Any) -> List[str]:
    if not isinstance(value, list):
        abort(400, description="allowed_origins_must_be_array")
    if len(value) > 20:
        abort(400, description="too_many_allowed_origins")

    origins: List[str] = []
    for raw in value:
        origin = canonical_origin(str(raw or ""))
        if not origin:
            abort(400, description="invalid_allowed_origin")
        if origin.startswith("http://") and not (
            origin.startswith("http://localhost") or origin.startswith("http://127.0.0.1")
        ):
            abort(400, description="allowed_origin_requires_https")
        if origin not in origins:
            origins.append(origin)
    return origins


def _widget_response(tenant: str, branding: Dict[str, Any]) -> Dict[str, Any]:
    widget = branding.get("widget") or {}
    widget = widget if isinstance(widget, dict) else {}
    script_url = f"{request.url_root.rstrip('/')}/widget.js?tenant={quote(tenant)}"
    return {
        "tenant": tenant,
        "widget": {
            "chat_title": str(widget.get("chat_title") or "Sales assistant"),
            "greeting": str(widget.get("greeting") or "Hi! How can I help you today?"),
            "avatar": str(widget.get("avatar") or ""),
            "allowed_origins": allowed_origins_from_branding(branding),
        },
        "embed": {
            "script_url": script_url,
            "snippet": f'<script src="{script_url}" async></script>',
        },
    }


@bp.get("/widget")
def api_widget_get():
    tenant = _tenant()
    branding = _storage().read_json(tenant, "branding.json")
    if not isinstance(branding, dict):
        branding = {}
    return jsonify(_widget_response(tenant, branding))


@bp.put("/widget")
def api_widget_put():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "widget_payload_must_be_object"}), 400

    tenant = _tenant()
    storage = _storage()
    before = storage.read_json(tenant, "branding.json")
    branding = dict(before) if isinstance(before, dict) else {}
    existing = branding.get("widget") or {}
    existing = dict(existing) if isinstance(existing, dict) else {}

    widget = {
        **existing,
        "chat_title": _clean_widget_text(data.get("chat_title"), "chat_title", 80) or "Sales assistant",
        "greeting": _clean_widget_text(data.get("greeting"), "greeting", 240) or "Hi! How can I help you today?",
        "avatar": _clean_widget_avatar(data.get("avatar")),
        "allowed_origins": _clean_allowed_origins(data.get("allowed_origins", [])),
    }
    branding["widget"] = widget
    snapshot = storage.write_json(tenant, "branding.json", branding)
    _invalidate_tenant(tenant)
    _audit("widget.update", f"{tenant}/branding.json", before=before, after={"snapshot": snapshot, "widget": widget})
    return jsonify({"ok": True, "snapshot": snapshot, **_widget_response(tenant, branding)})


@bp.post("/mode")
def api_mode_set():
    data = request.get_json(silent=True) or {}
    mode = str(data.get("mode") or "").strip().upper()
    if mode not in {"V5", "V6", "V7", "AIV7", "AIV7_FLAGSHIP"}:
        return jsonify({"error": "invalid_mode"}), 400

    from routes import get_container

    c = get_container()
    object.__setattr__(c.settings, "MODE", "V7" if mode.startswith("AIV7") else mode)
    c.invalidate_tenant(c.settings.BUSINESS_KEY)
    return jsonify({"ok": True, "mode": c.settings.MODE})


@bp.get("/insights")
def api_insights():
    """
    Single endpoint the dashboard uses.

    Contract (used by dashboard/static/js/charts.js):
      - kpis
      - message_volume
      - sessions_per_bucket
      - channels_total
      - top_intents
      - fallbacks
      - overview_daily
    """
    tenant = _tenant()
    minutes = _int_arg("minutes", 1440)
    bucket = _int_arg("bucket", 60)
    top = _int_arg("top", 10)
    limit = _int_arg("limit", 50)

    # KPIs
    kpis = get_kpis(tenant=tenant, minutes=minutes)

    # Timeseries
    msg_series = get_timeseries(tenant=tenant, minutes=minutes, bucket_minutes=bucket)
    sess_series = get_sessions_timeseries(tenant=tenant, minutes=minutes, bucket_minutes=bucket)

    # Breakdowns
    channels = get_channels_split(tenant=tenant, minutes=minutes)
    intents = get_top_intents(tenant=tenant, minutes=minutes, top=top)
    fallbacks = get_fallbacks(tenant=tenant, minutes=minutes, top=top)
    errors = get_errors(tenant=tenant, minutes=minutes, top=top)
    questions = get_common_questions(tenant=tenant, minutes=minutes, top=top)
    leads = get_leads(tenant=tenant, limit=limit)

    # Overview daily series (powers the "overview" chart)
    overview_daily = get_overview_daily(tenant=tenant, minutes=minutes, limit_days=45)

    # Optional extras (safe if not implemented)
    ch_breakdown = get_channel_breakdown(tenant=tenant, minutes=minutes)
    wa_share = get_whatsapp_store_share(tenant=tenant, minutes=minutes, limit=12)

    channels_total = [{"label": ch, "count": v.get("total", 0)} for ch, v in (channels or {}).items()]

    payload = {
        "tenant": tenant,
        "window_minutes": minutes,
        "bucket_minutes": bucket,
        "kpis": kpis,
        "message_volume": msg_series,
        "sessions_per_bucket": sess_series,
        "channels": channels,
        "channels_total": channels_total,
        "channel_breakdown": ch_breakdown,
        "whatsapp_store_share": wa_share,
        "top_intents": intents,
        "fallbacks": fallbacks,
        "errors": errors,
        "common_questions": questions,
        "leads": leads,
        "overview_daily": overview_daily,
    }
    return jsonify(payload)


@bp.get("/kpis")
def api_kpis():
    minutes = _int_arg("minutes", 1440)
    return jsonify(get_kpis(tenant=_tenant(), minutes=minutes))


@bp.get("/timeseries")
def api_timeseries():
    minutes = _int_arg("minutes", 1440)
    bucket = _int_arg("bucket", 60)
    return jsonify(get_timeseries(tenant=_tenant(), minutes=minutes, bucket_minutes=bucket))


@bp.get("/sessions_timeseries")
def api_sessions_timeseries():
    minutes = _int_arg("minutes", 1440)
    bucket = _int_arg("bucket", 60)
    return jsonify(get_sessions_timeseries(tenant=_tenant(), minutes=minutes, bucket_minutes=bucket))


@bp.get("/channels")
def api_channels():
    minutes = _int_arg("minutes", 1440)
    return jsonify(get_channels_split(tenant=_tenant(), minutes=minutes))


@bp.get("/intents")
def api_intents():
    minutes = _int_arg("minutes", 1440)
    top = _int_arg("top", 10)
    return jsonify(get_top_intents(tenant=_tenant(), minutes=minutes, top=top))


@bp.get("/fallbacks")
def api_fallbacks():
    minutes = _int_arg("minutes", 1440)
    top = _int_arg("top", 10)
    return jsonify(get_fallbacks(tenant=_tenant(), minutes=minutes, top=top))


@bp.get("/errors")
def api_errors():
    minutes = _int_arg("minutes", 1440)
    top = _int_arg("top", 10)
    return jsonify(get_errors(tenant=_tenant(), minutes=minutes, top=top))


@bp.get("/questions")
def api_questions():
    minutes = _int_arg("minutes", 1440)
    top = _int_arg("top", 10)
    return jsonify(get_common_questions(tenant=_tenant(), minutes=minutes, top=top))


@bp.get("/leads")
def api_leads():
    limit = _int_arg("limit", 50)
    return jsonify(get_leads(tenant=_tenant(), limit=limit))
