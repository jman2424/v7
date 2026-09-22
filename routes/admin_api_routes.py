# routes/admin_api_routes.py
from __future__ import annotations

import logging
import hashlib
import secrets
from typing import Any, Callable, Dict, List
from urllib.parse import quote, urlsplit
from html import escape

from flask import Blueprint, abort, current_app, jsonify, request, session
from itsdangerous import BadSignature, URLSafeTimedSerializer
from jsonschema.exceptions import ValidationError

from connectors.web_widget import allowed_origins_from_branding, canonical_origin
from routes import get_container
from routes.session_auth import clear_authenticated_session, is_authenticated_account_active
from routes.tenancy import is_platform_operator, require_admin_role, require_platform_operator, resolve_admin_tenant, user_roles
from service.sales_playbook import SalesPlaybookValidationError, load_sales_playbook, validate_sales_playbook

logger = logging.getLogger("ADMIN.API")
bp = Blueprint("admin_api", __name__, url_prefix="/admin/api")


@bp.before_request
def _require_admin_session() -> None:
    if not session.get("user"):
        abort(401, description="unauthorized")
    if not is_authenticated_account_active(_storage()):
        clear_authenticated_session()
        abort(401, description="unauthorized")
    require_admin_role()
    if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'} and request.path not in {'/admin/api/tenants'}:
        if not is_platform_operator():
            from service.tenant_access import require_active
            require_active(_tenant())


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


def _fb_bool(*args: Any, **kwargs: Any) -> bool:
    return False


# Canonical analytics functions (pulled from service/analytics_db.py)
get_kpis = _safe_import("get_kpis", _fb_dict)
get_sales_funnel = _safe_import("get_sales_funnel", _fb_dict)
get_timeseries = _safe_import("get_timeseries", _fb_list)
get_sessions_timeseries = _safe_import("get_sessions_timeseries", _fb_list)
get_channels_split = _safe_import("get_channels_split", _fb_dict)
get_top_intents = _safe_import("get_top_intents", _fb_list)
get_fallbacks = _safe_import("get_fallbacks", _fb_list)
get_errors = _safe_import("get_errors", _fb_list)
get_common_questions = _safe_import("get_common_questions", _fb_list)
get_leads = _safe_import("get_leads", _fb_list)
update_lead_status = _safe_import("update_lead_status", _fb_bool)

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


def _int_arg(name: str, default: int, *, minimum: int = 1, maximum: int = 1000) -> int:
    try:
        value = int(request.args.get(name) or default)
    except (TypeError, ValueError):
        abort(400, description="invalid_query_parameter")
    if not minimum <= value <= maximum:
        abort(400, description="query_parameter_out_of_range")
    return value


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
    from service.security import management_user
    user = management_user()
    if not is_platform_operator() and 'business_owner' not in user_roles():
        abort(403, description='company_owner_required')
    from service.tenant_service import TenantService
    tenants = TenantService(_storage()).list_tenants()
    if not is_platform_operator():
        from service.tenant_access import owned_tenants
        allowed = {user['tenant'], *owned_tenants(user)}
        tenants = [row for row in tenants if row['key'] in allowed]
    return jsonify({"tenants": tenants})


@bp.post("/tenants")
def api_tenants_post():
    from service.security import management_user
    user = management_user()
    if not is_platform_operator() and 'business_owner' not in user_roles():
        abort(403, description='company_owner_required')
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "tenant_payload_must_be_object"}), 400

    from service.tenant_service import TenantService

    try:
        created = TenantService(_storage()).create_tenant(data.get("key") or "", data.get("name") or "", owner=None if is_platform_operator() else user)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    _audit("tenant.create", created["key"], after=created)
    return jsonify({"ok": True, "tenant": created}), 201


@bp.get('/activation')
def api_activation_get():
    from service.tenant_access import activation
    return jsonify(activation(_tenant()))


@bp.get("/api-usage")
def api_usage_get():
    from service.api_usage import summary
    from service.usage_currency import gbp_rate

    from service.security import require_permission
    require_permission('view_costs')
    tenant = _tenant()
    scope = request.args.get("scope", "company")
    if scope not in {"company", "all"}:
        abort(400, description="invalid_usage_scope")
    if scope == "all":
        require_platform_operator()
    days = _int_arg("days", 30, maximum=90)
    container = get_container().for_tenant(tenant)
    result = summary(None if scope == "all" else tenant, days)
    exchange = gbp_rate()
    for row in [result["totals"], *result["breakdown"]]:
        usd = row.pop("estimated_cost_usd")
        row["estimated_cost_gbp"] = (0.0 if usd == 0 else round(usd * exchange["rate"], 9)
                                     if usd is not None and exchange else None)
    result.update(currency="GBP", exchange_rate=exchange)
    from service import model_settings
    chosen_model = model_settings.selected(tenant,container.storage)
    brain = container.handler.h_v7.brain
    mode = str(container.overrides.get("ai.mode") or "v7").lower()
    mode = mode if mode in {"v5", "v6"} else "v7"
    result.update(scope=scope, tenant=tenant, configuration={
        "mode": mode.upper(),
        "planning_model": chosen_model or brain.config.model,
        "model_options": model_settings.options(),
        "can_change_model": bool(is_platform_operator() or user_roles() == {"business_owner"}),
        "planning_enabled": mode == "v7" and brain.client is not None,
        "rewriting_model": chosen_model or container.rewriter._model,
        "rewriting_enabled": container.rewriter._client is not None,
    })
    return jsonify(result)


@bp.post("/test-agent")
def api_test_agent():
    """Use the real tenant agent with separate test memory and no sales activity."""
    tenant = _tenant()
    from service.tenant_access import require_active
    require_active(tenant)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="json_object_required"), 400
    message = data.get("message")
    if not isinstance(message, str) or not message.strip() or len(message) > 4000:
        return jsonify(error="message_must_be_1_to_4000_characters"), 400
    signer = URLSafeTimedSerializer(current_app.secret_key, salt="console-agent-test-v1")
    owner = hashlib.sha256(session["_csrf"].encode()).hexdigest()
    token = data.get("conversation_token")
    if token:
        if not isinstance(token, str) or len(token) > 2048:
            return jsonify(error="invalid_test_conversation"), 403
        try:
            identity = signer.loads(token, max_age=3600)
        except BadSignature:
            return jsonify(error="test_conversation_expired"), 403
        if (not isinstance(identity, dict) or identity.get("tenant") != tenant
                or identity.get("owner") != owner or not isinstance(identity.get("id"), str)
                or not identity["id"].startswith("test_")):
            return jsonify(error="invalid_test_conversation"), 403
    else:
        identity = {"tenant": tenant, "owner": owner, "id": "test_" + secrets.token_urlsafe(24)}
        token = signer.dumps(identity)
    try:
        container = get_container().for_tenant(tenant)
    except ValueError:
        return jsonify(error="unknown_tenant"), 404
    try:
        result = container.handler.handle(message.strip(), tenant=tenant, session_id=identity["id"],
                                          channel="test", metadata={"source": "console_test"})
    except Exception:
        logger.exception("Agent test failed tenant=%s", tenant)
        _audit("agent.test", tenant, after={"error": True})
        return jsonify(error="agent_test_failed"), 503
    failed = not isinstance(result, dict) or result.get("intent") == "system_error"
    _audit("agent.test", tenant, after={"error": failed})
    if failed:
        return jsonify(error="agent_test_failed"), 503
    from routes.webchat_routes import _public_agent_payload
    return jsonify(reply=str(result.get("reply") or "Please rephrase your question."),
                   conversation_token=token, agent=_public_agent_payload(result))


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


@bp.get('/join-requests')
def api_join_requests():
    if not _may_manage_accounts():
        abort(403)
    from service.registration import pending
    return jsonify(requests=pending(_tenant()))


@bp.post('/join-requests/<request_id>')
def api_join_request_decision(request_id):
    if not _may_manage_accounts():
        abort(403)
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or data.get('decision') not in ('approve', 'reject'):
        return jsonify(error='Choose approve or reject.'), 400
    tenant = _tenant()
    from service.registration import decide
    try:
        decide(tenant, request_id, data['decision'] == 'approve', session['user']['email'])
    except ValueError as exc:
        return jsonify(error=str(exc)), 409
    _audit('join_request.'+data['decision'],tenant,after={'request_id':request_id,'role':'business_staff'})
    return jsonify(ok=True)


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


@bp.put("/accounts/<string:account_id>")
def api_accounts_put(account_id: str):
    if not _may_manage_accounts():
        abort(403, description="account_management_forbidden")
    if not account_id or len(account_id) > 256:
        return jsonify({"error": "invalid_account_id"}), 400

    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "account_payload_must_be_object"}), 400

    tenant = _tenant()
    from service.account_service import AccountService

    accounts = AccountService(_storage())
    existing = accounts.get_account(tenant, account_id)
    if existing is None:
        return jsonify({"error": "account_not_found"}), 404
    if not is_platform_operator() and set(existing.get("roles") or []) != {"business_staff"}:
        abort(403, description="owner_can_only_manage_staff")

    try:
        account = accounts.update_account(tenant, account_id, data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    _audit(
        "account.update",
        f"{tenant}/{account_id}",
        before={"active": existing.get("active") is not False},
        after={"active": account["active"], "permissions": account['permissions'], "password_reset": bool(str(data.get("password") or ""))},
    )
    return jsonify({"ok": True, "account": account})


@bp.get("/catalog")
def api_catalog_get():
    return jsonify(_storage().read_json(_tenant(), "catalog.json"))


@bp.put("/catalog")
def api_catalog_put():
    import math
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "catalog_must_be_object"}), 400

    tenant = _tenant()
    before = _storage().read_json(tenant, "catalog.json")
    from service.product_metrics import record_inventory
    # Quantity is optional, but when supplied it is the source of availability.
    if isinstance(data.get('categories'), list):
        skus = []
        for category in data['categories']:
            if not isinstance(category, dict) or not isinstance(category.get('items'), list):
                continue
            for item in category['items']:
                if not isinstance(item, dict):
                    continue
                skus.append(item.get('sku'))
                quantity = item.get('stock_quantity')
                for key in ('stock_quantity', 'low_stock_threshold'):
                    value = item.get(key)
                    if isinstance(value, float) and not math.isfinite(value):
                        return jsonify(error='Stock quantities must be finite numbers.'), 400
                if isinstance(quantity, (int, float)) and not isinstance(quantity, bool):
                    item['in_stock'] = quantity > 0
        if len(skus) != len(set(str(sku) for sku in skus)):
            return jsonify(error='Product references must be unique within the company.'), 400
    try:
        snap = _storage().write_json(tenant, "catalog.json", data, schema="catalog.schema.json")
    except ValidationError as exc:
        return jsonify({"error": "invalid_catalog", "detail": exc.message}), 400
    _invalidate_tenant(tenant)
    record_inventory(tenant, before, data)
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


def _agent_settings_payload(overrides: Any) -> Dict[str, Any]:
    data = overrides if isinstance(overrides, dict) else {}
    tone = data.get("tone") if isinstance(data.get("tone"), dict) else {}
    style = str(tone.get("style") or "friendly").strip().lower()
    if style not in _TONE_STYLES:
        style = "friendly"
    try:
        max_sentences = int(tone.get("max_sentences") or 2)
    except (TypeError, ValueError):
        max_sentences = 2
    max_sentences = min(max(max_sentences, 1), 4)
    return {
        "tone": {"style": style, "max_sentences": max_sentences},
        "playbook": load_sales_playbook(data),
    }


@bp.get("/agent-settings")
def api_agent_settings_get():
    overrides = _storage().read_json(_tenant(), "overrides.json")
    return jsonify(_agent_settings_payload(overrides))


@bp.put("/agent-settings")
def api_agent_settings_put():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "agent_settings_must_be_object"}), 400

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
    if "playbook" in data:
        try:
            playbook = validate_sales_playbook(data.get("playbook"))
        except SalesPlaybookValidationError as exc:
            return jsonify({"error": str(exc)}), 400
    else:
        playbook = load_sales_playbook(overrides)

    overrides["tone"] = {"style": style, "max_sentences": max_sentences}
    overrides["sales_playbook"] = playbook
    snapshot = storage.write_json(tenant, "overrides.json", overrides)
    _invalidate_tenant(tenant)
    _audit(
        "agent_settings.update",
        f"{tenant}/overrides.json",
        before=before,
        after={
            "snapshot": snapshot,
            "tone": overrides["tone"],
            "playbook": {
                "offering_type": playbook["offering_type"],
                "primary_goal": playbook["primary_goal"],
                "ideal_customer_configured": bool(playbook["ideal_customer"]),
                "value_propositions": len(playbook["value_propositions"]),
                "qualification_questions": len(playbook["qualification_questions"]),
            },
        },
    )
    return jsonify({"ok": True, "snapshot": snapshot, **_agent_settings_payload(overrides)})


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
        try:
            parsed = urlsplit(origin)
            port = parsed.port
        except ValueError:
            abort(400, description="invalid_allowed_origin")
        if not parsed.hostname or parsed.username or parsed.password or port == 0:
            abort(400, description="invalid_allowed_origin")
        if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            abort(400, description="allowed_origin_requires_https")
        if origin not in origins:
            origins.append(origin)
    return origins


def _widget_response(tenant: str, branding: Dict[str, Any]) -> Dict[str, Any]:
    widget = branding.get("widget") or {}
    widget = widget if isinstance(widget, dict) else {}
    script_url = f"{request.url_root.rstrip('/')}/widget.js?tenant={quote(tenant)}"
    chat_url = f"{request.url_root.rstrip('/')}/chat_ui?tenant={quote(tenant)}"
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
            "snippet": f'<script src="{escape(script_url, quote=True)}" async></script>',
            "chat_url": chat_url,
            "iframe_snippet": (
                f'<iframe src="{escape(chat_url + "&embed=1", quote=True)}" '
                'title="Sales assistant" width="100%" height="640" '
                'style="max-width:100%;border:0;border-radius:8px" loading="lazy" '
                'allow="microphone" sandbox="allow-scripts allow-forms allow-same-origin"></iframe>'
            ),
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

    tenant = _tenant()
    storage = _storage()
    before = storage.read_json(tenant, "overrides.json")
    overrides = dict(before) if isinstance(before, dict) else {}
    ai = overrides.get("ai")
    ai = dict(ai) if isinstance(ai, dict) else {}
    normalized_mode = "v7" if mode.startswith("AIV7") else mode.lower()
    ai["mode"] = normalized_mode
    overrides["ai"] = ai
    snapshot = storage.write_json(tenant, "overrides.json", overrides)
    _invalidate_tenant(tenant)
    _audit("agent.mode.update", f"{tenant}/overrides.json", before=before, after={"snapshot": snapshot, "mode": normalized_mode})
    return jsonify({"ok": True, "mode": normalized_mode})


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
    minutes = _int_arg("minutes", 1440, maximum=525600)
    bucket = _int_arg("bucket", 60, maximum=1440)
    top = _int_arg("top", 10, maximum=100)
    limit = _int_arg("limit", 50, maximum=200)

    # KPIs
    kpis = get_kpis(tenant=tenant, minutes=minutes)
    sales_funnel = get_sales_funnel(tenant=tenant, minutes=minutes)

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
        "sales_funnel": sales_funnel,
        "message_volume": msg_series,
        "sessions_per_bucket": sess_series,
        "sessions_by_channel": _safe_import("get_sessions_by_channel", _fb_dict)(tenant=tenant, minutes=minutes),
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


@bp.get("/statistics")
def api_statistics():
    from service.statistics import get_statistics

    tenant = _tenant()
    days = _int_arg("days", 30, maximum=365)
    channel = request.args.get("channel", "all")
    if channel not in {"all", "web", "whatsapp"}:
        return jsonify(error="invalid_statistics_channel"), 400
    try:
        offers = _storage().read_json(tenant, "offers.json")
    except FileNotFoundError:
        offers = []
    response = jsonify(get_statistics(tenant=tenant, days=days, channel=channel, offers=offers,
                                      catalog=_storage().read_json(tenant, 'catalog.json')))
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.post('/recorded-sales')
def api_record_sale():
    from service.product_metrics import record_sale
    if not is_platform_operator() and 'business_owner' not in user_roles():
        abort(403, description='company_owner_required')
    tenant = _tenant()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error='Enter a sale record.'), 400
    try:
        result = record_sale(tenant, data, _storage().read_json(tenant, 'catalog.json'))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    _audit('sale.record', f"{tenant}/{result['id']}")
    return jsonify(result), 200


@bp.post('/recorded-sales/<sale_id>/void')
def api_void_sale(sale_id):
    from service.product_metrics import void_sale
    if not is_platform_operator() and 'business_owner' not in user_roles():
        abort(403, description='company_owner_required')
    tenant = _tenant()
    if not void_sale(tenant, sale_id):
        abort(404)
    _audit('sale.void', f'{tenant}/{sale_id}')
    return jsonify(ok=True)


@bp.get("/kpis")
def api_kpis():
    minutes = _int_arg("minutes", 1440, maximum=525600)
    return jsonify(get_kpis(tenant=_tenant(), minutes=minutes))


@bp.get("/timeseries")
def api_timeseries():
    minutes = _int_arg("minutes", 1440, maximum=525600)
    bucket = _int_arg("bucket", 60, maximum=1440)
    return jsonify(get_timeseries(tenant=_tenant(), minutes=minutes, bucket_minutes=bucket))


@bp.get("/sessions_timeseries")
def api_sessions_timeseries():
    minutes = _int_arg("minutes", 1440, maximum=525600)
    bucket = _int_arg("bucket", 60, maximum=1440)
    return jsonify(get_sessions_timeseries(tenant=_tenant(), minutes=minutes, bucket_minutes=bucket))


@bp.get("/channels")
def api_channels():
    minutes = _int_arg("minutes", 1440, maximum=525600)
    return jsonify(get_channels_split(tenant=_tenant(), minutes=minutes))


@bp.get("/intents")
def api_intents():
    minutes = _int_arg("minutes", 1440, maximum=525600)
    top = _int_arg("top", 10, maximum=100)
    return jsonify(get_top_intents(tenant=_tenant(), minutes=minutes, top=top))


@bp.get("/fallbacks")
def api_fallbacks():
    minutes = _int_arg("minutes", 1440, maximum=525600)
    top = _int_arg("top", 10, maximum=100)
    return jsonify(get_fallbacks(tenant=_tenant(), minutes=minutes, top=top))


@bp.get("/errors")
def api_errors():
    minutes = _int_arg("minutes", 1440, maximum=525600)
    top = _int_arg("top", 10, maximum=100)
    return jsonify(get_errors(tenant=_tenant(), minutes=minutes, top=top))


@bp.get("/questions")
def api_questions():
    minutes = _int_arg("minutes", 1440, maximum=525600)
    top = _int_arg("top", 10, maximum=100)
    return jsonify(get_common_questions(tenant=_tenant(), minutes=minutes, top=top))


@bp.get("/leads")
def api_leads():
    limit = _int_arg("limit", 50, maximum=200)
    return jsonify(get_leads(tenant=_tenant(), limit=limit))


_LEAD_STATUSES = {"Open", "Contacted", "Qualified", "Won", "Lost"}


@bp.put("/leads/<string:lead_id>")
def api_lead_status_put(lead_id: str):
    data = request.get_json(silent=True) or {}
    status = str(data.get("status") or "").strip() if isinstance(data, dict) else ""
    if status not in _LEAD_STATUSES:
        return jsonify({"error": "invalid_lead_status"}), 400
    if not lead_id or len(lead_id) > 256:
        return jsonify({"error": "invalid_lead_id"}), 400

    tenant = _tenant()
    if not update_lead_status(tenant=tenant, lead_id=lead_id, status=status):
        return jsonify({"error": "lead_not_found"}), 404
    _audit("lead.status", f"{tenant}/lead-status", after={"status": status})
    return jsonify({"ok": True, "status": status})

@bp.get("/conversations")
def api_conversations():
    from service.analytics_db import _conn, _ensure_ready, _since
    tenant = _tenant().upper()
    since = _since(_int_arg("minutes", 1440, maximum=43200))
    try:
        before = int(request.args.get("before", "9223372036854775807"))
    except ValueError:
        abort(400)
    if not 1 <= before <= 9223372036854775807:
        abort(400)
    _ensure_ready()
    with _conn() as db:
        rows = db.execute(
            "SELECT id, ts_utc, channel, event_type, text FROM events "
            "WHERE tenant=? AND id<? AND ts_utc>=? AND event_type IN ('msg_in','msg_out') "
            "ORDER BY id DESC LIMIT 51", (tenant, before, since)
        ).fetchall()
    return jsonify(messages=[dict(row) for row in rows[:50]], has_more=len(rows) > 50,
                   next_before=rows[49]["id"] if len(rows) > 50 else None)


@bp.get("/integrations")
def api_integrations():
    import os
    tenant = _tenant()
    c = get_container()
    mapping = c.settings.WHATSAPP_TENANT_MAP
    assigned = tenant in mapping.values() if mapping else tenant == c.settings.BUSINESS_KEY
    return jsonify(
        tenant=tenant, whatsapp_assigned=assigned,
        meta_configured=assigned and bool(c.settings.WHATSAPP_APP_SECRET and c.settings.WHATSAPP_TOKEN and (mapping or c.settings.WHATSAPP_PHONE_ID)),
        twilio_configured=assigned and bool((os.getenv("TWILIO_AUTH_TOKEN") or c.settings.TWILIO_AUTH_TOKEN) and (mapping or os.getenv("TWILIO_WHATSAPP_NUMBER"))),
        ai_configured=bool(os.getenv("OPENAI_API_KEY")),
    )


@bp.post("/whatsapp-qr")
def api_whatsapp_qr():
    from service.whatsapp_qr import create_whatsapp_qr

    tenant = _tenant()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="Enter a WhatsApp number and optional message."), 400
    try:
        result = create_whatsapp_qr(data.get("phone"), data.get("message", ""))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    _audit("whatsapp.qr.create", f"{tenant}/whatsapp-qr")
    response = jsonify(tenant=tenant, **result)
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.get("/platform")
def api_platform():
    require_platform_operator()
    from service.platform_overview import get_platform_overview
    return jsonify(get_platform_overview(get_container(), minutes=_int_arg("minutes", 1440, maximum=43200),
                                         page=_int_arg("page", 1, maximum=100000)))
