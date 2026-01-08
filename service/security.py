# service/security.py
from __future__ import annotations

import os
import hmac
import base64
import hashlib
from typing import Any, Dict


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
    Twilio request validation.

    signature_header: X-Twilio-Signature
    full_url: exact URL Twilio requested (incl https + host + path, no querystring changes)
    form_data: request.form as a dict (all fields Twilio posted)
    """
    if not auth_token or not signature_header or not full_url:
        return False

    # Build the signed string: URL + sorted params concatenated as key+value
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
# 2) Admin username/password
# -----------------------------
def authenticate_user(username: str, password: str) -> bool:
    """
    Admin login check using env vars.
    """
    admin_user = os.getenv("ADMIN_USERNAME", "")
    admin_pass = os.getenv("ADMIN_PASSWORD", "")

    if not admin_user or not admin_pass:
        return False

    return (
        hmac.compare_digest((username or "").strip(), admin_user)
        and hmac.compare_digest(password or "", admin_pass)
    )


# -----------------------------
# 3) Optional TOTP (2FA)
# -----------------------------
def verify_totp(code: str) -> bool:
    """
    If ADMIN_TOTP_SECRET is not set, TOTP is disabled and returns True.
    Otherwise validates a 6-digit TOTP code.
    """
    secret = os.getenv("ADMIN_TOTP_SECRET", "").strip()
    if not secret:
        return True  # TOTP disabled

    code = (code or "").strip()
    if len(code) != 6 or not code.isdigit():
        return False

    try:
        # Decode base32 secret
        key = base64.b32decode(secret.upper() + "====", casefold=True)

        # Time step = 30s
        import time, struct
        timestep = int(time.time()) // 30
        msg = struct.pack(">Q", timestep)

        h = hmac.new(key, msg, hashlib.sha1).digest()
        o = h[-1] & 0x0F
        dbc = struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF
        otp = str(dbc % 1000000).zfill(6)

        return hmac.compare_digest(code, otp)
    except Exception:
        return False
