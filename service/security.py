# service/security.py
from __future__ import annotations

import os
import hmac
import base64
import hashlib
import secrets
from typing import Any, Dict, Optional

import bcrypt
import pyotp


_CSRF_SECRET_ENV = "CSRF_SECRET"


def _secret_bytes(secret: str | bytes) -> bytes:
    if isinstance(secret, bytes):
        return secret
    return str(secret or "").encode("utf-8")


def _app_secret() -> bytes:
    secret = os.getenv(_CSRF_SECRET_ENV) or os.getenv("SECRET_KEY") or "dev-csrf-secret"
    return secret.encode("utf-8")


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    raw = (password or "").encode("utf-8")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    try:
        return bcrypt.checkpw((password or "").encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def generate_totp_token(secret: str) -> str:
    return pyotp.TOTP(secret).now()


def verify_totp_token(secret: str, token: str, *, window: int = 0) -> bool:
    try:
        return bool(pyotp.TOTP(secret).verify(str(token or ""), valid_window=window))
    except Exception:
        return False


def sign_webhook(payload: bytes, secret: str | bytes) -> str:
    digest = hmac.new(_secret_bytes(secret), payload or b"", hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _verify_signed_payload(payload: bytes, signature_header: str, secret: str | bytes) -> bool:
    if not payload or not signature_header or not secret:
        return False

    expected = sign_webhook(payload, secret)
    candidates = [signature_header]
    if signature_header.startswith("sha256="):
        candidates.append(signature_header.removeprefix("sha256="))
    expected_raw = expected.removeprefix("sha256=")

    return any(
        hmac.compare_digest(candidate, expected)
        or hmac.compare_digest(candidate, expected_raw)
        for candidate in candidates
    )


def generate_csrf_token(session_id: str) -> str:
    nonce = secrets.token_urlsafe(16)
    sid = str(session_id or "")
    sig = hmac.new(_app_secret(), f"{sid}.{nonce}".encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{nonce}.{sig}"


def verify_csrf_token(session_id: str, token: str) -> bool:
    try:
        nonce, sig = str(token or "").rsplit(".", 1)
    except ValueError:
        return False

    sid = str(session_id or "")
    expected = hmac.new(_app_secret(), f"{sid}.{nonce}".encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


# -----------------------------
# 1) Twilio webhook signature
# -----------------------------
def verify_webhook_signature(*args: Any) -> bool:
    """
    Validate webhook signatures.

    Supported call shapes:
      - verify_webhook_signature(payload_bytes, signature_header, secret)
      - verify_webhook_signature(flask_request, app_secret) for Meta X-Hub-Signature-256
      - verify_webhook_signature(auth_token, signature_header, full_url, form_data) for Twilio
    """
    if len(args) == 3:
        payload, signature_header, secret = args
        if not isinstance(payload, (bytes, bytearray)):
            return False
        return _verify_signed_payload(bytes(payload), str(signature_header or ""), secret)

    if len(args) == 2:
        req, app_secret = args
        signature_header = ""
        try:
            signature_header = req.headers.get("X-Hub-Signature-256") or ""
            payload = req.get_data() or b""
        except Exception:
            return False
        return _verify_signed_payload(payload, signature_header, app_secret)

    if len(args) != 4:
        return False

    auth_token, signature_header, full_url, form_data = args
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
