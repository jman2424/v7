from __future__ import annotations

from flask import Blueprint, request, jsonify, render_template, current_app
from routes import get_container
from connectors.web_widget import parse_inbound, send_reply

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


@bp.route("/chat_api", methods=["POST", "OPTIONS"])
def chat_api():
    """
    Contract (HTTP request JSON):
    {
      "message": str,
      "session_id": str?,            # optional, we fall back to asa_<remote_addr>
      "channel": "web"|"wa"|"api"?,  # optional, defaults to "web"
      "tenant": str?,                # optional, defaults to BUSINESS_KEY
      "metadata": {}?                # optional dict
    }

    Returns (HTTP response JSON):
    {
      "reply": str,
      "raw": {...}                   # full result from message_handler
    }
    """

    # ---------- CORS preflight (OPTIONS) ----------
    if request.method == "OPTIONS":
        resp = current_app.make_response("")
        resp.status_code = 204  # No Content
        origin = request.headers.get("Origin", "*")
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp

    # ---------- Actual POST ----------
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
        resp = jsonify({"error": "missing_message"})
        _add_cors_headers(resp)
        return resp, 400

    event = events[0]
    text = event["text"]
    session_id = event["session_id"]
    channel = event["channel"]
    tenant = event["tenant"]
    metadata = event["metadata"]

    # Delegate to message handler (mode-aware)
    from service import message_handler

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

    resp = jsonify(
        {
            "reply": resp_payload["reply"],
            "raw": resp_payload["raw"],
        }
    )
    _add_cors_headers(resp)
    return resp, 200


def _add_cors_headers(resp):
    """
    Helper to add CORS headers on POST responses.
    """
    origin = request.headers.get("Origin", "*")
    resp.headers["Access-Control-Allow-Origin"] = origin
    resp.headers["Access-Control-Allow-Credentials"] = "true"
    return resp
