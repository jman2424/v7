# routes/whatsapp_routes.py
from __future__ import annotations

import logging
from typing import Any, Dict

from flask import Blueprint, request, abort, jsonify, Response
from twilio.twiml.messaging_response import MessagingResponse

from routes import get_container
from service.security import verify_webhook_signature
from connectors.whatsapp import parse_inbound, send_reply
from service.analytics_db import log_event, upsert_lead, set_lead_session

logger = logging.getLogger("WA.Webhook")
bp = Blueprint("whatsapp", __name__, url_prefix="/whatsapp")


def _get_handler(container):
    h = getattr(container, "handler", None) or getattr(container, "message_handler", None)
    if h is None:
        logger.error("WA: No MessageHandler instance found on container.")
    return h


@bp.get("/webhook")
def webhook_verify():
    c = get_container()
    verify = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge", "")

    if verify != getattr(c.settings, "WHATSAPP_VERIFY_TOKEN", ""):
        abort(403)

    return challenge, 200, {"Content-Type": "text/plain; charset=utf-8"}


@bp.post("/webhook")
def webhook_receive():
    c = get_container()

    ua = request.headers.get("User-Agent") or ""
    content_type = request.headers.get("Content-Type") or ""
    is_twilio = "TwilioProxy" in ua or content_type.startswith("application/x-www-form-urlencoded")

    # Meta signature verification (Cloud API only)
    app_secret = getattr(c.settings, "WHATSAPP_APP_SECRET", "") or ""
    sig_header = request.headers.get("X-Hub-Signature-256")
    if not is_twilio and app_secret and sig_header:
        if not verify_webhook_signature(request, app_secret):
            logger.warning("WA WEBHOOK: invalid X-Hub-Signature, aborting 403.")
            abort(403)

    handler = _get_handler(c)

    # --------------------------
    # TWILIO (FORM)
    # --------------------------
    if is_twilio:
        form = request.form.to_dict()
        body = (form.get("Body") or "").strip()
        from_raw = (form.get("From") or "").strip()  # "whatsapp:+447..."
        from_id = from_raw.replace("whatsapp:", "").replace("+", "")

        if not body:
            resp = MessagingResponse()
            resp.message("Sorry—I didn’t receive any text.")
            return Response(str(resp), status=200, mimetype="application/xml")

        tenant = getattr(c.settings, "BUSINESS_KEY", "DEFAULT")
        session_id = from_id or "wa_unknown"
        lead_id = f"wa:{from_id or session_id}"
        phone = f"+{from_id}" if from_id else None

        upsert_lead(tenant=tenant, lead_id=lead_id, phone=phone)
        set_lead_session(lead_id=lead_id, session_id=session_id)

        log_event(
            tenant=tenant,
            channel="whatsapp",
            session_id=session_id,
            lead_id=lead_id,
            event_type="msg_in",
            text=body,
            meta={"source": "twilio", "from": from_id},
        )

        logger.info("WA IN: source=twilio tenant=%s session=%s from=%s text=%r", tenant, session_id, from_id, body)

        if handler is None:
            result: Dict[str, Any] = {"reply": "Sorry—bot not configured yet.", "intent": "system_error", "entities": {}}
        else:
            try:
                result = handler.handle(
                    body,
                    tenant=tenant,
                    session_id=session_id,
                    channel="whatsapp",
                    metadata={"wa_id": from_id},
                ) or {}
            except Exception as exc:
                logger.exception("WA: handler.handle crashed: %s", exc)
                log_event(
                    tenant=tenant,
                    channel="whatsapp",
                    session_id=session_id,
                    lead_id=lead_id,
                    event_type="error",
                    error_type=type(exc).__name__,
                    error_code="wa_handler_crash",
                    meta={"error": str(exc)},
                )
                result = {"reply": "Sorry—server error.", "intent": "system_error", "entities": {}}

        reply = (result.get("reply") or "").strip() or "Sorry—I didn’t catch that."
        intent = (result.get("intent") or "unknown").strip()
        entities = result.get("entities", {}) or {}

        logger.info("WA OUT: source=twilio tenant=%s session=%s intent=%s entities=%s reply=%r", tenant, session_id, intent, entities, reply)

        log_event(
            tenant=tenant,
            channel="whatsapp",
            session_id=session_id,
            lead_id=lead_id,
            event_type="msg_out",
            text=reply,
            intent=intent,
            meta={"source": "twilio"},
        )

        if intent == "system_fallback":
            log_event(
                tenant=tenant,
                channel="whatsapp",
                session_id=session_id,
                lead_id=lead_id,
                event_type="fallback",
                text=body,
                intent=intent,
            )

        resp = MessagingResponse()
        resp.message(reply)
        return Response(str(resp), status=200, mimetype="application/xml")

    # --------------------------
    # CLOUD (JSON)
    # --------------------------
    try:
        payload = request.get_json(force=True, silent=True) or {}
    except Exception as exc:
        logger.exception("WA WEBHOOK: invalid JSON payload: %s", exc)
        return jsonify({"error": "invalid_payload"}), 400

    try:
        events = parse_inbound(payload)
    except Exception as exc:
        logger.exception("WA WEBHOOK: parse_inbound failed: %s", exc)
        return jsonify({"ok": True, "events": 0}), 200

    if not events:
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

            lead_id = f"wa:{from_id}"
            upsert_lead(tenant=tenant, lead_id=lead_id)
            set_lead_session(lead_id=lead_id, session_id=session_id)

            log_event(
                tenant=tenant,
                channel="whatsapp",
                session_id=session_id,
                lead_id=lead_id,
                event_type="msg_in",
                text=text,
                meta={"source": "cloud", "from": from_id},
            )

            logger.info("WA IN: source=cloud tenant=%s session=%s from=%s text=%r", tenant, session_id, from_id, text)

            if handler is None:
                result: Dict[str, Any] = {"reply": "Sorry—bot not configured yet.", "intent": "system_error", "entities": {}}
            else:
                try:
                    result = handler.handle(
                        text,
                        tenant=tenant,
                        session_id=session_id,
                        channel="whatsapp",
                        metadata={"wa_id": from_id},
                    ) or {}
                except Exception as exc:
                    logger.exception("WA: handler.handle crashed: %s", exc)
                    log_event(
                        tenant=tenant,
                        channel="whatsapp",
                        session_id=session_id,
                        lead_id=lead_id,
                        event_type="error",
                        error_type=type(exc).__name__,
                        error_code="wa_handler_crash",
                        meta={"error": str(exc)},
                    )
                    result = {"reply": "Sorry—server error.", "intent": "system_error", "entities": {}}

            reply = (result.get("reply") or "").strip()
            intent = (result.get("intent") or "unknown").strip()
            entities = result.get("entities", {}) or {}

            logger.info("WA OUT: source=cloud tenant=%s session=%s intent=%s entities=%s reply=%r", tenant, session_id, intent, entities, reply)

            log_event(
                tenant=tenant,
                channel="whatsapp",
                session_id=session_id,
                lead_id=lead_id,
                event_type="msg_out",
                text=reply,
                intent=intent,
                meta={"source": "cloud"},
            )

            if intent == "system_fallback":
                log_event(
                    tenant=tenant,
                    channel="whatsapp",
                    session_id=session_id,
                    lead_id=lead_id,
                    event_type="fallback",
                    text=text,
                    intent=intent,
                )

            if reply:
                try:
                    send_reply(ev, reply, settings=c.settings)
                except Exception as send_exc:
                    logger.exception("WA WEBHOOK: send_reply failed: %s", send_exc)
                    log_event(
                        tenant=tenant,
                        channel="whatsapp",
                        session_id=session_id,
                        lead_id=lead_id,
                        event_type="error",
                        error_type=type(send_exc).__name__,
                        error_code="wa_send_reply_failed",
                        meta={"error": str(send_exc)},
                    )

            handled += 1
        except Exception:
            logger.exception("Error processing WA event")

    return jsonify({"ok": True, "events": handled}), 200


@bp.route("/status", methods=["POST", "GET"])
def whatsapp_status():
    form = request.form.to_dict()
    logger.info("WA STATUS: %s", form)
    return Response(status=204)
