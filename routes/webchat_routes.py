from __future__ import annotations

from flask import Blueprint, request, jsonify, render_template
from routes import get_container
from connectors.web_widget_connector import parse_inbound, send_reply  # ✅

bp = Blueprint("webchat", __name__)


@bp.get("/chat_ui")
def chat_ui():
    """
    Renders the chatbot iframe UI.

    Query params:
      - session: optional session id for the web widget
      - tenant: optional tenant key (falls back to BUSINESS_KEY)
    """
    c = get_container()
    session_id = request.args.get("session") or ""
    tenant = request.args.get("tenant") or c.settings.BUSINESS_KEY
    return render_template("chatbot.html", session_id=session_id, tenant=tenant)


@bp.post("/chat_api")
def chat_api():
    """
    Contract (HTTP request JSON):
    {
      "message": str,
      "session_id": str?,        # optional, we fall back to asa_<remote_addr>
      "channel": "web"|"wa"|"api"?,  # optional, defaults to "web"
      "tenant": str?,            # optional, defaults to BUSINESS_KEY
      "metadata": {}?            # optional dict
    }

    Returns (HTTP response JSON):
    {
      "reply": str,
      "raw": {...}               # full result from message_handler
    }
    """
    c = get_container()
    data = request.get_json(force=True) or {}

    # Normalise inbound payload into an event
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
    channel = event["channel"]
    tenant = event["tenant"]
    metadata = event["metadata"]

    # Delegate to message handler (mode-aware)
    from service import message_handler  # ✅

    result = message_handler.handle(
        c,
        text=text,
        session_id=session_id,
        channel=channel,
        tenant=tenant,
        metadata=metadata,
    )

    # Optionally log analytics
    c.analytics.log_turn(
        tenant=tenant,
        session_id=session_id,
        intent=result.get("intent"),
        resolved=result.get("resolved", False),
        latency_ms=result.get("_latency_ms", 0),
    )

    # Build response using connector helper (keeps contract stable)
    resp_payload = send_reply(
        event,
        result.get("reply", ""),
        raw=result,
    )

    # Your original contract only required {reply, raw} – we keep that.
    return jsonify({"reply": resp_payload["reply"], "raw": resp_payload["raw"]}), 200
