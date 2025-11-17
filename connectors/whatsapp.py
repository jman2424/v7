"""
WhatsApp connector.

Supports:
- Meta WhatsApp Cloud API webhooks (JSON)
- Twilio WhatsApp webhooks (form-encoded)

Provides:
- parse_inbound(payload) -> list[dict]
- send_reply(event, reply, settings) -> None  (Cloud API only)
"""

from __future__ import annotations

from typing import Any, Dict, List
import logging
import requests

from app.config import Settings

logger = logging.getLogger("WhatsAppConnector")


def parse_inbound(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Parse inbound WhatsApp webhook payload into a flat list of events.

    Two modes:

    1) Meta Cloud API JSON (payload["entry"]...):
       -> events with source="cloud"

    2) Twilio form-encoded (wrapped in {"raw_form": {...}} by the route):
       -> events with source="twilio"

    Normalised event shape:

    {
      "from": "447...",
      "session_id": "447...",
      "tenant": "<optional tenant key>",
      "text": "hello",
      "raw": <original message dict>,
      "metadata": {...},
      "source": "cloud" | "twilio",
    }
    """
    events: List[Dict[str, Any]] = []

    # -------- Twilio form-encoded (wrapped as "raw_form") ----------
    if "raw_form" in payload:
        form = payload.get("raw_form") or {}
        body = (form.get("Body") or "").strip()

        # Twilio WA sends both WaId and From (with "whatsapp:" prefix)
        wa_id = (form.get("WaId") or "").strip()
        if not wa_id:
            frm = (form.get("From") or "").strip()
            if frm.startswith("whatsapp:"):
                frm = frm[len("whatsapp:") :]
            wa_id = frm

        if body and wa_id:
            events.append(
                {
                    "from": wa_id,
                    "session_id": wa_id,  # 1 session per number
                    "tenant": None,
                    "text": body,
                    "raw": form,
                    "metadata": {
                        "twilio_message_sid": form.get("MessageSid"),
                        "profile_name": form.get("ProfileName"),
                    },
                    "source": "twilio",
                }
            )
        else:
            logger.debug(
                "parse_inbound(Twilio): missing wa_id/body; form=%r",
                {k: form.get(k) for k in ["From", "WaId", "Body"]},
            )

        return events

    # -------- Meta Cloud API JSON ----------
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {}) or {}
            metadata = value.get("metadata", {}) or {}
            messages = value.get("messages", []) or []

            for msg in messages:
                # Only handle text messages for now
                if msg.get("type") != "text":
                    continue

                wa_id = msg.get("from")
                text = (msg.get("text", {}) or {}).get("body", "") or ""

                if not wa_id or not text.strip():
                    continue

                events.append(
                    {
                        "from": wa_id,
                        "session_id": wa_id,  # 1 session per number
                        "tenant": None,
                        "text": text,
                        "raw": msg,
                        "metadata": {
                            "phone_number_id": metadata.get("phone_number_id"),
                            "display_phone_number": metadata.get(
                                "display_phone_number"
                            ),
                        },
                        "source": "cloud",
                    }
                )

    if not events:
        logger.debug("parse_inbound: no text messages found in payload")

    return events


def send_reply(event: Dict[str, Any], reply: str, *, settings: Settings) -> None:
    """
    Send a text reply back via WhatsApp Cloud API.

    Uses:
      settings.WHATSAPP_TOKEN
      settings.WHATSAPP_PHONE_ID
      settings.WHATSAPP_API_URL (optional override)

    Twilio replies are handled in the route via TwiML and **do not** use this.
    """
    # Skip if this is a Twilio event
    if event.get("source") == "twilio":
        logger.debug("send_reply: Twilio event; reply handled via TwiML.")
        return

    wa_id = event.get("from")
    if not wa_id:
        logger.warning("send_reply: missing 'from' in event, cannot reply")
        return

    token = settings.WHATSAPP_TOKEN
    phone_id = settings.WHATSAPP_PHONE_ID
    base_url = settings.WHATSAPP_API_URL or "https://graph.facebook.com/v21.0"

    if not token or not phone_id:
        logger.warning(
            "send_reply: missing WA Cloud API config (token/phone_id). Skipping send.",
            extra={"wa_id": wa_id},
        )
        return

    url = f"{base_url.rstrip('/')}/{phone_id}/messages"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    payload: Dict[str, Any] = {
        "messaging_product": "whatsapp",
        "to": wa_id,
        "type": "text",
        "text": {"body": reply},
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=8)
        if resp.status_code >= 400:
            logger.warning(
                "send_reply: WA Cloud API returned non-2xx",
                extra={
                    "status": resp.status_code,
                    "body": resp.text[:500],
                    "wa_id": wa_id,
                },
            )
    except Exception as exc:
        logger.exception(
            "send_reply: exception while calling WA Cloud API",
            extra={"wa_id": wa_id, "error": str(exc)},
        )
