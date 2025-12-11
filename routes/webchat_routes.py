from __future__ import annotations

from flask import Blueprint, request, jsonify, render_template, current_app
from routes import get_container
from connectors.web_widget import parse_inbound, send_reply

bp = Blueprint("webchat", __name__)

ALLOWED_WEB_ORIGIN = "https://web-tester-jnwd.onrender.com"


def _add_cors_headers(resp):
    """
    Add CORS headers so the web-tester frontend can call /chat_api.
    """
    resp.headers["Access-Control-Allow-Origin"] = ALLOWED_WEB_ORIGIN
    resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    return resp


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
      "session_id": str?,             # optional, we fall back to asa_<remote_addr>
      "channel": "web"|"wa"|"api"?,   # optional, defaults to "web"
      "tenant": str?,                 # optional, defaults to BUSINESS_KEY
      "metadata": {}?                 # optional dict
    }

    Returns (HTTP response JSON):
    {
      "reply": str,
      "raw": {...}
    }
    """

    # --- CORS preflight ---
    if request.method == "OPTIONS":
        resp = jsonify({})
        return _add_cors_headers(resp)

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
        resp.status_code = 400
        return _add_cors_headers(resp)

    event = events[0]
    text = event["text"]
    session_id = event["session_id"]
    channel = event["channel"]
    tenant = event["tenant"]
    metadata = event["metadata"]

    # ------------------------------------------------------------------
    # MAIN BOT CALL – try to use the real router if available.
    # If anything goes wrong, fall back to echo so the UI never 500s.
    # ------------------------------------------------------------------
    router_obj = getattr(c, "router", None)
    result = None

    try:
        if router_obj is not None:
            # Try common patterns for Router.handle(...)
            if hasattr(router_obj, "handle"):
                try:
                    # Pattern 1: handle(text=..., session_id=..., ...)
                    result = router_obj.handle(
                        text=text,
                        session_id=session_id,
                        channel=channel,
                        tenant=tenant,
                        metadata=metadata,
                    )
                except TypeError:
                    # Pattern 2: handle(container, text=..., ...)
                    result = router_obj.handle(
                        c,
                        text=text,
                        session_id=session_id,
                        channel=channel,
                        tenant=tenant,
                        metadata=metadata,
                    )

            elif hasattr(router_obj, "handle_turn"):
                # Some implementations use handle_turn(...)
                result = router_obj.handle_turn(
                    text=text,
                    session_id=session_id,
                    channel=channel,
                    tenant=tenant,
                    metadata=metadata,
                )

    except Exception:
        # Log the error but don't break the widget.
        current_app.logger.exception(
            "webchat /chat_api: router error, falling back to echo"
        )
        result = None

    # If router didn't return a usable result, use a simple echo reply.
    if not isinstance(result, dict) or "reply" not in result:
        reply_text = f"I received: {text}"
        result = {
            "reply": reply_text,
            "intent": "stub_web_echo",
            "resolved": True,
            "_latency_ms": 0,
            "channel": channel,
            "tenant": tenant,
            "metadata": metadata,
        }
    else:
        reply_text = result.get("reply", "")

    # Build response using connector helper
    resp_payload = send_reply(
        event,
        reply_text,
        raw=result,
    )

    resp = jsonify(
        {
            "reply": resp_payload["reply"],
            "raw": resp_payload["raw"],
        }
    )
    return _add_cors_headers(resp)
