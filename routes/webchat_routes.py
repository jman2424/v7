# routes/webchat_routes.py
from __future__ import annotations

import inspect
import json
import logging
from typing import Any, Dict, Optional

from flask import Blueprint, Response, jsonify, make_response, render_template, request

from connectors.web_widget import (
    allowed_origins_from_branding,
    canonical_origin,
    is_allowed_origin,
    parse_inbound,
    send_reply,
)
from routes import get_container, get_tenant_container

# DB-backed analytics (same DB used by dashboard)
from service.analytics_db import log_message, log_error, upsert_lead, set_lead_session

logger = logging.getLogger("WEB.Chat")
bp = Blueprint("webchat", __name__)

# ---------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------
def _tenant_branding(container, tenant: str) -> Dict[str, Any]:
    try:
        branding = container.storage.read_json(tenant, "branding.json")
        return branding if isinstance(branding, dict) else {}
    except Exception:
        logger.exception("WEB: branding read failed tenant=%s", tenant)
        return {}


def _allowed_origins(container, tenant: str) -> list[str]:
    return allowed_origins_from_branding(_tenant_branding(container, tenant))


def _request_origin_is_allowed(container, tenant: str) -> bool:
    origin = request.headers.get("Origin") or ""
    if not origin:
        return True

    normalized = canonical_origin(origin)
    own_origin = canonical_origin(request.host_url)
    return normalized == own_origin or is_allowed_origin(normalized, _allowed_origins(container, tenant))


def _cors(resp: Response, *, container, tenant: str) -> Response:
    origin = request.headers.get("Origin") or ""
    if not origin:
        return resp

    normalized = canonical_origin(origin)
    own_origin = canonical_origin(request.host_url)
    if normalized == own_origin or is_allowed_origin(normalized, _allowed_origins(container, tenant)):
        resp.headers["Access-Control-Allow-Origin"] = normalized
    resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


def _tenant_from_request(default_tenant: str) -> str:
    return (request.args.get("tenant") or default_tenant).strip() or default_tenant


def _embed_javascript(tenant: str, branding: Dict[str, Any]) -> str:
    widget = branding.get("widget") if isinstance(branding, dict) else {}
    widget = widget if isinstance(widget, dict) else {}
    title = str(widget.get("chat_title") or "Sales assistant")
    primary = str((branding.get("theme") or {}).get("primary_color") or "#0f9d58")
    config = json.dumps({"tenant": tenant, "title": title, "primary": primary})

    return f"""(function () {{
  var config = {config};
  var current = document.currentScript;
  var host = new URL(current.src, window.location.href).origin;
  var mount = current.dataset.target ? document.querySelector(current.dataset.target) : null;
  var root = document.createElement('div');
  var launcher = document.createElement('button');
  var frame = document.createElement('iframe');
  var frameId = 'v7-widget-' + Math.random().toString(36).slice(2);

  root.id = frameId + '-root';
  root.style.cssText = 'position:fixed;right:20px;bottom:20px;z-index:2147483000;font-family:system-ui,-apple-system,Segoe UI,sans-serif;';
  launcher.type = 'button';
  launcher.setAttribute('aria-expanded', 'false');
  launcher.setAttribute('aria-controls', frameId);
  launcher.textContent = config.title;
  launcher.style.cssText = 'border:0;border-radius:8px;background:' + config.primary + ';color:#fff;min-height:44px;padding:0 16px;font:600 14px system-ui,-apple-system,Segoe UI,sans-serif;box-shadow:0 8px 24px rgba(15,23,42,.24);cursor:pointer;';
  frame.id = frameId;
  frame.title = config.title;
  frame.loading = 'lazy';
  frame.referrerPolicy = 'strict-origin-when-cross-origin';
  frame.setAttribute('sandbox', 'allow-scripts allow-forms allow-same-origin');
  frame.src = host + '/chat_ui?tenant=' + encodeURIComponent(config.tenant) + '&embed=1';
  frame.style.cssText = 'display:none;position:absolute;right:0;bottom:56px;width:min(380px,calc(100vw - 32px));height:min(620px,calc(100vh - 104px));border:0;border-radius:8px;box-shadow:0 16px 42px rgba(15,23,42,.28);background:#fff;overflow:hidden;';
  launcher.addEventListener('click', function () {{
    var open = frame.style.display !== 'none';
    frame.style.display = open ? 'none' : 'block';
    launcher.setAttribute('aria-expanded', String(!open));
  }});
  root.appendChild(frame);
  root.appendChild(launcher);
  (mount || document.body).appendChild(root);
}})();
"""


# ---------------------------------------------------------------------
# Handler access
# ---------------------------------------------------------------------
def _get_handler(container):
    """
    We only use a handler that is already correctly wired into your container.
    If container.handler is missing, that is a deployment/wiring problem and should be fixed there,
    not hidden here.
    """
    h = getattr(container, "handler", None) or getattr(container, "message_handler", None)
    if h is None:
        logger.error("WEB: container.handler missing (no MessageHandler wired).")
    return h


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def _lead_id_from_session(session_id: str) -> str:
    sid = (session_id or "web_unknown").strip() or "web_unknown"
    return f"web:{sid}"


def _extract_store_from_result(result: dict) -> Optional[str]:
    if not isinstance(result, dict):
        return None

    store = result.get("store")
    if isinstance(store, str) and store.strip():
        return store.strip()

    entities = result.get("entities") or {}
    if isinstance(entities, dict):
        for k in ("store", "branch", "location", "nearest_store", "nearest_branch"):
            v = entities.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
            if isinstance(v, dict):
                name = v.get("name") or v.get("title")
                if isinstance(name, str) and name.strip():
                    return name.strip()

    meta = result.get("meta") or {}
    if isinstance(meta, dict):
        v = meta.get("store") or meta.get("branch") or meta.get("location")
        if isinstance(v, str) and v.strip():
            return v.strip()

    return None


def _is_fallback_result(result: dict, intent: str) -> bool:
    if not isinstance(result, dict):
        return False

    for k in ("is_fallback", "fallback", "did_fallback"):
        if result.get(k) is True:
            return True

    bad_intents = {
        "unknown",
        "fallback",
        "default",
        "clarify",
        "needs_clarification",
        "no_match",
        "system_fallback",
    }
    if (intent or "").strip().lower() in bad_intents:
        return True

    conf = result.get("confidence")
    try:
        if conf is not None and float(conf) < 0.35:
            return True
    except Exception:
        pass

    return False


def _extract_message_id(ev: dict) -> str:
    """
    Stable id per user message so analytics can dedupe retried POSTs.
    Accepts widget variants.
    """
    if not isinstance(ev, dict):
        return ""
    meta = ev.get("metadata") or {}
    if not isinstance(meta, dict):
        meta = {}

    for k in ("message_id", "client_message_id", "id", "mid"):
        v = ev.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        v = meta.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()

    return ""


# ---------------------------------------------------------------------
# Analytics safe-call (NO silent drop)
# - If analytics_db doesn't support message_id yet, we auto-drop the kwarg.
# - If it fails, we LOG the failure so you can actually fix it.
# ---------------------------------------------------------------------
def _call_compat(fn, kwargs: dict) -> None:
    sig = None
    try:
        sig = inspect.signature(fn)
    except Exception:
        sig = None

    if sig is not None:
        allowed = set(sig.parameters.keys())
        cleaned = {k: v for k, v in kwargs.items() if k in allowed}
    else:
        cleaned = kwargs

    fn(**cleaned)


def _safe_log_message(**kwargs) -> None:
    try:
        _call_compat(log_message, kwargs)
    except Exception as e:
        logger.exception(
            "ANALYTICS log_message FAILED: %s | keys=%s",
            e,
            sorted(list(kwargs.keys())),
        )


def _safe_log_error(**kwargs) -> None:
    try:
        _call_compat(log_error, kwargs)
    except Exception as e:
        logger.exception(
            "ANALYTICS log_error FAILED: %s | keys=%s",
            e,
            sorted(list(kwargs.keys())),
        )


# ---------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------
@bp.get("/chat_ui")
def chat_ui():
    root_container = get_container()
    session_id = request.args.get("session") or ""
    tenant = _tenant_from_request(root_container.settings.BUSINESS_KEY)
    try:
        c = get_tenant_container(tenant)
    except ValueError:
        return jsonify({"error": "unknown_tenant"}), 404

    response = make_response(
        render_template(
            "chatbot.html",
            session_id=session_id,
            tenant=tenant,
            branding=_tenant_branding(c, tenant),
            embedded=request.args.get("embed") == "1",
        )
    )
    allowed = _allowed_origins(c, tenant)
    ancestors = "'self'" if not allowed else "'self' " + " ".join(allowed)
    response.headers["Content-Security-Policy"] = f"frame-ancestors {ancestors}"
    return response


@bp.get("/widget.js")
def widget_embed():
    root_container = get_container()
    tenant = _tenant_from_request(root_container.settings.BUSINESS_KEY)
    try:
        c = get_tenant_container(tenant)
    except ValueError:
        return jsonify({"error": "unknown_tenant"}), 404

    response = Response(_embed_javascript(tenant, _tenant_branding(c, tenant)), mimetype="application/javascript")
    response.headers["Cache-Control"] = "public, max-age=300"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@bp.route("/chat_api", methods=["OPTIONS"])
def chat_api_options():
    root_container = get_container()
    tenant = _tenant_from_request(root_container.settings.BUSINESS_KEY)
    try:
        c = get_tenant_container(tenant)
    except ValueError:
        return jsonify({"error": "unknown_tenant"}), 404
    if not _request_origin_is_allowed(c, tenant):
        return jsonify({"error": "origin_forbidden"}), 403
    return _cors(make_response("", 204), container=c, tenant=tenant)


@bp.route("/chat_api", methods=["POST"])
def chat_api():
    root_container = get_container()

    try:
        data = request.get_json(force=True) or {}
    except Exception:
        logger.exception("WEB: Invalid JSON payload")
        return jsonify({"error": "invalid_json"}), 400

    tenant = str(data.get("tenant") or request.args.get("tenant") or root_container.settings.BUSINESS_KEY).strip()
    try:
        c = get_tenant_container(tenant)
    except ValueError:
        return jsonify({"error": "unknown_tenant"}), 404
    if not _request_origin_is_allowed(c, tenant):
        return jsonify({"error": "origin_forbidden"}), 403

    events = parse_inbound(
        data,
        default_tenant=tenant,
        default_channel="web",
        remote_addr=request.remote_addr,
    )
    if not events:
        return _cors(jsonify({"error": "missing_message"}), container=c, tenant=tenant), 400

    ev = events[0]
    text = (ev.get("text") or "").strip()
    session_id = (ev.get("session_id") or "").strip() or "web_unknown"
    tenant = (ev.get("tenant") or "").strip() or c.settings.BUSINESS_KEY
    channel = (ev.get("channel") or "web").strip().lower() or "web"
    metadata = ev.get("metadata") or {}

    message_id = _extract_message_id(ev)

    logger.info(
        "WEB IN: tenant=%s channel=%s mid=%s session_present=%s text_len=%s",
        tenant,
        channel,
        message_id or "-",
        bool(session_id),
        len(text),
    )

    lead_id = _lead_id_from_session(session_id)

    # Lead table helpers (non-blocking)
    try:
        upsert_lead(tenant=tenant, lead_id=lead_id)
        set_lead_session(tenant=tenant, lead_id=lead_id, session_id=session_id)
    except Exception:
        logger.exception("WEB: lead upsert failed (non-fatal)")

    # ✅ KPI inbound row (dedup if retried)
    _safe_log_message(
        tenant=tenant,
        channel=channel,
        direction="inbound",
        session_id=session_id,
        intent="unknown",
        text=text,
        lead_id=lead_id,
        store=None,
        fallback=False,
        error=False,  # legacy marker only
        error_code="",
        error_type="",
        message_id=message_id,
    )

    handler = _get_handler(c)

    is_error = False
    error_code = ""
    error_type = ""

    if handler is None:
        is_error = True
        error_code = "web_no_handler"
        error_type = "RuntimeError"
        result: Dict[str, Any] = {"reply": "Sorry—bot not configured.", "intent": "system_error", "entities": {}}
    else:
        try:
            # IMPORTANT: your MessageHandler expects metadata=...
            result = handler.handle(
                text,
                tenant=tenant,
                session_id=session_id,
                channel=channel,
                metadata=metadata,
            ) or {}
        except Exception as exc:
            is_error = True
            error_code = "web_handler_crash"
            error_type = type(exc).__name__
            logger.exception("WEB: handler.handle crashed: %s", exc)
            result = {"reply": "Sorry—server error.", "intent": "system_error", "entities": {}}

    reply = (result.get("reply") or "").strip()
    intent = (result.get("intent") or "unknown").strip()
    store = _extract_store_from_result(result)
    is_fallback = _is_fallback_result(result, intent)

    logger.info(
        "WEB OUT: tenant=%s intent=%s fallback=%s error=%s reply_len=%s",
        tenant,
        intent,
        is_fallback,
        is_error,
        len(reply),
    )

    # outbound id derived from inbound id (dedupe retries)
    out_message_id = f"{message_id}:reply" if message_id else ""

    # ✅ KPI outbound row (dedup if retried)
    _safe_log_message(
        tenant=tenant,
        channel=channel,
        direction="outbound",
        session_id=session_id,
        intent=intent,
        text=reply,
        lead_id=lead_id,
        store=store,
        fallback=is_fallback,
        error=False,  # KPI errors stored as separate rows
        error_code="",
        error_type="",
        message_id=out_message_id,
    )

    # ✅ error row (separate event_type='error' in analytics_db)
    if is_error:
        _safe_log_error(
            tenant=tenant,
            channel=channel,
            session_id=session_id,
            lead_id=lead_id,
            error_code=error_code,
            error_type=error_type,
            meta={"where": "webchat_routes.chat_api"},
            message_id=f"{message_id}:error" if message_id else "",
        )

    resp_payload = send_reply(ev, reply, raw=result)
    return _cors(
        jsonify({"reply": resp_payload["reply"], "raw": resp_payload["raw"], "session_id": resp_payload["session_id"]}),
        container=c,
        tenant=tenant,
    ), 200
