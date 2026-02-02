# routes/webchat_routes.py
from __future__ import annotations

import logging
import os
from typing import Any, Dict

from flask import Blueprint, jsonify, make_response, render_template, request

from routes import get_container
from connectors.web_widget import parse_inbound, send_reply

# ✅ use DB-backed analytics directly (same as whatsapp_routes)
from service.analytics_db import log_message, upsert_lead, set_lead_session

logger = logging.getLogger("WEB.Chat")
bp = Blueprint("webchat", __name__)

# If you want multiple origins later, upgrade this to a whitelist.
ALLOWED_ORIGIN = os.environ.get("WEBCHAT_ALLOWED_ORIGIN", "https://web-tester-jnwd.onrender.com")


def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGIN
    resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Credentials"] = "true"
    return resp


def _get_handler(container):
    h = getattr(container, "handler", None) or getattr(container, "message_handler", None)
    if h is not None:
        return h

    logger.warning("WEB: No MessageHandler on container. Creating one.")
    try:
        from service.message_handler import MessageHandler

        h = MessageHandler(container)
        container.handler = h
        return h
    except Exception:
        logger.exception("WEB: Failed to create MessageHandler")
        return None


def _lead_id_from_session(session_id: str) -> str:
    sid = (session_id or "web_unknown").strip() or "web_unknown"
    return f"web:{sid}"


def _extract_store_from_result(result: dict) -> str | None:
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

    if str(result.get("route") or "").lower() in ("fallback", "default"):
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


def _safe_log(*, tenant: str, channel: str, direction: str, session_id: str, text: str, intent: str,
              lead_id: str | None = None, store: str | None = None,
              fallback: bool = False, error: bool = False,
              error_code: str = "", error_type: str = "") -> None:
    """
    Analytics must never break chat.
    """
    try:
        log_message(
            tenant=tenant,
            channel=channel,
            direction=direction,
            session_id=session_id,
            intent=intent or "unknown",
            text=text or "",
            lead_id=lead_id,
            store=store,
            fallback=bool(fallback),
            error=bool(error),
            error_code=error_code or "",
            error_type=error_type or "",
        )
    except Exception:
        return


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

    logger.info("WEB IN: tenant=%s session=%s channel=%s text=%r", tenant, session_id, channel, text)

    lead_id = _lead_id_from_session(session_id)

    # Ensure lead exists (so "LEADS" table can populate later)
    try:
        upsert_lead(tenant=tenant, lead_id=lead_id)
        set_lead_session(tenant=tenant, lead_id=lead_id, session_id=session_id)
    except Exception:
        # still continue chat
        pass

    # ✅ inbound log (this powers "COMMON QUESTIONS")
    _safe_log(
        tenant=tenant,
        channel="web",
        direction="inbound",
        session_id=session_id,
        text=text,
        intent="unknown",
        lead_id=lead_id,
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
        len(reply or ""),
    )

    # ✅ outbound log (fallback/error panels + store share for future)
    _safe_log(
        tenant=tenant,
        channel="web",
        direction="outbound",
        session_id=session_id,
        text=reply,
        intent=intent,
        lead_id=lead_id,
        store=store,
        fallback=is_fallback,
        error=is_error,
        error_code=error_code,
        error_type=error_type,
    )

    resp_payload = send_reply(ev, reply, raw=result)
    return _cors(jsonify({"reply": resp_payload["reply"], "raw": resp_payload["raw"]})), 200
