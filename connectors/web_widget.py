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
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
import logging
import secrets


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
    """
    Canonicalize a browser origin string into scheme://netloc.
    Returns "" on failure.
    """
    try:
        p = urlparse(u)
        if not p.scheme or not p.netloc:
            return ""
        return f"{p.scheme}://{p.netloc}"
    except Exception:
        return ""


def _safe_str(v: Any, max_len: int = 300) -> str:
    """
    Safe string for logs to avoid huge payloads + newlines.
    """
    try:
        s = str(v)
    except Exception:
        return "<unprintable>"
    s = s.replace("\n", "\\n").replace("\r", "\\r")
    if len(s) > max_len:
        s = s[:max_len] + "…"
    return s


def _make_req_id() -> str:
    return "wwc_" + secrets.token_hex(6)


def _log_ctx(req_id: Optional[str], **fields: Any) -> str:
    """
    Create a compact context string for logs.
    """
    parts = []
    if req_id:
        parts.append(f"rid={req_id}")
    for k, v in fields.items():
        if v is None:
            continue
        parts.append(f"{k}={_safe_str(v, 120)}")
    return " ".join(parts)


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

    def validate_origin(self, origin: str, *, req_id: Optional[str] = None) -> bool:
        """
        Return True if `origin` is allowed.

        Logs:
          - debug: canonicalized origin + match decision
          - warning: missing/invalid origin
        """
        if not origin:
            logger.warning("validate_origin: missing origin %s", _log_ctx(req_id))
            return False

        allowed = self.allowed_origins or DEFAULT_ALLOWED_ORIGINS
        o = _canon_origin(origin)

        if not o:
            logger.warning(
                "validate_origin: invalid origin=%r %s",
                _safe_str(origin),
                _log_ctx(req_id),
            )
            return False

        ok = any(o == a or o.startswith(a) for a in allowed)

        logger.debug(
            "validate_origin: origin=%s ok=%s allowed=%s %s",
            o,
            ok,
            len(allowed),
            _log_ctx(req_id),
        )
        return ok

    def is_chat_message(self, payload: Dict[str, Any], *, req_id: Optional[str] = None) -> bool:
        """
        Validate the inbound widget postMessage payload.

        Expected:
          { type: "chat:message", text: "..." }
        """
        if not isinstance(payload, dict):
            logger.debug(
                "is_chat_message: payload not dict type=%s %s",
                type(payload),
                _log_ctx(req_id),
            )
            return False

        t = payload.get("type")
        if t != "chat:message":
            logger.debug(
                "is_chat_message: wrong type=%r %s",
                _safe_str(t),
                _log_ctx(req_id),
            )
            return False

        text = payload.get("text")
        ok = isinstance(text, str) and len(text.strip()) > 0

        if not ok:
            logger.debug(
                "is_chat_message: empty/invalid text=%r %s",
                _safe_str(text),
                _log_ctx(req_id),
            )
        return ok

    def parse_chat_message(self, payload: Dict[str, Any], *, req_id: Optional[str] = None) -> Dict[str, Any]:
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

        if not isinstance(meta, dict):
            logger.debug(
                "parse_chat_message: metadata not dict type=%s %s",
                type(meta),
                _log_ctx(req_id),
            )
            meta = {}

        logger.debug(
            "parse_chat_message: session_id=%r tenant=%r text_len=%d meta_keys=%d %s",
            sess,
            tenant,
            len(text),
            len(meta.keys()),
            _log_ctx(req_id),
        )

        return {
            "message": text,
            "session_id": sess,
            "channel": "web",
            "tenant": tenant,
            "metadata": meta,
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
    try:
        text = (payload.get("message") or payload.get("text") or "")
        if not isinstance(text, str):
            return ""
        return text.strip()
    except Exception:
        return ""


def _extract_session_id(payload: Dict[str, Any], remote_addr: Optional[str]) -> str:
    """
    Use explicit session_id if provided, otherwise fall back to
    the old behaviour: "asa_<remote_addr>".
    """
    try:
        sess = payload.get("session_id") or payload.get("sessionId") or ""
        if not isinstance(sess, str):
            sess = ""
        sess = sess.strip()
    except Exception:
        sess = ""

    if not sess and remote_addr:
        sess = f"asa_{remote_addr}"

    return sess or "asa_anon"


def _extract_channel(payload: Dict[str, Any], default_channel: str) -> str:
    try:
        ch = payload.get("channel") or default_channel or "web"
        if not isinstance(ch, str):
            return "web"
        ch = ch.strip()
        return ch or "web"
    except Exception:
        return "web"


def _extract_tenant(payload: Dict[str, Any], default_tenant: Optional[str]) -> Optional[str]:
    try:
        t = payload.get("tenant") or default_tenant
        if t is None:
            return None
        if not isinstance(t, str):
            return default_tenant
        t = t.strip()
        return t or None
    except Exception:
        return default_tenant


def _extract_metadata(payload: Dict[str, Any]) -> Dict[str, Any]:
    meta = payload.get("metadata") or {}
    if not isinstance(meta, dict):
        return {}
    return meta


def parse_inbound(
    payload: Dict[str, Any],
    *,
    default_tenant: Optional[str] = None,
    default_channel: str = "web",
    remote_addr: Optional[str] = None,
    req_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Parse inbound web widget payload into a flat list of events.

    Adds robust logging so you can trace:
      - missing text
      - session_id derivation
      - tenant/channel parsing
      - metadata shape issues

    NOTE: `req_id` is optional. If not passed, we generate one for logs only.
    """
    rid = req_id or _make_req_id()
    events: List[Dict[str, Any]] = []

    if not isinstance(payload, dict):
        logger.warning(
            "parse_inbound: payload not dict type=%s %s",
            type(payload),
            _log_ctx(rid, remote_addr=remote_addr),
        )
        return events

    text = _extract_text(payload)
    if not text:
        logger.info(
            "parse_inbound: empty text message_keys=%s %s",
            list(payload.keys()),
            _log_ctx(rid, remote_addr=remote_addr),
        )
        return events

    session_id = _extract_session_id(payload, remote_addr)
    channel = _extract_channel(payload, default_channel)
    tenant = _extract_tenant(payload, default_tenant)
    metadata = _extract_metadata(payload)

    logger.info(
        "parse_inbound: ok session_id=%s channel=%s tenant=%s text_len=%d meta_keys=%d %s",
        session_id,
        channel,
        tenant,
        len(text),
        len(metadata.keys()),
        _log_ctx(rid, remote_addr=remote_addr),
    )

    # Keep raw payload, but DO NOT log it here (too noisy + may contain PII).
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
            "req_id": rid,  # helpful for correlating logs end-to-end
        }
    )

    return events


def send_reply(
    event: Dict[str, Any],
    reply: str,
    *,
    raw: Optional[Dict[str, Any]] = None,
    req_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build the JSON response that /chat_api should return.

    Returns:
      { "reply": str, "raw": {...}, "session_id": "asa_..." }

    Logging:
      - info: reply length + session_id
      - debug: raw keys count (NOT full raw)
    """
    rid = req_id or event.get("req_id") or _make_req_id()
    session_id = event.get("session_id") or "asa_anon"
    reply_str = str(reply or "")

    raw_out = raw or {}

    logger.info(
        "send_reply: session_id=%s reply_len=%d raw_keys=%d %s",
        session_id,
        len(reply_str),
        len(raw_out.keys()) if isinstance(raw_out, dict) else 0,
        _log_ctx(rid),
    )

    # never dump raw in logs by default
    logger.debug(
        "send_reply.debug: raw_type=%s %s",
        type(raw_out),
        _log_ctx(rid),
    )

    return {
        "reply": reply_str,
        "raw": raw_out,
        "session_id": session_id,
        "req_id": rid,  # optional but extremely useful for debugging
    }
