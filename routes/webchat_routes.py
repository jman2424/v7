# routes/webchat_routes.py
from __future__ import annotations

import inspect
import logging
import os
import secrets
from typing import Any, Dict, Optional

from flask import Blueprint, abort, current_app, g, jsonify, make_response, render_template, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from connectors.web_widget import parse_inbound, send_reply
from routes import get_container

# DB-backed analytics (same DB used by dashboard)
from service.analytics_db import log_error, log_message, set_lead_session, upsert_lead

logger = logging.getLogger("WEB.Chat")
bp = Blueprint("webchat", __name__)

def _tenant_container(tenant):
    try:
        return get_container().for_tenant(tenant)
    except ValueError:
        abort(400, description="invalid_tenant")
    except FileNotFoundError:
        abort(404, description="tenant_not_found")


def _branding(c):
    try:
        data = c.storage.read_json(c.settings.BUSINESS_KEY, "branding.json")
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError):
        return {}


def _check_origin(c):
    origin = request.headers.get("Origin")
    allowed = _branding(c).get("allowed_origins", [])
    if not isinstance(allowed, list):
        allowed = []
    # Same-origin hosted chat always works. Cross-origin calls need tenant consent.
    if origin and origin != request.host_url.rstrip("/") and origin not in allowed:
        abort(403, description="origin_forbidden")


def _cors(resp):
    origin = request.headers.get("Origin")
    if origin:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _signer():
    return URLSafeTimedSerializer(current_app.secret_key, salt="web-conversation-v1")


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
    tenant = request.args.get("tenant") or get_container().settings.BUSINESS_KEY
    c = _tenant_container(tenant)
    from urllib.parse import urlsplit
    origins = _branding(c).get("allowed_origins", [])
    g.chat_origins = []
    if isinstance(origins, list):
        for origin in origins:
            if isinstance(origin, str) and not any(ch in origin for ch in (";", "'", " ", "\r", "\n")):
                parsed = urlsplit(origin)
                if parsed.scheme in {"http", "https"} and parsed.netloc and not parsed.path and not parsed.username:
                    g.chat_origins.append(origin)
    return render_template("chatbot.html", tenant=tenant, branding=_branding(c))


@bp.route("/chat_api", methods=["OPTIONS"])
def chat_api_options():
    tenant = request.args.get("tenant") or get_container().settings.BUSINESS_KEY
    _check_origin(_tenant_container(tenant))
    return _cors(make_response("", 204))


@bp.route("/chat_api", methods=["POST"])
def chat_api():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="json_object_required"), 400
    tenant = data.get("tenant") or get_container().settings.BUSINESS_KEY
    if not isinstance(tenant, str):
        return jsonify(error="invalid_tenant"), 400
    c = _tenant_container(tenant)
    _check_origin(c)
    text = data.get("message", data.get("text", ""))
    if not isinstance(text, str) or not text.strip() or len(text) > 4000:
        return _cors(jsonify(error="message_must_be_1_to_4000_characters")), 400
    text = text.strip()
    token = data.get("conversation_token")
    if token:
        if not isinstance(token, str) or len(token) > 2048:
            return _cors(jsonify(error="invalid_conversation")), 403
        try:
            identity = _signer().loads(token, max_age=86400)
        except (BadSignature, SignatureExpired):
            return _cors(jsonify(error="conversation_expired")), 403
        if not isinstance(identity, dict) or identity.get("tenant") != tenant:
            return _cors(jsonify(error="invalid_conversation")), 403
        session_id = identity["id"]
    else:
        session_id = "web:" + secrets.token_urlsafe(24)
        token = _signer().dumps({"tenant": tenant, "id": session_id})
    channel = "web"
    metadata = {"source": "widget"}
    # Ignore caller identities/metadata: they must not select another conversation.
    message_id = data.get("message_id") or secrets.token_hex(16)
    if not isinstance(message_id, str) or len(message_id) > 128:
        return _cors(jsonify(error="invalid_message_id")), 400
    message_id = session_id + ":" + message_id

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

    if not isinstance(result, dict):
        result = {"reply": "Sorry, please try again.", "intent": "system_error"}
        is_error, error_code, error_type = True, "invalid_agent_response", "InvalidResponse"
    reply = str(result.get("reply") or "Please rephrase your question.").strip()
    intent = (result.get("intent") or "unknown").strip()
    if intent == "system_error":
        is_error, error_code, error_type = True, "agent_failure", "AgentError"
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

    return _cors(jsonify(reply=reply, conversation_token=token, session_id=session_id,
                         error=error_code or None)), 503 if is_error else 200
