# routes/whatsapp_routes.py
from __future__ import annotations

import logging
from typing import Any, Dict

from flask import Blueprint, request, abort, jsonify, Response
from twilio.twiml.messaging_response import MessagingResponse

from routes import get_container
from service.security import verify_webhook_signature
from connectors.whatsapp import parse_inbound, send_reply

logger = logging.getLogger("WA.Webhook")

bp = Blueprint("whatsapp", __name__, url_prefix="/whatsapp")


# ---------- helper to get the orchestrator ----------

def _get_handler(container):
    """
    Fetch the MessageHandler instance from the DI container.
    Supports both `container.handler` and `container.message_handler`.
    """
    h = getattr(container, "handler", None) or getattr(container, "message_handler", None)
    if h is None:
        logger.error("WA: No MessageHandler instance found on container.")
    return h


# ---------- Meta verification (for WhatsApp Cloud API only) ----------

@bp.get("/webhook")
def webhook_verify():
    """
    Facebook/WhatsApp Cloud API verification echo.

    Expects:
      - hub.mode
      - hub.verify_token
      - hub.challenge

    Twilio sandbox does NOT use this.
    """
    c = get_container()
    verify = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge", "")

    if verify != getattr(c.settings, "WHATSAPP_VERIFY_TOKEN", ""):
        abort(403)

    # Meta expects raw challenge text/plain
    return challenge, 200, {"Content-Type": "text/plain; charset=utf-8"}


# ---------- Main webhook (Twilio + Cloud API) ----------

@bp.post("/webhook")
def webhook_receive():
    """
    Receive inbound WhatsApp messages.

    Supports:
      - Twilio WhatsApp (form-encoded; User-Agent contains TwilioProxy)
      - Meta WhatsApp Cloud API (JSON + X-Hub-Signature-256)
    """
    c = get_container()

    ua = request.headers.get("User-Agent") or ""
    content_type = request.headers.get("Content-Type") or ""
    is_twilio = "TwilioProxy" in ua or content_type.startswith(
        "application/x-www-form-urlencoded"
    )

    # ----- Meta signature verification (Cloud API only) -----
    app_secret = getattr(c.settings, "WHATSAPP_APP_SECRET", "") or ""
    sig_header = request.headers.get("X-Hub-Signature-256")

    if not is_twilio and app_secret and sig_header:
        if not verify_webhook_signature(request, app_secret):
            logger.warning("WA WEBHOOK: invalid X-Hub-Signature, aborting 403.")
            abort(403)
    elif not is_twilio:
        logger.debug(
            "WA WEBHOOK: no X-Hub-Signature-256 present; skipping Meta signature check."
        )

    handler = _get_handler(c)

    # ------------------------------------------------------------------
    #                       TWILIO PATH (FORM)
    # ------------------------------------------------------------------
    if is_twilio:
        form = request.form.to_dict()
        body = (form.get("Body") or "").strip()
        from_raw = (form.get("From") or "").strip()  # e.g. "whatsapp:+4473..."
        from_id = from_raw.replace("whatsapp:", "").replace("+", "")

        if not body:
            resp = MessagingResponse()
            resp.message("Sorry—I didn’t receive any text.")
            return Response(str(resp), status=200, mimetype="application/xml")

        tenant = getattr(c.settings, "BUSINESS_KEY", "DEFAULT")
        session_id = from_id or "wa_unknown"

        logger.info(
            "WA IN: source=twilio tenant=%s session=%s from=%s text=%r",
            tenant,
            session_id,
            from_id,
            body,
        )

        if handler is None:
            reply = "Sorry—my chatbot brain isn’t configured yet. Please contact support."
        else:
            # Use your orchestrator (MessageHandler.handle)
            result = handler.handle(
                body,
                tenant=tenant,
                session_id=session_id,
                channel="whatsapp",
                metadata={"wa_id": from_id},
            )
            reply = (result.get("reply") or "").strip() or "Sorry—I didn’t catch that."

        resp = MessagingResponse()
        resp.message(reply)
        return Response(str(resp), status=200, mimetype="application/xml")

    # ------------------------------------------------------------------
    #                     CLOUD API PATH (JSON)
    # ------------------------------------------------------------------
    try:
        payload = request.get_json(force=True, silent=True) or {}
        logger.debug("WA WEBHOOK JSON payload: %s", str(payload)[:2000])
    except Exception as exc:
        logger.exception("WA WEBHOOK: invalid JSON payload: %s", exc)
        return jsonify({"error": "invalid payload"}), 400

    try:
        events = parse_inbound(payload)
    except Exception as exc:
        logger.exception("WA WEBHOOK: parse_inbound failed: %s", exc)
        return jsonify({"ok": True, "events": 0}), 200

    if not events:
        logger.debug("WA WEBHOOK: no text events in payload.")
        return jsonify({"ok": True, "events": 0}), 200

    handled = 0
    tenant_default = getattr(c.settings, "BUSINESS_KEY", "DEFAULT")

    for ev in events:
        try:
            text = (ev.get("text") or "").strip()
            if not text:
                continue

            from_id = ev.get("from") or "unknown"
            session_id = ev.get("session_id") or from_id
            tenant = ev.get("tenant") or tenant_default

            logger.info(
                "WA IN: source=cloud tenant=%s session=%s from=%s text=%r",
                tenant,
                session_id,
                from_id,
                text,
            )

            if handler is None:
                result: Dict[str, Any] = {
                    "reply": "Sorry—my chatbot brain isn’t configured yet. Please contact support."
                }
            else:
                result = handler.handle(
                    text,
                    tenant=tenant,
                    session_id=session_id,
                    channel="whatsapp",
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

            handled += 1

        except Exception as ev_exc:
            logger.exception("Error processing WA event: %s", ev_exc)

    return jsonify({"ok": True, "events": handled}), 200


# ---------- Twilio status callback (optional) ----------

@bp.route("/status", methods=["POST", "GET"])
def whatsapp_status():
    """
    Twilio message status callback endpoint.

    If you set the Twilio status callback URL to:
      https://v7-52g3.onrender.com/whatsapp/status

    this will stop the 404s and just log the status events.
    """
    form = request.form.to_dict()
    logger.info("WA STATUS: %s", form)
    return Response(status=204)
