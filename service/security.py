"""
Security utilities:
- Password hashing (bcrypt)
- TOTP setup/verify for 2FA
- RBAC helpers (roles, permissions)
- CSRF token helpers (HMAC over session)
- Webhook signature checks (generic HMAC utility)

These are framework-agnostic; routes/auth_routes.py wires them into Flask sessions.
"""

from __future__ import annotations
import base64
import hashlib
import hmac
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import bcrypt
import pyotp


# ---------- Passwords ----------

def hash_password(plain: str) -> str:
    if not isinstance(plain, str) or not plain:
        raise ValueError("Invalid password")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(plain.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ---------- TOTP (2FA) ----------

def generate_totp_secret() -> str:
    # Base32 seed
    return pyotp.random_base32()

def totp_uri(secret: str, username: str, issuer: str = "AI Sales Assistant") -> str:
    return pyotp.totp.TOTP(secret).provisioning_uri(name=username, issuer_name=issuer)

def verify_totp(secret: str, code: str, *, window: int = 1) -> bool:
    try:
        totp = pyotp.TOTP(secret)
        return bool(totp.verify(code, valid_window=window))
    except Exception:
        return False


# ---------- RBAC ----------

@dataclass(frozen=True)
class Role:
    name: str
    permissions: frozenset[str]

# default roles
ROLE_ADMIN = Role("admin", frozenset({"catalog:rw", "faq:rw", "analytics:r", "leads:rw", "users:rw"}))
ROLE_STAFF = Role("staff", frozenset({"catalog:r", "faq:r", "analytics:r", "leads:rw"}))
ROLE_VIEWER = Role("viewer", frozenset({"analytics:r"}))

def can(role: Role, permission: str) -> bool:
    return permission in role.permissions

def role_from_str(name: str) -> Role:
    n = (name or "").lower()
    if n == "admin":
        return ROLE_ADMIN
    if n == "staff":
        return ROLE_STAFF
    return ROLE_VIEWER


# ---------- CSRF (HMAC over session) ----------

def make_csrf_token(secret_key: str, session_id: str, ts: Optional[int] = None) -> str:
    ts = ts or int(time.time())
    msg = f"{session_id}.{ts}".encode("utf-8")
    sig = hmac.new(secret_key.encode("utf-8"), msg, hashlib.sha256).digest()
    return f"{ts}.{base64.urlsafe_b64encode(sig).decode('utf-8').rstrip('=')}"

def verify_csrf_token(secret_key: str, session_id: str, token: str, max_age: int = 3600) -> bool:
    try:
        ts_str, b64 = token.split(".", 1)
        ts = int(ts_str)
        if int(time.time()) - ts > max_age:
            return False
        expected = make_csrf_token(secret_key, session_id, ts)
        # constant time compare
        return hmac.compare_digest(expected, token)
    except Exception:
        return False


# ---------- Webhook signatures (generic HMAC utility) ----------

def verify_hmac_signature(secret: str, raw_body: bytes, provided_sig: str, algo: str = "sha256") -> bool:
    if not secret:
        return True  # allow if not configured
    try:
        digest = hmac.new(secret.encode("utf-8"), raw_body, getattr(hashlib, algo)).hexdigest()
        # Some providers prefix with "sha256="; normalize:
        if provided_sig.startswith("sha256="):
            provided_sig = provided_sig.split("=", 1)[1]
        return hmac.compare_digest(digest, provided_sig)
    except Exception:
        return False


# ---------- Login helpers (simple in-memory user store hook) ----------

@dataclass
class User:
    username: str
    password_hash: str
    role: Role
    totp_secret: Optional[str] = None

class UserStore:
    """
    Simple in-proc store. Replace with DB-backed provider if needed.
    """
    def __init__(self):
        self._by_name: Dict[str, User] = {}

    def add_user(self, username: str, password_plain: str, role: str = "admin", totp_secret: Optional[str] = None) -> User:
        u = User(username=username, password_hash=hash_password(password_plain), role=role_from_str(role), totp_secret=totp_secret)
        self._by_name[username] = u
        return u

    def get(self, username: str) -> Optional[User]:
        return self._by_name.get(username)

    def verify_login(self, username: str, password_plain: str, totp_code: Optional[str] = None) -> bool:
        u = self.get(username)
        if not u:
            return False
        if not verify_password(password_plain, u.password_hash):
            return False
        if u.totp_secret:
            if not (totp_code and verify_totp(u.totp_secret, totp_code)):
                return False
        return True
