from __future__ import annotations

from flask import Blueprint, request, jsonify, render_template
from routes import get_container
from connectors.web_widget_connector import parse_inbound, send_reply  # ✅ our widget normaliser

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
    Incoming JSON from the widget page or simple fetch:

    {
      "message": "hi",
      "session_id": "asa_...",    # optional
      "channel": "web",           # optional
      "tenant": "TARIQ",          # optional
      "metadata": {...}           # optional
    }

    Response:

    {
      "reply": "string",
      "raw": {...}                # full router result
    }
    """
    c = get_container()
    data = request.get_json(force=True) or {}

    # ---- normalise inbound into a single "event" dict ----
    events = parse_inbound(
        data,
        default_tenant=c.settings.BUSINESS_KEY,
        default_channel="web",
        remote_addr=request.remote_addr,
    )

    if not events:
        return jsonify({"error": "missing_message"}), 400

    event = events[0]

    # ---- delegate to the main router (same engine WA uses) ----
    from service import router  # lazy import to avoid cycles

    # router.route(...) is how this repo is designed (no .handle attribute)
    result = router.route(c, event=event)

    # ---- build reply payload in the web-widget shape ----
    resp_payload = send_reply(
        event,
        result.get("reply", "") or "",
        raw=result,
    )

    # The widget only cares about { reply, raw }
    return jsonify(
        {
            "reply": resp_payload["reply"],
            "raw": resp_payload["raw"],
        }
    ), 200
