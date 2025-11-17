# routes/whatsapp_routes.py
from __future__ import annotations

import logging
from flask import Blueprint, request, abort, jsonify, Response

from twilio.twiml.messaging_response import MessagingResponse

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
    Facebook/WhatsApp verification echo (for Cloud API).

    Expects query params:
      - hub.mode
      - hub.verify_token
      - hub.challenge
    Twilio will never hit this with GET.
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

    Supports:
    - Twilio WhatsApp (form-encoded, User-Agent: TwilioProxy/1.1)
    - Meta Cloud API (JSON with X-Hub-Signature-256)

    Flow:
    - For Meta + signature header -> verify X-Hub-Signature-256
    - For Twilio (no signature header) -> skip Meta verification
    - Normalise events via connectors.whatsapp.parse_inbound
    - Route through core message_handler
    - Reply:
        * Twilio -> TwiML (sync reply)
        * Cloud API -> send_reply() (REST call)
    """
    c = get_container()

    # --- Detect if this looks like Twilio (no JSON, form data, Twilio UA) ---
    is_twilio = (
        not request.is_json
        and "TwilioProxy" in (request.headers.get("User-Agent") or "")
    )

    # ----- Signature verification (Meta Cloud API only) -----
    app_secret = getattr(c.settings, "WHATSAPP_APP_SECRET", "") or ""
    sig_header = request.headers.get("X-Hub-Signature-256")

    if not is_twilio and app_secret and sig_header:
        if not verify_webhook_signature(request, app_secret):
            logger.warning("WA WEBHOOK: invalid X-Hub-Signature, aborting 403.")
            abort(403)
    elif not is_twilio:
        logger.debug(
            "WA WEBHOOK: no X-Hub-Signature-256 present; "
            "skipping Meta signature check."
        )

    # ----- Parse payload -----
    try:
        if is_twilio:
            # Wrap raw form into a dict the connector understands
            payload = {"raw_form": request.form.to_dict()}
        else:
            payload = request.get_json(force=True, silent=True) or {}
        logger.debug("WA WEBHOOK payload: %s", str(payload)[:2000])
    except Exception as exc:
        logger.exception("WA WEBHOOK: invalid payload: %s", exc)
        if is_twilio:
            # Twilio still expects 200; reply with generic error
            resp = MessagingResponse()
            resp.message("Sorry—there was a problem reading your message.")
            return Response(str(resp), status=200, mimetype="application/xml")
        return jsonify({"error": "invalid payload"}), 400

    # ----- Convert into internal events -----
    try:
        events = parse_inbound(payload)
    except Exception as exc:
        logger.exception("WA WEBHOOK: parse_inbound failed: %s", exc)
        # Don’t 500 on bad messages; just acknowledge
        if is_twilio:
            resp = MessagingResponse()
            resp.message("Sorry—there was a problem handling your message.")
            return Response(str(resp), status=200, mimetype="application/xml")
        return jsonify({"ok": True, "events": 0}), 200

    if not events:
        logger.debug("WA WEBHOOK: no text events in payload.")
        if is_twilio:
            # Silent 200 so Twilio stops retrying
            return Response("", status=200, mimetype="text/plain")
        return jsonify({"ok": True, "events": 0}), 200

    handled = 0
    twilio_reply: str | None = None

    for ev in events:
        try:
            text = (ev.get("text") or "").strip()
            if not text:
                continue

            from_id = ev.get("from") or "unknown"
            session_id = ev.get("session_id") or from_id
            tenant = ev.get("tenant") or c.settings.BUSINESS_KEY
            source = ev.get("source") or ("twilio" if is_twilio else "cloud")

            logger.info(
                "WA IN: source=%s tenant=%s session=%s from=%s text=%r",
                source,
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
                if source == "twilio":
                    # For Twilio, we respond via TwiML once per webhook call.
                    # If multiple events somehow exist, only the first reply is used.
                    if twilio_reply is None:
                        twilio_reply = reply
                else:
                    # Cloud API path: send via REST
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

    # ---- Final response depending on channel ----
    if is_twilio:
        resp = MessagingResponse()
        if twilio_reply:
            resp.message(twilio_reply)
        # If no reply, still 200 so Twilio stops retrying
        return Response(str(resp), status=200, mimetype="application/xml")

    return jsonify({"ok": True, "events": handled}), 200
