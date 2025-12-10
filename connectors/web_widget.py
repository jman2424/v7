"""
Web widget connector.

Purpose:
- Normalise inbound messages coming from the web widget (/chat_api).
- Provide a helper to build the JSON reply that /chat_api returns.

Designed to mirror the WhatsApp connector shape:

Inbound event:
{
  "from": "web:<session_id>",
  "session_id": "asa_...",
  "tenant": "<tenant key or None>",
  "text": "hello",
  "raw": <original payload dict>,
  "metadata": {...},
  "source": "web_widget",
  "channel": "web",
}

Outbound response (for /chat_api):
{
  "reply": "string",
  "raw": {...},         # full result from message_handler
  "session_id": "asa_..."
}
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger("WebWidgetConnector")


def _extract_text(payload: Dict[str, Any]) -> str:
    """
    Supports both:
    - /chat_api contract: { "message": "hi", ... }
    - widget-style contract: { "text": "hi", ... }
    """
    text = (payload.get("message") or payload.get("text") or "").strip()
    return text


def _extract_session_id(payload: Dict[str, Any], remote_addr: Optional[str]) -> str:
    """
    Use explicit session_id if provided, otherwise fall back to the
    old behaviour: "asa_<remote_addr>".
    """
    sess = (
        payload.get("session_id")
        or payload.get("sessionId")
        or ""
    ).strip()

    if not sess and remote_addr:
        sess = f"asa_{remote_addr}"

    return sess or "asa_anon"


def parse_inbound(
    payload: Dict[str, Any],
    *,
    default_tenant: Optional[str] = None,
    default_channel: str = "web",
    remote_addr: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Parse inbound web widget payload into a flat list of events.

    Input (typical /chat_api JSON):
    {
      "message": "hi",
      "session_id": "asa_...",
      "channel": "web",
      "tenant": "tariq_meatshop",
      "metadata": {...}
    }

    Returns:
    [
      {
        "from": "web:asa_...",
        "session_id": "asa_...",
        "tenant": "...",
        "text": "hi",
        "raw": <original payload>,
        "metadata": {...},
        "source": "web_widget",
        "channel": "web",
      }
    ]
    """
    events: List[Dict[str, Any]] = []

    if not isinstance(payload, dict):
        logger.debug("parse_inbound(web): payload is not a dict (%r)", type(payload))
        return events

    text = _extract_text(payload)
    if not text:
        logger.debug("parse_inbound(web): missing/empty message/text")
        return events

    session_id = _extract_session_id(payload, remote_addr)
    channel = (payload.get("channel") or default_channel or "web").strip() or "web"
    tenant = payload.get("tenant") or default_tenant

    metadata = payload.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}

    events.append(
        {
            "from": f"web:{session_id}",
            "session_id": session_id,
            "tenant": tenant,
            "text": text,
            "raw": payload,
            "metadata": metadata,
            "source": "web_widget",
            "channel": channel,
        }
    )

    return events


def send_reply(
    event: Dict[str, Any],
    reply: str,
    *,
    raw: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build the JSON response that /chat_api should return.

    Matches your documented contract:

    Returns:
    { "reply": str, "raw": {...}? }
    """
    session_id = event.get("session_id")

    return {
        "reply": str(reply or ""),
        "raw": raw or {},
        "session_id": session_id,
    }
