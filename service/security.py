# service/security.py
from __future__ import annotations

import os
import hmac
import base64
import hashlib
from typing import Any, Dict, Optional


# -----------------------------
# 1) Twilio webhook signature
# -----------------------------
def verify_webhook_signature(
    auth_token: str,
    signature_header: str,
    full_url: str,
    form_data: Dict[str, Any],
) -> bool:
    """
    Validate Twilio webhook signature.

    signature_header: value of X-Twilio-Signature header
    full_url: exact URL Twilio requested (scheme + host + path must match)
    form_data: request.form as a dict (all fields Twilio posted)
    """
    if not auth_token or not signature_header or not full_url:
        return False

    # Twilio signs: full_url + concatenated sorted params (key + value)
    items = sorted((k, str(v)) for k, v in (form_data or {}).items())
    payload = full_url + "".join(k + v for k, v in items)

    digest = hmac.new(
        auth_token.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha1,
    ).digest()

    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, signature_header)


# -----------------------------
# 2) Admin auth (env-based)
# -----------------------------
def authenticate_user(
    c: Any = None, *, email: str = "", password: str = ""
) -> Optional[Dict[str, Any]]:
    """
    Dashboard login.

    Matches routes/admin_routes.py:
        user = authenticate_user(c, email=email, password=password)

    Returns:
        - user dict (with id/email/roles/totp_secret) if valid
        - None if invalid
    """
    admin_user = (os.getenv("ADMIN_USERNAME") or "").strip().lower()
    admin_pass = os.getenv("ADMIN_PASSWORD") or ""

    if not admin_user or not admin_pass:
        # Fail closed if env vars missing
        return None

    email_norm = (email or "").strip().lower()
    password_norm = password or ""

    if not (
        hmac.compare_digest(email_norm, admin_user)
        and hmac.compare_digest(password_norm, admin_pass)
    ):
        return None

    # Optional 2FA: if set, login route will require a totp code
    totp_secret = (os.getenv("ADMIN_TOTP_SECRET") or "").strip() or None

    return {
        "id": "admin",
        "email": admin_user,
        "roles": ["admin"],
        "totp_secret": totp_secret,
    }


# -----------------------------
# 3) TOTP verify (secret + code)
# -----------------------------
def verify_totp(secret: str, code: str) -> bool:
    """
    Validate a 6-digit TOTP.

    Matches routes/admin_routes.py:
        verify_totp(user["totp_secret"], totp)

    secret: base32 encoded secret
    code: 6 digit code from authenticator app
    """
    secret = (secret or "").strip()
    code = (code or "").strip()

    if not secret:
        return True  # If no secret, treat as not required

    if len(code) != 6 or not code.isdigit():
        return False

    try:
        # Decode base32 secret
        key = base64.b32decode(secret.upper() + "====", casefold=True)

        # Time step = 30 seconds
        import time
        import struct

        timestep = int(time.time()) // 30
        msg = struct.pack(">Q", timestep)

        h = hmac.new(key, msg, hashlib.sha1).digest()
        offset = h[-1] & 0x0F
        dbc = struct.unpack(">I", h[offset : offset + 4])[0] & 0x7FFFFFFF
        otp = str(dbc % 1000000).zfill(6)

        return hmac.compare_digest(code, otp)
    except Exception:
        return False
