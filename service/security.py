"""
Security utilities.

Provides:
- hash_password(plain) -> str
- check_password(plain, hashed) -> bool
- verify_webhook_signature(request, app_secret) -> bool   # used by WhatsApp webhook

Admin auth helpers (so routes don't crash):
- require_bearer_or_session(container, request) -> dict
- ensure_roles(user, roles) -> None

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
from typing import Optional, Iterable, Any, Dict

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
        return False


# ------------- Webhook signature verification (WhatsApp / Meta) -------------


def verify_webhook_signature(request: Request, app_secret: Optional[str]) -> bool:
    """
    Verify Meta / WhatsApp webhook signature.

    Meta spec:
      X-Hub-Signature-256: "sha256=<hex-digest>"
      digest = HMAC-SHA256(app_secret, raw_body)
    """
    # dev-mode bypass
    if not app_secret:
        return True

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


# ------------- Admin auth helpers (fix your ImportError) -------------


def _extract_bearer_token(req: Request) -> str:
    auth = (req.headers.get("Authorization") or "").strip()
    if not auth.lower().startswith("bearer "):
        return ""
    return auth.split(" ", 1)[1].strip()


def require_bearer_or_session(container: Any, req: Request) -> Dict[str, Any]:
    """
    Returns a user-like dict if authorized, otherwise raises a 401 via exception upstream.

    Supports:
    - Bearer token: Authorization: Bearer <token>
      Token is validated by container.auth if present, otherwise falls back to env token.
    - Session auth: if you later add it, container.auth may also support it.
    """
    token = _extract_bearer_token(req)

    # 1) Preferred: container.auth service (if you have one)
    auth_svc = getattr(container, "auth", None)
    if auth_svc:
        # Common patterns: validate_bearer / verify_token / authenticate_request
        for fn_name in ("validate_bearer", "verify_token", "authenticate_request"):
            fn = getattr(auth_svc, fn_name, None)
            if callable(fn):
                user = fn(token=token, request=req)  # type: ignore
                if user:
                    return user  # expected dict-like

    # 2) Fallback: simple env-token check (fast unblock)
    # Set ADMIN_BEARER_TOKEN in Render env vars
    import os
    expected = (os.getenv("ADMIN_BEARER_TOKEN") or "").strip()
    if expected and token and hmac.compare_digest(token, expected):
        return {"id": "bearer", "role": "admin", "roles": ["admin"]}

    # 3) No auth matched
    raise PermissionError("Unauthorized")


def ensure_roles(user: Dict[str, Any], roles: Iterable[str]) -> None:
    """
    Ensures user has at least one of the allowed roles.
    Raises PermissionError if not allowed.
    """
    allowed = set([r.strip().lower() for r in roles if r])
    if not allowed:
        return

    # Accept either `role` (string) or `roles` (list)
    user_role = str(user.get("role") or "").strip().lower()
    user_roles = user.get("roles") or []
    if isinstance(user_roles, str):
        user_roles = [user_roles]
    user_roles = set([str(r).strip().lower() for r in user_roles if r])

    if user_role in allowed or (user_roles & allowed):
        return

    raise PermissionError("Forbidden")
