"""
Security utilities.

Exports:
- hash_password(plain) -> str
- check_password(plain, hashed) -> bool
- verify_webhook_signature(request, app_secret) -> bool

Admin/Auth helpers:
- authenticate_user(container, email, password, totp_code=None) -> dict | None
- verify_totp(secret, code) -> bool
- require_bearer_or_session(container, request) -> dict
- ensure_roles(user, roles) -> None
"""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any, Dict, Iterable, Optional, Set

import bcrypt
import pyotp
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


# ---------------- TOTP ----------------

def verify_totp(secret: str | None, code: str | None) -> bool:
    """
    If secret is not set -> TOTP not required.
    """
    secret = (secret or "").strip()
    code = (code or "").strip()

    if not secret:
        return True
    if not code:
        return False

    try:
        totp = pyotp.TOTP(secret)
        return bool(totp.verify(code, valid_window=1))
    except Exception:
        return False


# ---------------- Admin login (browser form) ----------------

def authenticate_user(container: Any, email: str, password: str, totp_code: str | None = None) -> Dict[str, Any] | None:
    """
    Admin auth: checks email + password, and optional TOTP.

    Expected settings (any of these):
      - ADMIN_EMAIL
      - ADMIN_PASSWORD_HASH  (bcrypt hash)  [recommended]
      - ADMIN_PASSWORD       (plain fallback)
      - ADMIN_TOTP_SECRET    (optional)
    """
    s = getattr(container, "settings", None) or container

    admin_email = (getattr(s, "ADMIN_EMAIL", "") or "").strip().lower()
    if not admin_email:
        return None

    if (email or "").strip().lower() != admin_email:
        return None

    if not verify_totp(getattr(s, "ADMIN_TOTP_SECRET", None), totp_code):
        return None

    pw_hash = (getattr(s, "ADMIN_PASSWORD_HASH", "") or "").strip()
    pw_plain = (getattr(s, "ADMIN_PASSWORD", "") or "").strip()
    password = (password or "").strip()

    ok = False
    if pw_hash:
        try:
            ok = bcrypt.checkpw(password.encode("utf-8"), pw_hash.encode("utf-8"))
        except Exception:
            ok = False
    elif pw_plain:
        ok = hmac.compare_digest(password, pw_plain)

    if not ok:
        return None

    return {"email": admin_email, "role": "admin", "roles": ["admin"], "auth": "session"}


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


# ---------------- Bearer/session auth (API + admin pages) ----------------

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
      B) Logged-in session (session["user"])
    """
    token = _get_bearer_token(req)

    # 1) Bearer token path
    if token:
        expected = None
        try:
            expected = getattr(getattr(container, "settings", None), "ADMIN_BEARER_TOKEN", None)
        except Exception:
            expected = None
        expected = expected or os.getenv("ADMIN_BEARER_TOKEN") or os.getenv("BEARER_TOKEN")

        if expected and hmac.compare_digest(token, expected):
            return {"id": "bearer_admin", "role": "admin", "roles": ["admin"], "auth": "bearer"}
        abort(401)

    # 2) Session path
    user = session.get("user")
    if isinstance(user, dict) and (user.get("role") or user.get("roles") or user.get("email")):
        u = dict(user)
        if "roles" not in u:
            u["roles"] = [u.get("role")] if u.get("role") else []
        u.setdefault("auth", "session")
        return u

    abort(401)


def ensure_roles(user: Dict[str, Any], roles: Iterable[str]) -> None:
    required = {str(r).strip().lower() for r in (roles or []) if r and str(r).strip()}
    if not required:
        return

    have: Set[str] = set()
    if isinstance(user, dict):
        if user.get("role"):
            have.add(str(user["role"]).strip().lower())
        rs = user.get("roles") or []
        if isinstance(rs, (list, tuple, set)):
            have |= {str(x).strip().lower() for x in rs if x}

    if not (have & required):
        abort(403)
