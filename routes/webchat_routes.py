# routes/webchat_routes.py
from __future__ import annotations

import logging
from flask import Blueprint, request, jsonify, render_template, make_response

from routes import get_container
from connectors.web_widget import parse_inbound, send_reply
from service.analytics_db import log_event, upsert_lead, set_lead_session

logger = logging.getLogger("WEB.Chat")
bp = Blueprint("webchat", __name__)


def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "https://web-tester-jnwd.onrender.com"
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
    channel = (ev.get("channel") or "web").strip()
    metadata = ev.get("metadata") or {}

    lead_id = f"web:{session_id}"

    # Ensure lead exists
    upsert_lead(tenant=tenant, lead_id=lead_id)
    set_lead_session(lead_id=lead_id, session_id=session_id)

    # Log inbound
    log_event(
        tenant=tenant,
        channel=channel,
        session_id=session_id,
        lead_id=lead_id,
        event_type="msg_in",
        text=text,
        meta={"remote_addr": request.remote_addr, "metadata": metadata},
    )

    logger.info("WEB IN: tenant=%s session=%s text=%r", tenant, session_id, text)

    handler = _get_handler(c)
    result: dict = {}

    if handler is None:
        result = {"reply": "Sorry—bot not configured.", "intent": "system_error", "entities": {}}
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
            logger.exception("WEB: handler.handle crashed: %s", exc)
            log_event(
                tenant=tenant,
                channel=channel,
                session_id=session_id,
                lead_id=lead_id,
                event_type="error",
                error_type=type(exc).__name__,
                error_code="web_handler_crash",
                meta={"error": str(exc)},
            )
            result = {"reply": "Sorry—server error.", "intent": "system_error", "entities": {}}

    reply = (result.get("reply") or "").strip()
    intent = (result.get("intent") or "unknown").strip()

    logger.info("WEB OUT: tenant=%s session=%s intent=%s reply=%r", tenant, session_id, intent, reply)

    # Log outbound
    log_event(
        tenant=tenant,
        channel=channel,
        session_id=session_id,
        lead_id=lead_id,
        event_type="msg_out",
        text=reply,
        intent=intent,
        meta={"raw_keys": list(result.keys())},
    )

    # Log fallback explicitly if you use it
    if intent == "system_fallback":
        log_event(
            tenant=tenant,
            channel=channel,
            session_id=session_id,
            lead_id=lead_id,
            event_type="fallback",
            text=text,
            intent=intent,
        )

    resp_payload = send_reply(ev, reply, raw=result)
    return _cors(jsonify({"reply": resp_payload["reply"], "raw": resp_payload["raw"]})), 200
