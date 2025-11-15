"""
WhatsApp Cloud API connector.

Provides:
- parse_inbound(payload) -> list[dict]
- send_reply(event, reply, settings) -> None

This is intentionally thin:
- No business logic
- Just maps Meta webhook JSON -> our internal event format
- And sends text replies using the Cloud API
"""

from __future__ import annotations

from typing import Any, Dict, List
import logging
import requests

from app.config import Settings

logger = logging.getLogger("WhatsAppConnector")


def parse_inbound(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Parse inbound WhatsApp Cloud API webhook payload into a flat list of events.

    Input shape (simplified Meta spec):

    {
      "entry": [
        {
          "changes": [
            {
              "value": {
                "metadata": {
                  "display_phone_number": "...",
                  "phone_number_id": "..."
                },
                "contacts": [...],
                "messages": [
                  {
                    "from": "447...",
                    "id": "...",
                    "timestamp": "...",
                    "type": "text",
                    "text": {"body": "hello"}
                  }
                ]
              }
            }
          ]
        }
      ]
    }

    Output event shape (what routes.whatsapp_routes expects):

    {
      "from": "447...",
      "session_id": "447...",
      "tenant": "<optional tenant key>",
      "text": "hello",
      "raw": <original message dict>,
    }
    """
    events: List[Dict[str, Any]] = []

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
                        "session_id": wa_id,  # simple: 1 session per number
                        # We *could* map tenant off phone_number_id if you multi-tenant later
                        "tenant": None,
                        "text": text,
                        "raw": msg,
                        "metadata": {
                            "phone_number_id": metadata.get("phone_number_id"),
                            "display_phone_number": metadata.get("display_phone_number"),
                        },
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

    If config is missing, logs a warning and no-ops.
    """
    wa_id = event.get("from")
    if not wa_id:
        logger.warning("send_reply: missing 'from' in event, cannot reply")
        return

    token = settings.WHATSAPP_TOKEN
    phone_id = settings.WHATSAPP_PHONE_ID
    base_url = settings.WHATSAPP_API_URL or "https://graph.facebook.com/v21.0"

    if not token or not phone_id:
        logger.warning(
            "send_reply: missing WA config (token/phone_id). Skipping send.",
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
                "send_reply: WA API returned non-2xx",
                extra={
                    "status": resp.status_code,
                    "body": resp.text[:500],
                    "wa_id": wa_id,
                },
            )
    except Exception as exc:
        logger.exception(
            "send_reply: exception while calling WA API",
            extra={"wa_id": wa_id, "error": str(exc)},
        )
