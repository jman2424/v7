from __future__ import annotations
from flask import Blueprint, request, jsonify, render_template, current_app
from routes import get_container

bp = Blueprint("webchat", __name__)

@bp.get("/chat_ui")
def chat_ui():
    c = get_container()
    session_id = request.args.get("session") or ""
    tenant = request.args.get("tenant") or c.settings.BUSINESS_KEY
    return render_template("chatbot.html", session_id=session_id, tenant=tenant)

@bp.post("/chat_api")
def chat_api():
    """
    Contract:
    { "message": str, "session_id": str?, "channel": "web"|"wa"|"api"?, "tenant": str?, "metadata": {}? }
    Returns:
    { "reply": str, "raw": {...}? }
    """
    c = get_container()
    data = request.get_json(force=True) or {}
    text = (data.get("message") or "").strip()
    if not text:
        return jsonify({"error": "missing_message"}), 400

    session_id = data.get("session_id") or f"asa_{request.remote_addr}"
    channel = data.get("channel") or "web"
    tenant = data.get("tenant") or c.settings.BUSINESS_KEY
    metadata = data.get("metadata") or {}

    # Delegate to message handler (mode-aware)
    from services import message_handler
    result = message_handler.handle(c, text=text, session_id=session_id, channel=channel, tenant=tenant, metadata=metadata)

    # Optionally log analytics
    c.analytics.log_turn(tenant=tenant, session_id=session_id, intent=result.get("intent"),
                         resolved=result.get("resolved", False), latency_ms=result.get("_latency_ms", 0))

    return jsonify({"reply": result.get("reply", ""), "raw": result})
