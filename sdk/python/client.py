"""
AI Sales Assistant — Python Client

Purpose:
- Simple wrapper around /chat_api and selected admin JSON endpoints.
- Stateless by default; you can pass session_id to maintain short-term context.

Dependencies:
- requests

Typical usage:
    from aisales_assistant_client import AssistantClient
    c = AssistantClient(base_url="https://your-app.example.com", tenant="EXAMPLE")
    r = c.send_message("What are your hours today?", session_id="asa_123")
    print(r["reply"])
"""

from __future__ import annotations
import time
import uuid
from typing import Any, Dict, Optional
import requests


class AssistantClient:
    def __init__(
        self,
        base_url: str,
        tenant: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 10.0,
    ) -> None:
        """
        :param base_url: Server root (e.g., https://your-app.example.com)
        :param tenant: Optional business key (maps to business/{KEY}/)
        :param api_key: Optional admin/API token if your routes require it
        :param timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.tenant = tenant
        self.api_key = api_key
        self.timeout = timeout
        self._session = requests.Session()

    # -------- Chat --------
    def send_message(
        self,
        message: str,
        session_id: Optional[str] = None,
        channel: str = "web",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Send a message to /chat_api and return JSON.
        Server is expected to respond with: { reply: str, raw?: any }
        """
        url = f"{self.base_url}/chat_api"
        payload = {
            "message": message,
            "session_id": session_id or self._new_session_id(),
            "channel": channel,
            "tenant": self.tenant,
            "metadata": metadata or {},
        }
        headers = self._headers()
        t0 = time.time()
        resp = self._session.post(url, json=payload, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        out = resp.json()
        out["_latency_ms"] = round((time.time() - t0) * 1000, 2)
        return out

    # -------- Admin (examples; adapt to your admin routes) --------
    def get_leads(self, limit: int = 50) -> Dict[str, Any]:
        """
        Example: fetch leads for dashboard (if you expose /admin/api/leads).
        """
        url = f"{self.base_url}/admin/api/leads"
        params = {"tenant": self.tenant, "limit": limit}
        headers = self._headers()
        resp = self._session.get(url, params=params, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def put_catalog(self, catalog_json: Dict[str, Any]) -> Dict[str, Any]:
        """
        Example: upload catalog via admin files API (if you expose /admin/api/catalog).
        """
        url = f"{self.base_url}/admin/api/catalog"
        headers = self._headers()
        resp = self._session.put(url, json={"tenant": self.tenant, "catalog": catalog_json}, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    # -------- Helpers --------
    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    @staticmethod
    def _new_session_id() -> str:
        return f"asa_{uuid.uuid4().hex[:8]}{int(time.time())}"
