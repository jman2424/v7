# service/security.py
from __future__ import annotations

import os
import hmac
from typing import Any, Dict, Optional


def _get_admin_creds(container=None) -> tuple[str, str]:
    """
    Reads admin creds from (in order):
    1) container.settings.ADMIN_EMAIL / ADMIN_PASSWORD (if present)
    2) environment variables ADMIN_EMAIL / ADMIN_PASSWORD
    """
    admin_email = ""
    admin_password = ""

    if container is not None and hasattr(container, "settings"):
        s = container.settings
        admin_email = getattr(s, "ADMIN_EMAIL", "") or ""
        admin_password = getattr(s, "ADMIN_PASSWORD", "") or ""

    if not admin_email:
        admin_email = os.getenv("ADMIN_EMAIL", "") or ""
    if not admin_password:
        admin_password = os.getenv("ADMIN_PASSWORD", "") or ""

    return admin_email.strip().lower(), admin_password


def authenticate_user(container, email: str, password: str) -> Optional[Dict[str, Any]]:
    """
    Simple env-based auth.
    Returns a user dict on success, else None.
    """
    admin_email, admin_password = _get_admin_creds(container)

    email = (email or "").strip().lower()
    password = password or ""

    if not admin_email or not admin_password:
        # Misconfigured deployment: no admin creds set
        return None

    email_ok = hmac.compare_digest(email, admin_email)
    pass_ok = hmac.compare_digest(password, admin_password)

    if not (email_ok and pass_ok):
        return None

    return {
        "id": "admin",
        "email": admin_email,
        "roles": ["admin"],
        # if you later add totp, set "totp_secret" here
    }


def verify_totp(secret: str, code: str) -> bool:
    """
    Stub: return True if you are not using TOTP yet.
    If you do use TOTP, replace with pyotp validation.
    """
    return True
