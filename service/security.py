"""
Security utilities.

Exports:
- hash_password(plain) -> str
- check_password(plain, hashed) -> bool
- verify_webhook_signature(request, app_secret) -> bool

Admin/Auth helpers (what your routes are trying to import):
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

import hashlib
import hmac
import os
from typing import Any, Dict, Iterable, Optional

import bcrypt
from flask import Request, abort, session


# ---------------- Password hashing ----------------

def hash_password(plain: str) -> str:
    if not isinstance(plain, str):
        raise TypeError("Password must be a string")
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(plain.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def check_password(plain: str, hashed: str) -> bool:
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ---------------- Webhook signature verification (Meta / WhatsApp) ----------------

def verify_webhook_signature(request: Request, app_secret: Optional[str]) -> bool:
    if not app_secret:
        return True  # dev mode

    header = request.headers.get("X-Hub-Signature-256", "")
    prefix = "sha256="
    if not header.startswith(prefix):
        return False

    received_sig = header[len(prefix):].strip()
    if not received_sig:
        return False

    body = request.get_data(cache=True) or b""
    computed = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(received_sig, computed)


# ---------------- Admin auth + RBAC (THIS FIXES YOUR IMPORT ERROR) ----------------

def _get_bearer_token(req: Request) -> Optional[str]:
    auth = (req.headers.get("Authorization") or "").strip()
    if not auth:
        return None
    parts = auth.split(" ", 1)
    if len(parts) != 2:
        return None
    scheme, token = parts[0].strip().lower(), parts[1].strip()
    if scheme != "bearer" or not token:
        return None
    return token


def require_bearer_or_session(container: Any, req: Request) -> Dict[str, Any]:
    """
    Accepts either:
      A) Authorization: Bearer <token>
      B) Logged-in session (e.g., session["user"])

    Returns a user dict like:
      {"id": "...", "role": "admin", "roles": ["admin", ...], "auth": "bearer|session"}

    Customize token source:
    - simplest: ADMIN_BEARER_TOKEN env
    - optional: container.settings.ADMIN_BEARER_TOKEN if you store it there
    """
    token = _get_bearer_token(req)

    # 1) Bearer token path (recommended for admin JSON endpoints)
    if token:
        expected = None
        # try container.settings first, then env
        try:
            expected = getattr(getattr(container, "settings", None), "ADMIN_BEARER_TOKEN", None)
        except Exception:
            expected = None
        expected = expected or os.getenv("ADMIN_BEARER_TOKEN") or os.getenv("BEARER_TOKEN")

        if expected and hmac.compare_digest(token, expected):
            return {
                "id": "bearer_admin",
                "role": "admin",
                "roles": ["admin"],
                "auth": "bearer",
            }
        abort(401)

    # 2) Session path (for browser admin panel)
    user = session.get("user")
    if isinstance(user, dict) and (user.get("role") or user.get("roles")):
        u = dict(user)
        u.setdefault("roles", [u.get("role")] if u.get("role") else [])
        u["auth"] = "session"
        return u

    abort(401)


def ensure_roles(user: Dict[str, Any], roles: Iterable[str]) -> None:
    required = {r.strip().lower() for r in (roles or []) if r and str(r).strip()}
    if not required:
        return

    have = set()
    if isinstance(user, dict):
        if user.get("role"):
            have.add(str(user["role"]).lower())
        rs = user.get("roles") or []
        if isinstance(rs, (list, tuple, set)):
            have |= {str(x).lower() for x in rs if x}

    if not (have & required):
        abort(403)
