"""
Security utilities.

Provides:
- hash_password(plain) -> str
- check_password(plain, hashed) -> bool
- verify_webhook_signature(request, app_secret) -> bool   # used by WhatsApp webhook

Notes
-----
WhatsApp / Facebook Cloud API webhook signing:
- Header: X-Hub-Signature-256: "sha256=<hex digest>"
- Payload: raw request body
- Key: app_secret (from Meta app settings)

If WHATSAPP_APP_SECRET is empty, signature verification returns True
to avoid locking you out in dev. In prod, ALWAYS set the secret.
"""

from __future__ import annotations

import hmac
import hashlib
from typing import Optional

import bcrypt
from flask import Request


# ------------- Password hashing (for admin login, etc.) -------------


def hash_password(plain: str) -> str:
    """
    Hash a plaintext password using bcrypt.

    Returns a UTF-8 string safe to store in DB / env.
    """
    if not isinstance(plain, str):
        raise TypeError("Password must be a string")

    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(plain.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def check_password(plain: str, hashed: str) -> bool:
    """
    Compare plaintext password to stored bcrypt hash.
    """
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        # If the stored hash is malformed, treat as mismatch.
        return False


# ------------- Webhook signature verification (WhatsApp / Meta) -------------


def verify_webhook_signature(request: Request, app_secret: Optional[str]) -> bool:
    """
    Verify Meta / WhatsApp webhook signature.

    Meta spec:
      X-Hub-Signature-256: "sha256=<hex-digest>"
      digest = HMAC-SHA256(app_secret, raw_body)

    Returns True if:
      - app_secret is empty (dev mode), OR
      - header missing AND secret empty (dev), OR
      - computed digest matches header.
    """
    # If no secret configured, don't block requests (useful in dev / local)
    if not app_secret:
        return True

    header = request.headers.get("X-Hub-Signature-256", "")
    prefix = "sha256="
    if not header.startswith(prefix):
        # Missing or malformed signature
        return False

    received_sig = header[len(prefix) :].strip()
    if not received_sig:
        return False

    # Raw body; cache=True so Flask doesn't consume the stream
    body = request.get_data(cache=True) or b""

    computed = hmac.new(
        app_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()

    # Use constant-time comparison
    return hmac.compare_digest(received_sig, computed)
