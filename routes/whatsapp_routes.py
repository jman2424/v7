from __future__ import annotations

from typing import Any, Dict, List

import logging
from flask import Blueprint, request, abort, jsonify

from routes import get_container
from service.security import verify_webhook_signature
from service import message_handler
from connectors.whatsapp import parse_inbound, send_reply

bp = Blueprint("whatsapp", __name__, url_prefix="/whatsapp")
logger = logging.getLogger("WA.Webhook")


@bp.get("/webhook")
def webhook_verify():
    """
    Facebook/WhatsApp webhook verification endpoint.

    Meta sends:
      - hub.mode
      - hub.verify_token
      - hub.challenge

    We must echo back hub.challenge (plain text) when verify_token matches.
    """
    c = get_container()
    verify = request.args.get("hub.verify_token", "")
    challenge = request.args.get("hub.challenge", "")
    mode = request.args.get("hub.mode", "")

    logger.info(
        "WA VERIFY: mode=%s verified_token=%s (expected=%s)",
        mode,
        verify,
        getattr(c.settings, "WHATSAPP_VERIFY_TOKEN", "<missing>"),
    )

    if mode != "subscribe":
        # Meta usually uses mode=subscribe; reject others
        abort(403)

    if verify != c.settings.WHATSAPP_VERIFY_TOKEN:
        logger.warning("WA VERIFY failed: wrong verify_token")
        abort(403)

    # Meta expects the raw challenge string with text/plain
    return challenge, 200, {"Content-Type": "text/plain; charset=utf-8"}


@bp.post("/webhook")
def webhook_receive():
    """
    Receive inbound WhatsApp messages from Meta (Cloud API).

    Flow:
      1. Verify X-Hub-Signature using app secret
      2. Parse events via connectors.whatsapp.parse_inbound(...)
      3. For each text event:
           - route through core bot (service.message_handler.handle)
           - send reply via connectors.whatsapp.send_reply(...)
      4. Log turn analytics

    Always return quickly with 200 so Meta doesn’t retry.
    """
    c = get_container()

    # ---- Signature verification (security) ----
    app_secret = getattr(c.settings, "WHATSAPP_APP_SECRET", "")
    if not app_secret:
        logger.warning("WHATSAPP_APP_SECRET not configured; skipping signature check.")
    else:
        if not verify_webhook_signature(request, app_secret):
            logger.warning("WA WEBHOOK: invalid X-Hub-Signature, aborting 403.")
            abort(403)

    # ---- Parse JSON payload safely ----
    try:
        payload: Dict[str, Any] = request.get_json(force=True, silent=False) or {}
        logger.debug("WA WEBHOOK payload: %s", str(payload)[:2000])
    except Exception as exc:
        logger.exception("WA WEBHOOK: invalid JSON payload: %s", exc)
        return jsonify({"error": "invalid JSON"}), 400

    # ---- Convert raw payload -> internal events ----
    try:
        events: List[Dict[str, Any]] = parse_inbound(payload)
    except Exception as exc:
        logger.exception("WA WEBHOOK: parse_inbound failed: %s", exc)
        # Still return 200 to avoid repeated retries
        return jsonify({"ok": True, "events": 0}), 200

    if not events:
        logger.debug("WA WEBHOOK: no text events in payload.")
        return jsonify({"ok": True, "events": 0}), 200

    # ---- Process each inbound message ----
    for ev in events:
        try:
            text = (ev.get("text") or "").strip()
            if not text:
                continue

            from_id = ev.get("from") or "unknown"
            session_id = ev.get("session_id") or from_id
            tenant = ev.get("tenant") or c.settings.BUSINESS_KEY

            logger.info(
                "WA IN: tenant=%s session=%s from=%s text=%r",
                tenant,
                session_id,
                from_id,
                text,
            )

            # --- Route through your core bot engine ---
            result: Dict[str, Any] = message_handler.handle(
                c,
                text=text,
                session_id=session_id,
                channel="wa",
                tenant=tenant,
                metadata={"wa_id": from_id},
            )

            reply = (result.get("reply") or "").strip()
            if reply:
                try:
                    send_reply(ev, reply, settings=c.settings)
                except Exception as send_exc:
                    logger.exception(
                        "WA WEBHOOK: send_reply failed: %s",
                        send_exc,
                        extra={"wa_id": from_id},
                    )

            # --- Analytics logging (best-effort) ---
            try:
                c.analytics.log_turn(
                    tenant=tenant,
                    session_id=session_id,
                    intent=result.get("intent"),
                    resolved=bool(result.get("resolved", False)),
                    latency_ms=float(result.get("_latency_ms", 0) or 0),
                )
            except Exception as log_exc:
                logger.exception("Analytics log_turn failed: %s", log_exc)

        except Exception as ev_exc:
            logger.exception("Error processing WA event: %s", ev_exc)

    # Meta doesn’t need a detailed body; just 200
    return jsonify({"ok": True, "events": len(events)}), 200
