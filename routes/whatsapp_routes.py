"""Optional WhatsApp endpoints. Unconfigured integrations fail closed."""
from __future__ import annotations

import hashlib
import hmac
import os
import logging
from dataclasses import replace

from flask import Blueprint, Response, abort, jsonify, request
from twilio.request_validator import RequestValidator
from twilio.twiml.messaging_response import MessagingResponse

from connectors.whatsapp import parse_inbound, send_reply
from routes import get_container
from service import webhook_inbox
from service.analytics_db import log_error, log_message, set_lead_session, upsert_lead

bp = Blueprint("whatsapp", __name__, url_prefix="/whatsapp")


def _verify():
    settings = get_container().settings
    if request.mimetype == "application/x-www-form-urlencoded":
        token = os.getenv("TWILIO_AUTH_TOKEN", "") or settings.TWILIO_AUTH_TOKEN
        if not token or not (os.getenv("TWILIO_WHATSAPP_NUMBER") or settings.WHATSAPP_TENANT_MAP):
            abort(503, description="whatsapp_not_configured")
        url = settings.BASE_URL.rstrip("/") + request.full_path.rstrip("?")
        if not RequestValidator(token).validate(url, request.form, request.headers.get("X-Twilio-Signature", "")):
            abort(403)
        return "twilio"
    if not settings.WHATSAPP_APP_SECRET:
        abort(503, description="whatsapp_not_configured")
    expected = "sha256=" + hmac.new(settings.WHATSAPP_APP_SECRET.encode(), request.get_data(), hashlib.sha256).hexdigest()
    supplied = request.headers.get("X-Hub-Signature-256", "")
    if not hmac.compare_digest(expected.encode(), supplied.encode()):
        abort(403)
    return "cloud"


@bp.get("/webhook")
def webhook_verify():
    expected = get_container().settings.WHATSAPP_VERIFY_TOKEN
    if not expected:
        abort(503, description="whatsapp_not_configured")
    supplied = request.args.get("hub.verify_token", "")
    if request.args.get("hub.mode") != "subscribe" or not hmac.compare_digest(expected.encode(), supplied.encode()):
        abort(403)
    return request.args.get("hub.challenge", ""), 200, {"Content-Type": "text/plain"}


def _reply(c, event, source):
    text = event.get("text")
    sender = event.get("from", "")
    if not isinstance(text, str) or not text.strip() or len(text) > 4000 or not isinstance(sender, str):
        abort(400)
    sender = sender.removeprefix("whatsapp:").lstrip("+")
    if not sender.isdigit() or len(sender) > 20:
        abort(400)
    tenant = c.settings.BUSINESS_KEY
    sid = "wa:" + sender
    raw = event.get("raw", {})
    mid = raw.get("id") or raw.get("MessageSid") or ""
    logging.getLogger("WA.Webhook").info("WA inbound source=%s tenant=%s message_len=%s", source, tenant, len(text))
    upsert_lead(tenant=tenant, lead_id=sid, phone="+" + sender)
    set_lead_session(tenant=tenant, lead_id=sid, session_id=sid)
    log_message(tenant=tenant, channel="whatsapp", direction="inbound", session_id=sid,
                text=text, lead_id=sid, message_id=mid)
    try:
        metadata = {"source": source, "wa_id": sender}
        if source == "cloud":
            metadata["phone_number_id"] = event.get("metadata", {}).get("phone_number_id")
        result = c.handler.handle(text, tenant=tenant, session_id=sid, channel="whatsapp",
                                  metadata=metadata)
        reply = result.get("reply") if isinstance(result, dict) else None
        if not isinstance(reply, str) or not reply.strip() or result.get("intent") == "system_error":
            raise ValueError("Invalid agent response")
    except Exception as error:
        log_error(tenant=tenant, channel="whatsapp", session_id=sid,
                  error_code="wa_handler_failure", error_type=type(error).__name__)
        abort(503, description="agent_unavailable")
    from service.product_metrics import matched_products
    log_message(tenant=tenant, channel="whatsapp", direction="outbound", session_id=sid,
                text=reply, intent=str(result.get("intent", "unknown")), lead_id=sid,
                fallback=any(result.get(key) is True for key in ('fallback','is_fallback','did_fallback')) or result.get('intent') in {'system_no_results','system_clarify','unknown','fallback','default','clarify','needs_clarification','no_match','system_fallback'},
                products=matched_products(result),
                message_id=mid + ":out" if mid else "")
    return reply


def _process(c, event, source):
    from service.subscriptions import whatsapp_enabled
    if not whatsapp_enabled(c.settings.BUSINESS_KEY):
        return ''
    raw = event.get("raw", {})
    message_id = raw.get("id") if source == "cloud" else raw.get("MessageSid")
    if not isinstance(message_id, str) or not message_id or len(message_id) > 200:
        abort(400, description="message_id_required")
    key = (c.settings.BUSINESS_KEY, source, message_id)
    state, cached_reply = webhook_inbox.claim(*key)
    if state == "done":
        return cached_reply
    if state == "busy":
        abort(503, description="message_processing")
    try:
        reply = _reply(c, event, source)
        if source == "cloud":
            phone_id = event.get("metadata", {}).get("phone_number_id")
            send_reply(event, reply, settings=replace(c.settings, WHATSAPP_PHONE_ID=phone_id))
        webhook_inbox.finish(*key, reply)
        return reply
    except Exception as error:
        webhook_inbox.finish(*key, None, failed=True)
        log_error(tenant=c.settings.BUSINESS_KEY, channel="whatsapp", session_id="provider",
                  error_code="wa_processing_failure", error_type=type(error).__name__)
        abort(503, description="whatsapp_processing_failed")


@bp.post("/webhook")
def webhook_receive():
    source = _verify()
    root = get_container()
    def recipient_container(recipient):
        number = str(recipient or "").removeprefix("whatsapp:").lstrip("+")
        mapping = root.settings.WHATSAPP_TENANT_MAP
        expected = os.getenv("TWILIO_WHATSAPP_NUMBER", "") if source == "twilio" else root.settings.WHATSAPP_PHONE_ID
        tenant = mapping.get(number) if mapping else root.settings.BUSINESS_KEY if number and number == expected.removeprefix("whatsapp:").lstrip("+") else None
        if not tenant:
            abort(403)
        try:
            return root.for_tenant(tenant)
        except (FileNotFoundError, ValueError):
            abort(503, description="whatsapp_tenant_not_configured")
    if source == "twilio":
        c = recipient_container(request.form.get("To"))
        events = parse_inbound({"raw_form": request.form.to_dict()})
        response = MessagingResponse()
        if events:
            response.message(_process(c, events[0], source))
        return Response(str(response), mimetype="application/xml")

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        abort(400)
    try:
        events = parse_inbound(payload)
    except (TypeError, AttributeError, KeyError):
        abort(400, description="invalid_webhook_payload")
    if events and not root.settings.WHATSAPP_TOKEN:
        abort(503, description="whatsapp_not_configured")
    for event in events:
        c = recipient_container(event.get("metadata", {}).get("phone_number_id"))
        _process(c, event, source)
    return jsonify(ok=True, events=len(events))


@bp.route("/status", methods=["GET", "POST"])
def whatsapp_status():
    # Preserve callback URL while denying unsigned status submissions.
    if request.method == "GET":
        return jsonify(ok=True, integration="whatsapp", configured=bool(
            get_container().settings.WHATSAPP_APP_SECRET or os.getenv("TWILIO_AUTH_TOKEN")))
    _verify()
    return Response(status=204)
