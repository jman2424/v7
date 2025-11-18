# routes/whatsapp_routes.py
from __future__ import annotations

import logging
from typing import Any, Dict

from flask import Blueprint, request, abort, jsonify, Response
from twilio.twiml.messaging_response import MessagingResponse
from openai import OpenAI

from routes import get_container
from service.security import verify_webhook_signature
from service import message_handler
from connectors.whatsapp import parse_inbound, send_reply

logger = logging.getLogger("WA.Webhook")

# This is what app.__init__ imports as `whatsapp_bp`
bp = Blueprint("whatsapp", __name__, url_prefix="/whatsapp")


# ---------- Core bot wrapper ----------

def _call_bot(
    c,
    *,
    text: str,
    session_id: str,
    channel: str,
    tenant: str,
    metadata: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Unified wrapper around whatever bot handler exists.

    Priority:
      1) service.message_handler.handle(container, text=..., ...)
      2) service.message_handler.handle_message(text, sender=..., state=...)
      3) Fallback: direct OpenAI call (uses OPENAI_API_KEY, OPENAI_MODEL)
    """
    metadata = metadata or {}

    # --- 1) New-style handler: handle(container, ...) ---
    if hasattr(message_handler, "handle"):
        return message_handler.handle(
            c,
            text=text,
            session_id=session_id,
            channel=channel,
            tenant=tenant,
            metadata=metadata,
        )

    # --- 2) Legacy handler: handle_message(text, sender=..., state=...) ---
    if hasattr(message_handler, "handle_message"):
        logger.debug("WA: using legacy message_handler.handle_message()")

        state = {
            "session_id": session_id,
            "tenant": tenant,
            "channel": channel,
        }
        reply_text = message_handler.handle_message(
            text,
            sender=channel,
            state=state,
        )
        return {
            "reply": reply_text or "",
            "intent": None,
            "resolved": True,
            "_latency_ms": 0,
        }

    # --- 3) Hard fallback: direct OpenAI call ---
    logger.warning(
        "WA: No message_handler.handle or handle_message found. "
        "Using direct OpenAI fallback."
    )

    api_key = getattr(c.settings, "OPENAI_API_KEY", "") or ""
    model = getattr(c.settings, "OPENAI_MODEL", "") or "gpt-4o-mini"

    if not api_key:
        logger.error("WA: OPENAI_API_KEY missing; cannot call OpenAI.")
        return {
            "reply": "Sorry—my brain isn’t configured properly yet.",
            "intent": None,
            "resolved": False,
            "_latency_ms": 0,
        }

    client = OpenAI(api_key=api_key)

    system_prompt = (
        "You are the Tariq Halal Meat Shop assistant on WhatsApp. "
        "Answer concisely and helpfully. If the user asks about meat, products, "
        "or prices, respond like a friendly shop assistant. "
        "Ask clarifying questions if needed instead of making things up."
    )

    try:
        completion = client.chat.completions.create(
            model=model,
            temperature=getattr(c.settings, "OPENAI_TEMPERATURE", 0.4),
            max_tokens=getattr(c.settings, "AI_MAX_TOKENS", 800),
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": f"[channel={channel} tenant={tenant}] {text}",
                },
            ],
        )
        reply = (completion.choices[0].message.content or "").strip()
    except Exception as exc:
        logger.exception("WA: OpenAI fallback failed: %s", exc)
        reply = "Sorry—there was an error talking to the AI."

    return {
        "reply": reply,
        "intent": None,
        "resolved": True,
        "_latency_ms": 0,
    }


# ---------- Meta verification (for Cloud API) ----------

@bp.get("/webhook")
def webhook_verify():
    """
    Facebook/WhatsApp Cloud API verification echo.

    Expects:
      - hub.mode
      - hub.verify_token
      - hub.challenge

    Twilio sandbox will NOT use this.
    """
    c = get_container()
    verify = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge", "")

    if verify != c.settings.WHATSAPP_VERIFY_TOKEN:
        abort(403)

    # Meta expects the challenge string as plain text
    return challenge, 200, {"Content-Type": "text/plain; charset=utf-8"}


# ---------- Main webhook (Twilio + Cloud API) ----------

@bp.post("/webhook")
def webhook_receive():
    """
    Receive inbound WhatsApp messages.

    Supports:
      - Twilio WhatsApp sandbox (form-encoded; User-Agent: TwilioProxy/1.1)
      - Meta WhatsApp Cloud API (JSON + X-Hub-Signature-256)

    Logic:
      * Detect Twilio vs Cloud API
      * For Cloud API: verify X-Hub-Signature-256 with app secret
      * Normalise events
      * Route into _call_bot()
      * Reply:
          - Twilio: TwiML response
          - Cloud API: REST send via connectors.whatsapp.send_reply
    """
    c = get_container()

    # --- Detect Twilio ---
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
            "WA WEBHOOK: no X-Hub-Signature-256 present; "
            "skipping Meta signature check."
        )

    # ----- Twilio path (simple: single message per webhook) -----
    if is_twilio:
        form = request.form.to_dict()
        body = (form.get("Body") or "").strip()
        from_raw = (form.get("From") or "").strip()  # e.g. "whatsapp:+4473..."
        from_id = from_raw.replace("whatsapp:", "").replace("+", "")

        if not body:
            resp = MessagingResponse()
            resp.message("Sorry—I didn’t receive any text.")
            return Response(str(resp), status=200, mimetype="application/xml")

        session_id = from_id or "wa_unknown"
        tenant = c.settings.BUSINESS_KEY

        logger.info(
            "WA IN: source=twilio tenant=%s session=%s from=%s text=%r",
            tenant,
            session_id,
            from_id,
            body,
        )

        result = _call_bot(
            c,
            text=body,
            session_id=session_id,
            channel="wa",
            tenant=tenant,
            metadata={"wa_id": from_id},
        )

        reply = (result.get("reply") or "").strip()
        if not reply:
            reply = "Sorry—I didn’t catch that."

        # Analytics (best effort)
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

        resp = MessagingResponse()
        resp.message(reply)

        return Response(str(resp), status=200, mimetype="application/xml")

    # ----- Cloud API path (Meta JSON) -----
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

    for ev in events:
        try:
            text = (ev.get("text") or "").strip()
            if not text:
                continue

            from_id = ev.get("from") or "unknown"
            session_id = ev.get("session_id") or from_id
            tenant = ev.get("tenant") or c.settings.BUSINESS_KEY

            logger.info(
                "WA IN: source=cloud tenant=%s session=%s from=%s text=%r",
                tenant,
                session_id,
                from_id,
                text,
            )

            result = _call_bot(
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

            # Analytics (best effort)
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
