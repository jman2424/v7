"""
Security utilities.

Provides:
- hash_password(plain) -> str
- check_password(plain, hashed) -> bool
- verify_webhook_signature(request, app_secret) -> bool
- require_bearer_or_session(...)
- ensure_roles(...)

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

import os
import hmac
import hashlib
import secrets
from typing import Optional, Iterable, Tuple

import bcrypt
from flask import Request, request, session, abort


# =========================================================
# Password hashing (admin login, etc.)
# =========================================================

def hash_password(plain: str) -> str:
    """Hash a plaintext password using bcrypt."""
    if not isinstance(plain, str):
        raise TypeError("Password must be a string")

    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(plain.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def check_password(plain: str, hashed: str) -> bool:
    """Compare plaintext password to stored bcrypt hash."""
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# =========================================================
# WhatsApp / Meta webhook signature verification
# =========================================================

def verify_webhook_signature(request: Request, app_secret: Optional[str]) -> bool:
    """
    Verify Meta / WhatsApp webhook signature.

    Header: X-Hub-Signature-256: "sha256=<hex-digest>"
    Digest: HMAC-SHA256(app_secret, raw_body)
    """
    if not app_secret:
        return True  # dev-safe

    header = request.headers.get("X-Hub-Signature-256", "")
    prefix = "sha256="
    if not header.startswith(prefix):
        return False

    received_sig = header[len(prefix):].strip()
    if not received_sig:
        return False

    body = request.get_data(cache=True) or b""

    computed = hmac.new(
        app_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(received_sig, computed)


# =========================================================
# Admin / Dashboard security
# =========================================================

def _parse_bearer_token(auth_header: str) -> str:
    """
    Parse:
      Authorization: Bearer <token>
    """
    if not auth_header:
        return ""
    parts = auth_header.strip().split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return ""


def require_bearer_or_session(
    *,
    allowed_roles: Optional[Iterable[str]] = None,
    session_user_key: str = "user",
    session_role_key: str = "role",
    env_token_key: str = "ADMIN_BEARER_TOKEN",
) -> Tuple[bool, str]:
    """
    Allow access if:
    1) Valid Flask session exists, OR
    2) Bearer token matches ADMIN_BEARER_TOKEN env var

    Returns: (ok, reason)
    """

    allowed = {r.lower() for r in (allowed_roles or [])}

    # ---- 1. Session auth ----
    user = session.get(session_user_key)
    role = (session.get(session_role_key) or "").lower()

    if user:
        if not allowed or role in allowed:
            return True, "session_ok"
        return False, "role_not_allowed"

    # ---- 2. Bearer token auth ----
    expected = (os.getenv(env_token_key) or "").strip()
    auth_header = request.headers.get("Authorization", "")
    token = _parse_bearer_token(auth_header)

    if expected and token and secrets.compare_digest(token, expected):
        return True, "bearer_ok"

    return False, "unauthorized"


def ensure_roles(role: Optional[str], allowed_roles: Iterable[str]) -> bool:
    """
    Simple role check.
    """
    if not allowed_roles:
        return True
    return (role or "").lower() in {r.lower() for r in allowed_roles}


# =========================================================
# Optional decorator (nice to have)
# =========================================================

def require_admin(*roles: str):
    """
    Optional decorator for admin routes.
    """
    def decorator(fn):
        def wrapper(*args, **kwargs):
            ok, _ = require_bearer_or_session(allowed_roles=roles)
            if not ok:
                abort(401)
            return fn(*args, **kwargs)
        wrapper.__name__ = fn.__name__
        return wrapper
    return decorator
