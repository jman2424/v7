# routes/webchat_routes.py
from __future__ import annotations

import logging
from flask import Blueprint, request, jsonify, render_template

from routes import get_container
from connectors.web_widget import parse_inbound, send_reply

logger = logging.getLogger("WEB.Chat")

bp = Blueprint("webchat", __name__)


# ------------------------------------------------------------
# Same helper pattern WhatsApp uses
# ------------------------------------------------------------
def _get_handler(container):
    """
    Fetch or create the MessageHandler instance.
    This mirrors whatsapp_routes.py exactly.
    """
    h = getattr(container, "handler", None) or getattr(container, "message_handler", None)

    if h is None:
        logger.warning("WEB: No MessageHandler on container. Creating one.")
        try:
            from service.message_handler import MessageHandler
            h = MessageHandler(container)
            container.handler = h
        except Exception as exc:
            logger.exception("WEB: Failed to create MessageHandler: %s", exc)
            return None

    return h


# ------------------------------------------------------------
# UI
# ------------------------------------------------------------
@bp.get("/chat_ui")
def chat_ui():
    c = get_container()
    session_id = request.args.get("session") or ""
    tenant = request.args.get("tenant") or c.settings.BUSINESS_KEY
    return render_template("chatbot.html", session_id=session_id, tenant=tenant)


# ------------------------------------------------------------
# API
# ------------------------------------------------------------
@bp.post("/chat_api")
def chat_api():
    c = get_container()

    try:
        data = request.get_json(force=True) or {}
    except Exception:
        logger.exception("WEB: Invalid JSON payload")
        return jsonify({"error": "invalid_json"}), 400

    # ---- normalise inbound payload ----
    events = parse_inbound(
        data,
        default_tenant=c.settings.BUSINESS_KEY,
        default_channel="web",
        remote_addr=request.remote_addr,
    )

    if not events:
        return jsonify({"error": "missing_message"}), 400

    event = events[0]

    text = event["text"]
    session_id = event["session_id"]
    tenant = event["tenant"]
    channel = event["channel"]
    metadata = event["metadata"]

    logger.info(
        "WEB IN: tenant=%s session=%s text=%r",
        tenant,
        session_id,
        text,
    )

    # ---- get SAME handler WhatsApp uses ----
    handler = _get_handler(c)

    if handler is None:
        result = {
            "reply": "Sorry—my chatbot brain isn’t configured yet.",
            "intent": "system_error",
            "entities": {},
        }
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
            result = {
                "reply": "Sorry—something went wrong while processing your message.",
                "intent": "system_error",
                "entities": {},
            }

    reply = (result.get("reply") or "").strip()

    logger.info(
        "WEB OUT: tenant=%s session=%s intent=%s reply=%r",
        tenant,
        session_id,
        result.get("intent"),
        reply,
    )

    # ---- build widget response ----
    resp_payload = send_reply(
        event,
        reply,
        raw=result,
    )

    return jsonify(
        {
            "reply": resp_payload["reply"],
            "raw": resp_payload["raw"],
        }
    ), 200
