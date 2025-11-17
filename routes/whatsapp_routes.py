# routes/whatsapp_routes.py
from __future__ import annotations

import logging
from flask import Blueprint, request, abort, jsonify

from routes import get_container
from service.security import verify_webhook_signature
from service import message_handler
from connectors.whatsapp import parse_inbound, send_reply

logger = logging.getLogger("WA.Webhook")

# This is what app.__init__ imports as `bp as whatsapp_bp`
bp = Blueprint("whatsapp", __name__, url_prefix="/whatsapp")


@bp.get("/webhook")
def webhook_verify():
    """
    Facebook/WhatsApp verification echo.
    Used by Meta when you first set up the webhook.

    Expects query params:
      - hub.mode
      - hub.verify_token
      - hub.challenge
    """
    c = get_container()
    verify = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge", "")

    if verify != c.settings.WHATSAPP_VERIFY_TOKEN:
        abort(403)

    # Meta expects the challenge string as plain text
    return challenge, 200, {"Content-Type": "text/plain; charset=utf-8"}


@bp.post("/webhook")
def webhook_receive():
    """
    Receive inbound WhatsApp messages.

    Designed for WhatsApp Cloud API payloads, but:
    - If X-Hub-Signature-256 is present AND app secret is set:
        → verify signature (Meta)
    - If header is missing:
        → skip verification (e.g. Twilio hitting this URL by mistake)
    """
    c = get_container()

    # ----- Signature verification (Meta only) -----
    app_secret = getattr(c.settings, "WHATSAPP_APP_SECRET", "") or ""
    sig_header = request.headers.get("X-Hub-Signature-256")

    if app_secret and sig_header:
        if not verify_webhook_signature(request, app_secret):
            logger.warning("WA WEBHOOK: invalid X-Hub-Signature, aborting 403.")
            abort(403)
    else:
        # No Meta signature header → probably not Cloud API
        logger.debug(
            "WA WEBHOOK: no X-Hub-Signature-256 present; "
            "skipping Meta signature check."
        )

    # ----- Parse payload -----
    try:
        if request.is_json:
            payload = request.get_json(force=True, silent=True) or {}
        else:
            # e.g. Twilio form-encoded payload – keep it around for debugging
            payload = {"raw_form": request.form.to_dict()}
        logger.debug("WA WEBHOOK payload: %s", str(payload)[:2000])
    except Exception as exc:
        logger.exception("WA WEBHOOK: invalid payload: %s", exc)
        return jsonify({"error": "invalid payload"}), 400

    # ----- Convert into internal events -----
    try:
        events = parse_inbound(payload)
    except Exception as exc:
        logger.exception("WA WEBHOOK: parse_inbound failed: %s", exc)
        # Don’t 500 on bad messages; just acknowledge
        return jsonify({"ok": True, "events": 0}), 200

    if not events:
        logger.debug("WA WEBHOOK: no text events in payload.")
        return jsonify({"ok": True, "events": 0}), 200

    handled = 0

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

            # Core bot handler (AI Mode v6 etc. lives behind this)
            result = message_handler.handle(
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
                        "WA WEBHOOK: send_reply failed",
                        extra={"wa_id": from_id, "error": str(send_exc)},
                    )

            # Analytics logging
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

            handled += 1

        except Exception as ev_exc:
            logger.exception("Error processing WA event: %s", ev_exc)

    return jsonify({"ok": True, "events": handled}), 200
