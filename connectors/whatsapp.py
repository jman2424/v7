"""
WhatsApp connector.

Responsibilities:
- Verify webhook signatures
- Parse inbound message payloads into canonical format
- Send outbound messages (text only, easily extensible)
- Handle transient errors & limited retries
- Support both sandbox and production tokens

Env vars expected:
  WA_VERIFY_TOKEN
  WA_ACCESS_TOKEN
  WA_API_BASE (e.g. "https://graph.facebook.com/v20.0/")
  WA_PHONE_ID
"""

from __future__ import annotations
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import urllib.request


def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


@dataclass
class WhatsAppClient:
    verify_token: str
    access_token: str
    api_base: str
    phone_id: str
    max_retries: int = 2

    # -------- factory --------
    @classmethod
    def from_env(cls) -> "WhatsAppClient":
        return cls(
            verify_token=os.getenv("WA_VERIFY_TOKEN", ""),
            access_token=os.getenv("WA_ACCESS_TOKEN", ""),
            api_base=os.getenv("WA_API_BASE", "https://graph.facebook.com/v20.0/"),
            phone_id=os.getenv("WA_PHONE_ID", ""),
        )

    # -------- verification --------
    def verify_challenge(self, params: Dict[str, str]) -> Optional[str]:
        """
        Handles GET verification from Meta webhook setup.
        Returns challenge string if token matches.
        """
        token = params.get("hub.verify_token")
        if token == self.verify_token:
            return params.get("hub.challenge")
        return None

    # -------- inbound parse --------
    def parse_inbound(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Convert raw Meta payload into normalized message dict:
        { "from": "+44...", "text": "hi", "timestamp": 1690000000, "id": "wamid.xxx" }
        """
        try:
            entry = payload["entry"][0]
            changes = entry["changes"][0]
            msg = changes["value"]["messages"][0]
            return {
                "from": msg["from"],
                "text": msg.get("text", {}).get("body", ""),
                "timestamp": int(msg.get("timestamp", time.time())),
                "id": msg.get("id"),
            }
        except Exception:
            return None

    # -------- send --------
    def send_text(self, to: str, text: str) -> bool:
        """
        POSTs to /{PHONE_ID}/messages
        """
        url = f"{self.api_base.rstrip('/')}/{self.phone_id}/messages"
        body = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text},
        }
        data = _json(body).encode("utf-8")
        for attempt in range(1, self.max_retries + 1):
            try:
                req = urllib.request.Request(url, data=data, headers=_headers(self.access_token))
                with urllib.request.urlopen(req, timeout=8) as r:
                    if 200 <= r.status < 300:
                        return True
            except Exception:
                if attempt == self.max_retries:
                    raise
                time.sleep(0.5 * attempt)
        return False

    # -------- utility --------
    def verify_signature(self, body: bytes, header_signature: str, app_secret: Optional[str]) -> bool:
        """
        Meta optional HMAC-SHA256 signature verification.
        """
        if not header_signature or not app_secret:
            return True  # skip if not configured
        try:
            expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
            return hmac.compare_digest(expected, header_signature)
        except Exception:
            return False
