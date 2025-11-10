"""
Web widget connector (iframe bridge contract).

Purpose:
- Define the payload contract between the embedding page (client SDK) and the
  widget page (server-rendered /chat_ui).
- Provide helpers to validate incoming messages and build outgoing replies.
- Protect against origin spoofing and malformed messages.

This must align with:
- sdk/js/index.js (EVT names, fields)
- dashboards/static/js/widget.js (iframe-side listener)
- routes/webchat_routes.py (/chat_ui GET, /chat_api POST)

Contract (incoming from client):
{
  "type": "chat:message",
  "sessionId": "asa_...",
  "text": "string",
  "metadata": {...}
}

Contract (outgoing to client):
{
  "type": "chat:reply",
  "data": {
    "reply": "string",
    "raw": {...}
  }
}
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse


EVT_TO_IFRAME = "ASA_WIDGET:client->iframe"
EVT_FROM_IFRAME = "ASA_WIDGET:iframe->client"

DEFAULT_ALLOWED_ORIGINS: List[str] = [
    "http://localhost",
    "http://localhost:3000",
    "http://127.0.0.1",
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

    Typical server flow (in /chat_ui page script or widget.js):
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
        { "message": str, "session_id": str, "channel": "web", "tenant": str|None, "metadata": dict }
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

    # ---- outbound events ----

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
