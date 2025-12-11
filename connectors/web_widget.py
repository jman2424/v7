"""
Web widget connector + iframe bridge.

This module provides:

1) WidgetBridge  -> for the iframe-based SDK (postMessage contract)
2) parse_inbound -> normalise /chat_api JSON into a single event
3) send_reply    -> build the JSON response for /chat_api

Event shape (inbound to core):

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

Response shape (outbound):

{
  "reply": "string",
  "raw": {...},
  "session_id": "asa_..."
}
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
import logging

logger = logging.getLogger("WebWidgetConnector")


# -------------------------------------------------------------------
# Iframe bridge (for SDK / widget.js postMessage integration)
# -------------------------------------------------------------------

EVT_TO_IFRAME = "ASA_WIDGET:client->iframe"
EVT_FROM_IFRAME = "ASA_WIDGET:iframe->client"

DEFAULT_ALLOWED_ORIGINS: List[str] = [
    "http://localhost",
    "http://localhost:3000",
    "http://127.0.0.1",
    "https://web-tester-jnwd.onrender.com",  # frontend
    "https://v7-52g3.onrender.com",          # widget host
]


def _canon_origin(u: str) -> str:
    try:
        p = urlparse(u)
        return f"{p.scheme}://{p.netloc}"
    except Exception:
        return ""


@dataclass
class WidgetBridge:
    """
    Stateless helpers to work with the iframe bridge.

    Typical flow (inside widget.js):
      - Validate event.origin with validate_origin()
      - Validate payload with is_chat_message()
      - POST to /chat_api
      - Post a reply back with build_reply_event()
    """

    allowed_origins: Optional[List[str]] = None

    # ---- validation ----

    def validate_origin(self, origin: str) -> bool:
        if not origin:
            return False
        allowed = self.allowed_origins or DEFAULT_ALLOWED_ORIGINS
        o = _canon_origin(origin)
        return any(o.startswith(a) for a in allowed)

    def is_chat_message(self, payload: Dict[str, Any]) -> bool:
        if not isinstance(payload, dict):
            return False
        if payload.get("type") != "chat:message":
            return False
        text = payload.get("text")
        return isinstance(text, str) and len(text.strip()) > 0

    def parse_chat_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Returns a normalized dict:
        {
          "message": str,
          "session_id": str | None,
          "channel": "web",
          "tenant": str | None,
          "metadata": dict
        }
        """
        text = (payload.get("text") or "").strip()
        sess = (payload.get("sessionId") or "").strip() or None
        meta = payload.get("metadata") or {}
        tenant = payload.get("tenant") or None
        return {
            "message": text,
            "session_id": sess,
            "channel": "web",
            "tenant": tenant,
            "metadata": meta if isinstance(meta, dict) else {},
        }

    # ---- outbound events (iframe) ----

    def build_ready_event(self, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {"__asa": EVT_FROM_IFRAME, "payload": {"type": "ready", "data": data or {}}}

    def build_typing_event(self, on: bool = True) -> Dict[str, Any]:
        return {"__asa": EVT_FROM_IFRAME, "payload": {"type": "chat:typing", "data": {"on": bool(on)}}}

    def build_reply_event(self, reply: str, raw: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "__asa": EVT_FROM_IFRAME,
            "payload": {
                "type": "chat:reply",
                "data": {"reply": str(reply or ""), "raw": raw or {}},
            },
        }

    def build_error_event(self, message: str, code: str = "widget_error") -> Dict[str, Any]:
        return {
            "__asa": EVT_FROM_IFRAME,
            "payload": {"type": "error", "data": {"code": code, "message": str(message)}},
        }

    def build_metrics_event(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        return {"__asa": EVT_FROM_IFRAME, "payload": {"type": "metrics", "data": dict(metrics or {})}}


# -------------------------------------------------------------------
# /chat_api normalisation helpers
# -------------------------------------------------------------------


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
    Use explicit session_id if provided, otherwise fall back to
    the old behaviour: "asa_<remote_addr>".
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

    Returns:
    { "reply": str, "raw": {...}, "session_id": "asa_..." }
    """
    session_id = event.get("session_id")

    return {
        "reply": str(reply or ""),
        "raw": raw or {},
        "session_id": session_id,
    }
