from __future__ import annotations

import hmac
from typing import Iterable, Optional, Set, Dict, Any

import bcrypt
import pyotp
from flask import session


def _norm_roles(roles: Iterable[str]) -> Set[str]:
    return {str(r).strip().lower() for r in roles or []}


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


def authenticate_user(container, email: str, password: str, totp_code: str | None = None) -> Dict[str, Any] | None:
    """
    Admin auth: checks email + password (hash preferred), and optional TOTP.

    Expected settings (any of these):
      - ADMIN_EMAIL
      - ADMIN_PASSWORD_HASH  (bcrypt hash)  [recommended]
      - ADMIN_PASSWORD       (plain, fallback)
      - ADMIN_TOTP_SECRET    (optional)
    """
    s = container.settings

    admin_email = (getattr(s, "ADMIN_EMAIL", "") or "").strip().lower()
    if not admin_email:
        # If you forgot to set it, don't let anyone in.
        return None

    if (email or "").strip().lower() != admin_email:
        return None

    # TOTP check (only if secret set)
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

    return {"email": admin_email, "roles": ["admin"]}


def require_bearer_or_session(container, req) -> Dict[str, Any]:
    """
    Used by your require_auth() helper.

    Accepts:
      - session["user"] (browser)
      - Authorization: Bearer <ADMIN_BEARER_TOKEN> (API)
    """
    # 1) Browser session
    user = session.get("user")
    if isinstance(user, dict) and user.get("email"):
        return user

    # 2) Bearer token
    auth = (req.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
        expected = (getattr(container.settings, "ADMIN_BEARER_TOKEN", "") or "").strip()
        if expected and hmac.compare_digest(token, expected):
            return {"email": "api-admin", "roles": ["admin"]}

    raise PermissionError("unauthorized")


def ensure_roles(user: Dict[str, Any], required_roles: Iterable[str]) -> None:
    required = _norm_roles(required_roles)
    if not required:
        return

    have = _norm_roles(user.get("roles", []))
    if not (have & required):
        raise PermissionError("forbidden")
