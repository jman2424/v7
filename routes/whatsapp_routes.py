from __future__ import annotations

from flask import Blueprint, request, abort, jsonify

from routes import get_container
from service.security import verify_webhook_signature
from service import message_handler
from connectors.whatsapp import parse_inbound, send_reply

bp = Blueprint("whatsapp", __name__, url_prefix="/whatsapp")


@bp.get("/webhook")
def webhook_verify():
    """
    Facebook/WhatsApp verification echo.
    Params: hub.mode, hub.verify_token, hub.challenge
    """
    c = get_container()
    verify = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge", "")

    if verify != c.settings.WHATSAPP_VERIFY_TOKEN:
        abort(403)

    # Meta expects the raw challenge string with text/plain
    return challenge, 200, {"Content-Type": "text/plain; charset=utf-8"}


@bp.post("/webhook")
def webhook_receive():
    """
    Receive inbound WhatsApp messages from Meta.
    - Verifies X-Hub-Signature using app secret
    - Parses events via connectors.whatsapp.parse_inbound
    - For each text event, runs services.message_handler and replies
    """
    c = get_container()

    # --- Signature check ---
    if not verify_webhook_signature(request, c.settings.WHATSAPP_APP_SECRET):
        abort(403)

    payload = request.get_json(force=True) or {}

    # --- Parse inbound events ---
    events = parse_inbound(payload)

    for ev in events:
        text = (ev.get("text") or "").strip()
        if not text:
            continue

        session_id = ev.get("session_id") or ev.get("from") or "wa_unknown"
        tenant = ev.get("tenant") or c.settings.BUSINESS_KEY

        # --- Route through core bot ---
        result = message_handler.handle(
            c,
            text=text,
            session_id=session_id,
            channel="wa",
            tenant=tenant,
            metadata={"wa_id": ev.get("from")},
        )

        reply = result.get("reply", "")
        if reply:
            # Connector handles calling Meta's WA Cloud API
            send_reply(ev, reply, settings=c.settings)

        # --- Analytics logging ---
        c.analytics.log_turn(
            tenant=tenant,
            session_id=session_id,
            intent=result.get("intent"),
            resolved=result.get("resolved", False),
            latency_ms=result.get("_latency_ms", 0),
        )

    return jsonify({"ok": True})
