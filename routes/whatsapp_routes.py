from __future__ import annotations
from flask import Blueprint, request, abort, jsonify
from routes import get_container

bp = Blueprint("whatsapp", __name__, url_prefix="/whatsapp")

@bp.get("/webhook")
def webhook_verify():
    """
    Facebook/WA verification echo. Params: hub.mode, hub.verify_token, hub.challenge
    """
    c = get_container()
    verify = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge", "")
    if verify != c.settings.WHATSAPP_VERIFY_TOKEN:
        abort(403)
    return challenge, 200, {"Content-Type": "text/plain; charset=utf-8"}

@bp.post("/webhook")
def webhook_receive():
    c = get_container()
    # Signature check
    from services.security import verify_webhook_signature
    if not verify_webhook_signature(request, c.settings.WHATSAPP_APP_SECRET):
        abort(403)

    payload = request.get_json(force=True) or {}
    # Parse inbound using connector
    from connectors.whatsapp import parse_inbound, send_reply

    events = parse_inbound(payload)
    for ev in events:
        text = (ev.get("text") or "").strip()
        if not text:
            continue
        session_id = ev.get("session_id") or ev.get("from") or "wa_unknown"
        tenant = ev.get("tenant") or c.settings.BUSINESS_KEY

        from services import message_handler
        result = message_handler.handle(c, text=text, session_id=session_id, channel="wa", tenant=tenant, metadata={"wa_id": ev.get("from")})
        reply = result.get("reply", "")
        if reply:
            send_reply(ev, reply, settings=c.settings)  # connector handles WA API calls

        # analytics
        c.analytics.log_turn(tenant=tenant, session_id=session_id, intent=result.get("intent"),
                             resolved=result.get("resolved", False), latency_ms=result.get("_latency_ms", 0))

    return jsonify({"ok": True})
