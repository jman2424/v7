# service/security.py
import os
import hmac
import base64
import hashlib

def authenticate_user(username: str, password: str) -> bool:
    """
    Admin login check using env vars.
    """
    admin_user = os.getenv("ADMIN_USERNAME", "")
    admin_pass = os.getenv("ADMIN_PASSWORD", "")

    if not admin_user or not admin_pass:
        # Fail closed if env vars are missing
        return False

    return (
        hmac.compare_digest((username or "").strip(), admin_user)
        and hmac.compare_digest(password or "", admin_pass)
    )

def verify_totp(code: str) -> bool:
    """
    Optional TOTP check.
    If ADMIN_TOTP_SECRET is not set, treat TOTP as disabled and return True.
    """
    secret = os.getenv("ADMIN_TOTP_SECRET", "").strip()
    if not secret:
        return True  # TOTP disabled

    # Minimal TOTP (RFC 6238). Requires code to be 6 digits.
    try:
        code = (code or "").strip()
        if len(code) != 6 or not code.isdigit():
            return False

        # Decode base32 secret
        key = base64.b32decode(secret.upper() + "====", casefold=True)

        # Time step = 30s
        import time, struct
        timestep = int(time.time()) // 30
        msg = struct.pack(">Q", timestep)

        h = hmac.new(key, msg, hashlib.sha1).digest()
        o = h[-1] & 0x0F
        dbc = struct.unpack(">I", h[o:o+4])[0] & 0x7FFFFFFF
        otp = str(dbc % 1000000).zfill(6)

        return hmac.compare_digest(code, otp)
    except Exception:
        return False
