# routes/webchat_routes.py
from __future__ import annotations

import inspect
import logging
import os
from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, make_response, render_template, request

from routes import get_container
from connectors.web_widget import parse_inbound, send_reply

# DB-backed analytics (same DB used by dashboard)
from service.analytics_db import log_message, log_error, upsert_lead, set_lead_session

logger = logging.getLogger("WEB.Chat")
bp = Blueprint("webchat", __name__)

# If you want multiple origins later, upgrade to a whitelist.
ALLOWED_ORIGIN = os.environ.get("WEBCHAT_ALLOWED_ORIGIN", "https://web-tester-jnwd.onrender.com")


# ---------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------
def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGIN
    resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Credentials"] = "true"
    return resp


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
    c = get_container()
    session_id = request.args.get("session") or ""
    tenant = request.args.get("tenant") or c.settings.BUSINESS_KEY
    return render_template("chatbot.html", session_id=session_id, tenant=tenant)


@bp.route("/chat_api", methods=["OPTIONS"])
def chat_api_options():
    return _cors(make_response("", 200))


@bp.route("/chat_api", methods=["POST"])
def chat_api():
    c = get_container()

    try:
        data = request.get_json(force=True) or {}
    except Exception:
        logger.exception("WEB: Invalid JSON payload")
        return _cors(jsonify({"error": "invalid_json"})), 400

    events = parse_inbound(
        data,
        default_tenant=c.settings.BUSINESS_KEY,
        default_channel="web",
        remote_addr=request.remote_addr,
    )
    if not events:
        return _cors(jsonify({"error": "missing_message"})), 400

    ev = events[0]
    text = (ev.get("text") or "").strip()
    session_id = (ev.get("session_id") or "").strip() or "web_unknown"
    tenant = (ev.get("tenant") or "").strip() or c.settings.BUSINESS_KEY
    channel = (ev.get("channel") or "web").strip().lower() or "web"
    metadata = ev.get("metadata") or {}

    message_id = _extract_message_id(ev)

    logger.info(
        "WEB IN: tenant=%s session=%s channel=%s mid=%s text=%r",
        tenant,
        session_id,
        channel,
        message_id or "-",
        text,
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
        "WEB OUT: tenant=%s session=%s intent=%s fallback=%s error=%s reply_len=%s",
        tenant,
        session_id,
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
    return _cors(jsonify({"reply": resp_payload["reply"], "raw": resp_payload["raw"]})), 200
