# service/security.py
from __future__ import annotations

import os
import hmac
import hashlib
from typing import Any, Dict, Optional

from flask import request


# ----------------------------
# Admin authentication
# ----------------------------

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

    # If these are missing, login will always fail
    if not admin_email or not admin_password:
        return None

    email_ok = hmac.compare_digest(email, admin_email)
    pass_ok = hmac.compare_digest(password, admin_password)

    if not (email_ok and pass_ok):
        return None

    return {
        "id": "admin",
        "email": admin_email,
        "roles": ["admin"],
        # If you later add TOTP, store and return user["totp_secret"]
    }


def verify_totp(secret: str, code: str) -> bool:
    """
    Stub: if you're not using TOTP yet, always True.
    If you add TOTP, swap this for pyotp verification.
    """
    return True


# ----------------------------
# Webhook signature verification
# ----------------------------

def verify_webhook_signature(
    *,
    secret: str,
    body: bytes,
    signature: str,
    timestamp: str | None = None,
) -> bool:
    """
    Generic HMAC webhook verification.

    Many webhook providers use:
      signature = HMAC_SHA256(secret, body) (or body+timestamp)

    This function checks:
      HMAC_SHA256(secret, body) == signature
    and if timestamp provided:
      HMAC_SHA256(secret, timestamp + "." + body) == signature

    Because providers differ, we accept both styles.
    """
    if not secret or not signature:
        return False

    sig = signature.strip()

    # Option A: raw body
    mac1 = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    # Option B: timestamp + "." + body
    mac2 = None
    if timestamp:
        payload = (timestamp + ".").encode("utf-8") + body
        mac2 = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()

    return hmac.compare_digest(sig, mac1) or (mac2 is not None and hmac.compare_digest(sig, mac2))


def verify_twilio_request(container, full_url: str, form: dict[str, str], signature: str) -> bool:
    """
    If you are using Twilio WhatsApp webhooks, Twilio uses its own signature scheme.
    Ideally you'd use twilio.request_validator.RequestValidator.

    This provides a safe fallback if Twilio lib isn't present.

    If you already implemented Twilio validation elsewhere, keep using that.
    """
    # If you have Twilio installed, do the proper verification.
    try:
        from twilio.request_validator import RequestValidator  # type: ignore
    except Exception:
        return False

    token = ""
    if container is not None and hasattr(container, "settings"):
        token = getattr(container.settings, "TWILIO_AUTH_TOKEN", "") or ""
    if not token:
        token = os.getenv("TWILIO_AUTH_TOKEN", "") or ""

    if not token or not signature:
        return False

    validator = RequestValidator(token)
    return validator.validate(full_url, form, signature)


def verify_incoming_webhook(container) -> bool:
    """
    Convenience wrapper:
    - If your whatsapp_routes calls this: it will verify using TWILIO_AUTH_TOKEN.
    - Reads current request context.
    """
    # Twilio sends X-Twilio-Signature
    tw_sig = request.headers.get("X-Twilio-Signature", "") or ""
    if not tw_sig:
        return False

    # full URL Twilio expects must match what Twilio hits (including https)
    # Render sits behind proxy; Flask will see proxy headers.
    full_url = request.url

    # Twilio signs form-encoded body params
    form = {k: v for k, v in request.form.items()}
    c = container
    return verify_twilio_request(c, full_url, form, tw_sig)
