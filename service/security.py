# service/security.py
from __future__ import annotations

import hmac
import hashlib
import base64
from typing import Any, Optional


def verify_webhook_signature(
    auth_token: str,
    signature_header: str,
    full_url: str,
    form_data: dict[str, Any],
) -> bool:
    """
    Twilio request validation.

    signature_header: X-Twilio-Signature
    full_url: the exact URL Twilio requested (incl https + host + path, no querystring changes)
    form_data: request.form as a dict (all fields Twilio posted)

    Returns True if signature matches.
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


# Keep your existing functions below (authenticate_user, verify_totp, etc.)
# If they don't exist, tell me and I’ll write them too.
