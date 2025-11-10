"""
Billing connector (Stripe / Paddle).

Responsibilities:
- Create checkout sessions for subscriptions
- Verify and parse webhook events (invoice paid/failed, subscription changes)
- Maintain a per-tenant in-proc status cache that higher layers can persist

Env (Stripe):
  BILLING_PROVIDER=stripe
  STRIPE_API_KEY=sk_...
  STRIPE_WEBHOOK_SECRET=whsec_...
  STRIPE_API_BASE=https://api.stripe.com

Env (Paddle):
  BILLING_PROVIDER=paddle
  PADDLE_API_KEY=...
  PADDLE_WEBHOOK_SECRET=...        (shared secret for HMAC)
  PADDLE_API_BASE=https://api.paddle.com

Notes:
- We keep dependencies minimal (urllib + stdlib).
- Persistence of tenant status is left to services; we expose get/set and emit normalized events.
"""

from __future__ import annotations
import hmac
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple
import urllib.parse
import urllib.request
import urllib.error


JsonDict = Dict[str, Any]


def _json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _post(url: str, headers: Dict[str, str], body: Dict[str, Any], timeout: float = 10.0) -> JsonDict:
    req = urllib.request.Request(url, data=_json_bytes(body), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        return json.loads(data.decode("utf-8"))


@dataclass
class BillingClient:
    provider: str
    api_key: str
    api_base: str
    webhook_secret: Optional[str] = None

    # in-proc status cache; services/admin can persist
    _tenant_status: Dict[str, str] = field(default_factory=dict)

    # ------------- factory -------------

    @classmethod
    def from_env(cls) -> "BillingClient":
        provider = (os.getenv("BILLING_PROVIDER") or "stripe").strip().lower()
        if provider == "paddle":
            return cls(
                provider="paddle",
                api_key=os.getenv("PADDLE_API_KEY", ""),
                api_base=os.getenv("PADDLE_API_BASE", "https://api.paddle.com"),
                webhook_secret=os.getenv("PADDLE_WEBHOOK_SECRET"),
            )
        # default: stripe
        return cls(
            provider="stripe",
            api_key=os.getenv("STRIPE_API_KEY", ""),
            api_base=os.getenv("STRIPE_API_BASE", "https://api.stripe.com"),
            webhook_secret=os.getenv("STRIPE_WEBHOOK_SECRET"),
        )

    # ------------- public API -------------

    def create_checkout_session(
        self,
        *,
        tenant: str,
        customer_email: str,
        plan_id: str,
        success_url: str,
        cancel_url: str,
        metadata: Optional[JsonDict] = None,
    ) -> JsonDict:
        """
        Returns:
          { "id": "...", "url": "https://..." }
        """
        if self.provider == "stripe":
            return self._stripe_checkout(
                tenant=tenant,
                email=customer_email,
                price_id=plan_id,
                success_url=success_url,
                cancel_url=cancel_url,
                metadata=metadata or {},
            )
        elif self.provider == "paddle":
            return self._paddle_checkout(
                tenant=tenant,
                email=customer_email,
                price_id=plan_id,
                success_url=success_url,
                cancel_url=cancel_url,
                metadata=metadata or {},
            )
        raise RuntimeError(f"Unsupported provider: {self.provider}")

    def verify_webhook(self, headers: Dict[str, str], body: bytes) -> bool:
        """
        Provider-specific signature verification.
        """
        if self.provider == "stripe":
            sig = headers.get("Stripe-Signature") or ""
            return self._verify_stripe(sig, body)
        elif self.provider == "paddle":
            sig = headers.get("Paddle-Signature") or headers.get("Paddle-Signature-V2") or ""
            return self._verify_paddle(sig, body)
        return False

    def parse_webhook(self, headers: Dict[str, str], body: bytes) -> Optional[JsonDict]:
        """
        Normalize webhook to:
        {
          "provider": "stripe"|"paddle",
          "type": "invoice.paid"|"invoice.payment_failed"|"subscription.canceled"|...,
          "tenant": "...",
          "customer_email": "...",
          "raw": {...}
        }
        """
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            return None

        if self.provider == "stripe":
            typ = payload.get("type") or ""
            obj = payload.get("data", {}).get("object", {})
            md = obj.get("metadata") or {}
            return {
                "provider": "stripe",
                "type": str(typ),
                "tenant": md.get("tenant") or md.get("business_key") or "",
                "customer_email": obj.get("customer_email") or obj.get("customer_details", {}).get("email"),
                "raw": payload,
            }

        if self.provider == "paddle":
            # Paddle v2 style events: payload["event_type"], payload["data"]
            typ = payload.get("event_type") or payload.get("type") or ""
            data = payload.get("data") or payload
            md = data.get("metadata") or {}
            # Customer email: try data.customer.email or top-level "email"
            email = None
            cust = data.get("customer") or {}
            if isinstance(cust, dict):
                email = cust.get("email")
            email = email or data.get("email")
            return {
                "provider": "paddle",
                "type": str(typ),
                "tenant": md.get("tenant") or md.get("business_key") or "",
                "customer_email": email,
                "raw": payload,
            }

        return None

    def handle_webhook(self, headers: Dict[str, str], body: bytes) -> Tuple[bool, Optional[JsonDict]]:
        """
        Verify, parse, and (optionally) update in-proc subscription status.
        Returns (ok, normalized_event_or_none)
        """
        if not self.verify_webhook(headers, body):
            return False, None
        evt = self.parse_webhook(headers, body)
        if not evt:
            return False, None

        tenant = evt.get("tenant") or ""
        et = evt.get("type", "")

        # naive mapping for status cache
        if any(k in et for k in ("invoice.paid", "payment_succeeded", "subscription_activated", "subscription.created")):
            self.set_tenant_status(tenant, "active")
        elif any(k in et for k in ("payment_failed", "invoice.payment_failed")):
            self.set_tenant_status(tenant, "past_due")
        elif any(k in et for k in ("subscription.canceled", "subscription_paused", "subscription.deleted", "subscription.cancelled")):
            self.set_tenant_status(tenant, "canceled")

        return True, evt

    # ------------- status cache -------------

    def get_tenant_status(self, tenant: str) -> str:
        """
        Returns 'active' | 'past_due' | 'canceled' | '' (unknown)
        """
        return self._tenant_status.get(tenant, "")

    def set_tenant_status(self, tenant: str, status: str) -> None:
        if tenant:
            self._tenant_status[tenant] = status

    # ------------- Stripe -------------

    def _stripe_checkout(
        self,
        *,
        tenant: str,
        email: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
        metadata: JsonDict,
    ) -> JsonDict:
        """
        Creates a Checkout Session (mode=subscription).
        Returns {id, url}
        """
        url = f"{self.api_base.rstrip('/')}/v1/checkout/sessions"
        # Stripe expects application/x-www-form-urlencoded; but JSON works if proxied.
        # We’ll build form-encoded to be compatible with direct API.
        data = {
            "mode": "subscription",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "customer_email": email,
            "line_items[0][price]": price_id,
            "line_items[0][quantity]": "1",
            "metadata[tenant]": tenant,
        }
        encoded = urllib.parse.urlencode(data).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=encoded,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            out = json.loads(resp.read().decode("utf-8"))
            return {"id": out.get("id"), "url": out.get("url")}

    def _verify_stripe(self, signature_header: str, body: bytes) -> bool:
        """
        Stripe signature: t=timestamp, v1=HMAC_SHA256(secret, "{t}.{payload}")
        We implement the common v1 case. If header missing, accept only if secret not set.
        """
        secret = self.webhook_secret
        if not secret:
            return True
        try:
            parts = dict(item.split("=", 1) for item in signature_header.split(","))
            ts = parts.get("t")
            v1 = parts.get("v1")
            if not ts or not v1:
                return False
            signed = f"{ts}.{body.decode('utf-8')}".encode("utf-8")
            digest = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
            # optional: reject stale timestamps (e.g., >5 minutes)
            if abs(time.time() - float(ts)) > 300:
                return False
            return hmac.compare_digest(digest, v1)
        except Exception:
            return False

    # ------------- Paddle -------------

    def _paddle_checkout(
        self,
        *,
        tenant: str,
        email: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
        metadata: JsonDict,
    ) -> JsonDict:
        """
        Create a Paddle checkout link. API shapes vary by account version;
        we target a generic endpoint:
          POST /v2/checkout
          Body: {customer_email, price_id, success_url, cancel_url, metadata:{tenant}}
        Your Paddle proxy can map this to the right API call.
        """
        url = f"{self.api_base.rstrip('/')}/v2/checkout"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        body = {
            "customer_email": email,
            "price_id": price_id,
            "success_url": success_url,
            "cancel_url": cancel_url,
            "metadata": {"tenant": tenant, **(metadata or {})},
        }
        try:
            out = _post(url, headers, body)
            return {"id": out.get("id") or out.get("checkout_id"), "url": out.get("url") or out.get("checkout_url")}
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Paddle checkout failed: {e.code}") from e

    def _verify_paddle(self, signature_header: str, body: bytes) -> bool:
        """
        Simple HMAC verification. Some Paddle setups sign the raw body (or a timestamp + body).
        Here we support raw-body HMAC-SHA256 with shared secret.
        """
        secret = self.webhook_secret
        if not secret:
            return True
        try:
            expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
            return hmac.compare_digest(expected, signature_header)
        except Exception:
            return False
