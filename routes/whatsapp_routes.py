# routes/whatsapp_routes.py
from __future__ import annotations

import logging
from typing import Any, Dict

from flask import Blueprint, Response, abort, jsonify, request
from twilio.twiml.messaging_response import MessagingResponse

from routes import get_container
from connectors.whatsapp import parse_inbound, send_reply
from service.security import verify_webhook_signature

# ✅ DB analytics
from service.analytics_db import (
    log_message,
    log_error,          # ✅ NEW
    upsert_lead,
    set_lead_session,
)

logger = logging.getLogger("WA.Webhook")
bp = Blueprint("whatsapp", __name__, url_prefix="/whatsapp")


def _get_handler(container):
    h = getattr(container, "handler", None) or getattr(container, "message_handler", None)
    if h is None:
        logger.error("WA: No MessageHandler instance found on container.")
    return h


def _norm_wa_id(raw: str) -> str:
    s = (raw or "").strip()
    s = s.replace("whatsapp:", "").strip()
    if s.startswith("+"):
        s = s[1:]
    return s


def _lead_id_from_sender(sender_digits: str) -> str:
    sender_digits = (sender_digits or "unknown").strip() or "unknown"
    return f"wa:{sender_digits}"


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
    is_twilio = ("TwilioProxy" in ua) or content_type.startswith("application/x-www-form-urlencoded")

    # Meta signature verification (Cloud API only)
    app_secret = getattr(c.settings, "WHATSAPP_APP_SECRET", "") or ""
    sig_header = request.headers.get("X-Hub-Signature-256")
    if (not is_twilio) and app_secret and sig_header:
        if not verify_webhook_signature(request, app_secret):
            logger.warning("WA WEBHOOK: invalid X-Hub-Signature, aborting 403.")
            abort(403)

    handler = _get_handler(c)
    tenant_default = getattr(c.settings, "BUSINESS_KEY", "DEFAULT") or "DEFAULT"

    # ------------------------------------------------------------------
    # TWILIO (FORM)
    # ------------------------------------------------------------------
    if is_twilio:
        form = request.form.to_dict()
        body = (form.get("Body") or "").strip()
        from_raw = (form.get("From") or "").strip()
        sender_digits = _norm_wa_id(from_raw)

        if not body:
            resp = MessagingResponse()
            resp.message("Sorry—I didn’t receive any text.")
            return Response(str(resp), status=200, mimetype="application/xml")

        tenant = tenant_default
        session_id = sender_digits or "wa_unknown"
        lead_id = _lead_id_from_sender(sender_digits)
        phone = f"+{sender_digits}" if sender_digits else None

        # Lead + session
        try:
            upsert_lead(tenant=tenant, lead_id=lead_id, phone=phone)
            set_lead_session(tenant=tenant, lead_id=lead_id, session_id=session_id)
        except Exception:
            pass

        # ✅ inbound message (Common Questions)
        try:
            log_message(
                tenant=tenant,
                channel="whatsapp",
                direction="inbound",
                session_id=session_id,
                intent="unknown",
                text=body,
                lead_id=lead_id,
                store=None,
                fallback=False,
                error=False,
            )
        except Exception:
            pass

        logger.info("WA IN: source=twilio tenant=%s session=%s from=%s text=%r", tenant, session_id, sender_digits, body)

        # Handle
        if handler is None:
            result: Dict[str, Any] = {"reply": "Sorry—bot not configured yet.", "intent": "system_error", "entities": {}}
        else:
            try:
                result = handler.handle(
                    body,
                    tenant=tenant,
                    session_id=session_id,
                    channel="whatsapp",
                    metadata={"wa_id": sender_digits, "source": "twilio"},
                ) or {}
            except Exception as exc:
                logger.exception("WA: handler.handle crashed: %s", exc)

                # ✅ ERROR as its own event_type=error (does NOT inflate outbound)
                try:
                    log_error(
                        tenant=tenant,
                        channel="whatsapp",
                        session_id=session_id,
                        lead_id=lead_id,
                        error_code="wa_handler_crash",
                        error_type=type(exc).__name__,
                        meta={"source": "twilio"},
                    )
                except Exception:
                    pass

                result = {"reply": "Sorry—server error.", "intent": "system_error", "entities": {}}

        reply = (result.get("reply") or "").strip() or "Sorry—I didn’t catch that."
        intent = (result.get("intent") or "unknown").strip()
        is_fallback = (intent == "system_fallback")

        logger.info("WA OUT: source=twilio tenant=%s session=%s intent=%s reply_len=%s", tenant, session_id, intent, len(reply))

        # ✅ outbound message row (fallback is a flag on msg_out)
        try:
            log_message(
                tenant=tenant,
                channel="whatsapp",
                direction="outbound",
                session_id=session_id,
                intent=intent,
                text=reply,
                lead_id=lead_id,
                store=None,
                fallback=is_fallback,
                error=False,
            )
        except Exception:
            pass

        resp = MessagingResponse()
        resp.message(reply)
        return Response(str(resp), status=200, mimetype="application/xml")

    # ------------------------------------------------------------------
    # CLOUD (JSON)
    # ------------------------------------------------------------------
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

    for ev in events:
        try:
            text = (ev.get("text") or "").strip()
            if not text:
                continue

            from_raw = (ev.get("from") or "unknown").strip()
            sender_digits = _norm_wa_id(from_raw)
            session_id = (ev.get("session_id") or sender_digits or "wa_unknown").strip()
            tenant = (ev.get("tenant") or tenant_default).strip() or tenant_default

            lead_id = _lead_id_from_sender(sender_digits)
            phone = f"+{sender_digits}" if sender_digits and sender_digits.isdigit() else None

            try:
                upsert_lead(tenant=tenant, lead_id=lead_id, phone=phone)
                set_lead_session(tenant=tenant, lead_id=lead_id, session_id=session_id)
            except Exception:
                pass

            # ✅ inbound (Common Questions)
            try:
                log_message(
                    tenant=tenant,
                    channel="whatsapp",
                    direction="inbound",
                    session_id=session_id,
                    intent="unknown",
                    text=text,
                    lead_id=lead_id,
                    store=None,
                    fallback=False,
                    error=False,
                )
            except Exception:
                pass

            logger.info("WA IN: source=cloud tenant=%s session=%s from=%s text=%r", tenant, session_id, sender_digits, text)

            # Handle
            if handler is None:
                result: Dict[str, Any] = {"reply": "Sorry—bot not configured yet.", "intent": "system_error", "entities": {}}
            else:
                try:
                    result = handler.handle(
                        text,
                        tenant=tenant,
                        session_id=session_id,
                        channel="whatsapp",
                        metadata={"wa_id": sender_digits, "source": "cloud"},
                    ) or {}
                except Exception as exc:
                    logger.exception("WA: handler.handle crashed: %s", exc)
                    try:
                        log_error(
                            tenant=tenant,
                            channel="whatsapp",
                            session_id=session_id,
                            lead_id=lead_id,
                            error_code="wa_handler_crash",
                            error_type=type(exc).__name__,
                            meta={"source": "cloud"},
                        )
                    except Exception:
                        pass
                    result = {"reply": "Sorry—server error.", "intent": "system_error", "entities": {}}

            reply = (result.get("reply") or "").strip()
            intent = (result.get("intent") or "unknown").strip()
            is_fallback = (intent == "system_fallback")

            logger.info("WA OUT: source=cloud tenant=%s session=%s intent=%s reply_len=%s", tenant, session_id, intent, len(reply))

            # ✅ outbound
            try:
                log_message(
                    tenant=tenant,
                    channel="whatsapp",
                    direction="outbound",
                    session_id=session_id,
                    intent=intent,
                    text=reply,
                    lead_id=lead_id,
                    store=None,
                    fallback=is_fallback,
                    error=False,
                )
            except Exception:
                pass

            # Send reply
            if reply:
                try:
                    send_reply(ev, reply, settings=c.settings)
                except Exception as send_exc:
                    logger.exception("WA WEBHOOK: send_reply failed: %s", send_exc)
                    try:
                        log_error(
                            tenant=tenant,
                            channel="whatsapp",
                            session_id=session_id,
                            lead_id=lead_id,
                            error_code="wa_send_reply_failed",
                            error_type=type(send_exc).__name__,
                            meta={"source": "cloud"},
                        )
                    except Exception:
                        pass

            handled += 1

        except Exception:
            logger.exception("Error processing WA event")

    return jsonify({"ok": True, "events": handled}), 200


@bp.route("/status", methods=["POST", "GET"])
def whatsapp_status():
    form = request.form.to_dict()
    logger.info("WA STATUS: %s", form)
    return Response(status=204)
