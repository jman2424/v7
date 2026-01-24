# routes/webchat_routes.py
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, make_response, render_template, request

from routes import get_container
from connectors.web_widget import parse_inbound, send_reply
from service.analytics_db import log_event, upsert_lead, set_lead_session

logger = logging.getLogger("WEB.Chat")
bp = Blueprint("webchat", __name__)

ALLOWED_ORIGIN = "https://web-tester-jnwd.onrender.com"


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


def _safe_upsert_lead(*, tenant: str, lead_id: str) -> None:
    """
    Some versions of your helpers may have different signatures.
    This makes the route resilient.
    """
    try:
        upsert_lead(tenant=tenant, lead_id=lead_id)
    except TypeError:
        # fallback: maybe upsert_lead(lead_id) or upsert_lead(tenant, lead_id)
        try:
            upsert_lead(lead_id)  # type: ignore[misc]
        except Exception:
            try:
                upsert_lead(tenant, lead_id)  # type: ignore[misc]
            except Exception:
                logger.exception("WEB: upsert_lead failed tenant=%s lead_id=%s", tenant, lead_id)


def _safe_set_lead_session(*, tenant: str, lead_id: str, session_id: str) -> None:
    try:
        set_lead_session(lead_id=lead_id, session_id=session_id)
    except TypeError:
        # fallback: maybe requires tenant
        try:
            set_lead_session(tenant=tenant, lead_id=lead_id, session_id=session_id)  # type: ignore[misc]
        except Exception:
            try:
                set_lead_session(lead_id, session_id)  # type: ignore[misc]
            except Exception:
                logger.exception(
                    "WEB: set_lead_session failed tenant=%s lead_id=%s session_id=%s",
                    tenant, lead_id, session_id
                )


def _safe_log_event(meta: Optional[Dict[str, Any]] = None, **kwargs) -> None:
    """
    Fixes your exact crash:
      TypeError: log_event() got an unexpected keyword argument 'meta'

    Strategy:
      1) Try calling with meta=
      2) If signature doesn't accept it, call again without meta.
      3) Never crash chat_api.
    """
    if meta is None:
        meta = {}

    # First attempt: modern signature supports meta
    try:
        log_event(meta=meta, **kwargs)  # type: ignore[arg-type]
        return
    except TypeError as te:
        # Only retry if the complaint is specifically about 'meta'
        msg = str(te).lower()
        if "unexpected keyword argument" in msg and "meta" in msg:
            pass
        else:
            logger.exception("WEB: log_event TypeError (not meta) kwargs=%s", list(kwargs.keys()))
            return
    except Exception:
        logger.exception("WEB: log_event failed (with meta) kwargs=%s", list(kwargs.keys()))
        return

    # Second attempt: old signature (no meta)
    try:
        log_event(**kwargs)  # type: ignore[arg-type]
    except Exception:
        logger.exception("WEB: log_event failed (without meta) kwargs=%s", list(kwargs.keys()))


@bp.get("/chat_ui")
def chat_ui():
    c = get_container()
    session_id = (request.args.get("session") or "").strip()
    tenant = (request.args.get("tenant") or "").strip() or c.settings.BUSINESS_KEY
    return render_template("chatbot.html", session_id=session_id, tenant=tenant)


@bp.route("/chat_api", methods=["OPTIONS"])
def chat_api_options():
    return _cors(make_response("", 200))


@bp.route("/chat_api", methods=["POST"])
def chat_api():
    c = get_container()

    # -----------------------------
    # Parse inbound JSON
    # -----------------------------
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

    # -----------------------------
    # Ensure lead exists
    # -----------------------------
    _safe_upsert_lead(tenant=tenant, lead_id=lead_id)
    _safe_set_lead_session(tenant=tenant, lead_id=lead_id, session_id=session_id)

    # -----------------------------
    # Log inbound (never crash)
    # -----------------------------
    _safe_log_event(
        tenant=tenant,
        channel=channel,
        session_id=session_id,
        lead_id=lead_id,
        event_type="msg_in",
        text=text,
        meta={
            "remote_addr": request.remote_addr,
            "metadata_keys": list(metadata.keys()) if isinstance(metadata, dict) else [],
        },
    )

    logger.info("WEB IN: tenant=%s session=%s text=%r", tenant, session_id, text)

    # -----------------------------
    # Handle message
    # -----------------------------
    handler = _get_handler(c)

    if handler is None:
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
            logger.exception("WEB: handler.handle crashed: %s", exc)

            _safe_log_event(
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

    reply = (result.get("reply") or "").strip() or "Sorry—I didn’t catch that."
    intent = (result.get("intent") or "unknown").strip()

    logger.info("WEB OUT: tenant=%s session=%s intent=%s reply=%r", tenant, session_id, intent, reply)

    # -----------------------------
    # Log outbound + fallback
    # -----------------------------
    _safe_log_event(
        tenant=tenant,
        channel=channel,
        session_id=session_id,
        lead_id=lead_id,
        event_type="msg_out",
        text=reply,
        intent=intent,
        meta={"raw_keys": list(result.keys())},
    )

    if intent == "system_fallback":
        _safe_log_event(
            tenant=tenant,
            channel=channel,
            session_id=session_id,
            lead_id=lead_id,
            event_type="fallback",
            text=text,
            intent=intent,
        )

    # -----------------------------
    # Return to widget
    # -----------------------------
    resp_payload = send_reply(ev, reply, raw=result)
    return _cors(jsonify({"reply": resp_payload.get("reply", reply), "raw": resp_payload.get("raw", result)})), 200
