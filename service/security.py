"""Authentication, management permissions and webhook verification."""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import secrets
import struct
import time
from functools import wraps
from pathlib import Path
from typing import Any, Dict, Optional

from flask import abort, current_app, session
from werkzeug.security import check_password_hash

from service import session_store

_TENANT_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_MANAGEMENT_ROLES = {"admin", "platform_admin", "business_owner"}


def _revision(identity):
    """Changing/removing/disabling credentials immediately invalidates sessions."""
    c = getattr(current_app, "container", None)
    try:
        records = _registry_users(c)
    except (OSError, ValueError, TypeError):
        return None
    email = identity.get("email")
    matches = [r for r in records if str(r.get("email", "")).strip().lower() == email]
    if matches:
        if len(matches) != 1 or matches[0].get("disabled"):
            return None
        data = matches[0]
    elif identity.get("id") == "admin" and email == os.getenv("ADMIN_USERNAME", "").strip().lower():
        data = {key: os.getenv(key, "") for key in ("ADMIN_USERNAME", "ADMIN_PASSWORD", "ADMIN_PASSWORD_HASH", "ADMIN_TOTP_SECRET")}
        if not data["ADMIN_PASSWORD"] and not data["ADMIN_PASSWORD_HASH"]:
            return None
    else:
        return None
    return hmac.new(current_app.secret_key.encode(), json.dumps(data, sort_keys=True).encode(), hashlib.sha256).hexdigest()


def verify_webhook_signature(
    auth_token: str,
    signature_header: str,
    full_url: str,
    form_data: Dict[str, Any],
) -> bool:
    """Validate the signature on a Twilio form webhook."""
    if not auth_token or not signature_header or not full_url:
        return False
    items = sorted((k, str(v)) for k, v in (form_data or {}).items())
    payload = full_url + "".join(k + v for k, v in items)
    digest = hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), signature_header)


def _verify_password(password: str, password_hash: str) -> bool:
    # Use Werkzeug's maintained password hashing implementation, already required
    # by Flask. Reject plaintext and unbounded client password input.
    if not password or len(password) > 1024 or not password_hash.startswith("scrypt:"):
        return False
    try:
        return check_password_hash(password_hash, password)
    except (ValueError, TypeError):
        return False


def _registry_users(c: Any) -> list[dict[str, Any]]:
    registry = (os.getenv("ADMIN_USERS_FILE") or "").strip()
    if not registry:
        return []
    path = Path(registry).expanduser().resolve()
    repo = Path(__file__).resolve().parents[1]
    protected_roots = [repo / "business", repo / "dashboard", Path.cwd() / "business"]
    storage = getattr(c, "storage", None)
    if storage is not None:
        protected_roots.append(Path(storage.business_root))
    # A tenant upload or public static asset must never become a credential file.
    if any(path.is_relative_to(root.resolve()) for root in protected_roots):
        raise ValueError("ADMIN_USERS_FILE must be outside business and dashboard directories")
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict) or not isinstance(payload.get("users"), list):
        raise ValueError("ADMIN_USERS_FILE must contain a users list")
    users = payload["users"]
    if not all(isinstance(user, dict) for user in users):
        raise ValueError("Invalid account record")
    return users


def authenticate_user(
    c: Any = None, *, email: str = "", password: str = ""
) -> Optional[Dict[str, Any]]:
    """Authenticate a server-configured account; never take role/tenant from input."""
    if not isinstance(email, str) or not isinstance(password, str):
        return None
    email_norm = email.strip().lower()
    if not email_norm or len(email_norm) > 254 or not password or len(password) > 1024:
        return None

    try:
        users = _registry_users(c)
    except (OSError, ValueError, TypeError):
        # A broken configured registry fails closed, including the environment account.
        return None

    matches = [u for u in users if str(u.get("email", "")).strip().lower() == email_norm]
    if matches:
        if len(matches) != 1:
            return None
        record = matches[0]
        role = record.get("role")
        tenant = record.get("tenant")
        password_hash = record.get("password_hash")
        if record.get("disabled") or role not in _MANAGEMENT_ROLES:
            return None
        if role == "business_owner" and (
            not isinstance(tenant, str) or not _TENANT_KEY.fullmatch(tenant)
        ):
            return None
        if not isinstance(password_hash, str) or not _verify_password(password, password_hash):
            return None
        secret = record.get("totp_secret") or ""
        if not isinstance(secret, str):
            return None
        return {
            "id": email_norm,
            "email": email_norm,
            "roles": [role],
            "tenant": tenant if role == "business_owner" else None,
            "totp_secret": secret,
        }

    admin_user = (os.getenv("ADMIN_USERNAME") or "").strip().lower()
    if not admin_user or not hmac.compare_digest(email_norm.encode(), admin_user.encode()):
        return None
    admin_hash = os.getenv("ADMIN_PASSWORD_HASH") or ""
    if admin_hash:
        valid = _verify_password(password, admin_hash)
    else:
        # Preserve the existing environment-based platform admin during migration.
        admin_pass = os.getenv("ADMIN_PASSWORD") or ""
        valid = bool(admin_pass) and hmac.compare_digest(password.encode(), admin_pass.encode())
    if not valid:
        return None
    return {
        "id": "admin",
        "email": admin_user,
        "roles": ["admin"],
        "tenant": None,
        "totp_secret": (os.getenv("ADMIN_TOTP_SECRET") or "").strip(),
    }


def verify_totp(secret: str, code: str) -> bool:
    """Verify a six-digit TOTP, allowing one time step for clock skew."""
    if not secret:
        return True
    if not isinstance(secret, str) or not isinstance(code, str):
        return False
    code = code.strip()
    if len(code) != 6 or not code.isascii() or not code.isdigit():
        return False
    try:
        normalized = secret.strip().upper().rstrip("=")
        key = base64.b32decode(normalized + "=" * (-len(normalized) % 8), casefold=True)
        if not key:
            return False
        timestep = int(time.time()) // 30
        for offset in (-1, 0, 1):
            digest = hmac.new(key, struct.pack(">Q", timestep + offset), hashlib.sha1).digest()
            position = digest[-1] & 0x0F
            number = struct.unpack(">I", digest[position:position + 4])[0] & 0x7FFFFFFF
            if hmac.compare_digest(code, f"{number % 1000000:06d}"):
                return True
    except (ValueError, binascii.Error, struct.error):
        return False
    return False


def start_management_session(user: dict[str, Any]) -> dict[str, Any]:
    """Rotate login state, storing only a safe, signed identity in the cookie."""
    identity = {key: user[key] for key in ("id", "email", "roles")}
    c = getattr(current_app, "container", None)
    if is_platform_admin(identity) and c.settings.BASE_URL.startswith("https://") and not user.get("totp_secret"):
        abort(403, description="Platform administrators must configure two-factor authentication for HTTPS deployments")
    if "business_owner" in user["roles"]:
        identity["tenant"] = user["tenant"]
    revision = _revision(identity)
    if not revision:
        abort(401)
    session_store.revoke(session.get("management_token"))
    session.clear()
    session.permanent = True
    session["user"] = identity
    session["management_token"] = session_store.create(identity, revision)
    session["_csrf"] = secrets.token_urlsafe(32)
    return identity


def is_platform_admin(user: Optional[dict[str, Any]] = None) -> bool:
    identity = user if user is not None else session.get("user")
    return isinstance(identity, dict) and bool(
        {"admin", "platform_admin"}.intersection(identity.get("roles") or [])
    )


def management_user(platform_only: bool = False) -> dict[str, Any]:
    """Enforce management authentication before inspecting or mutating tenant data."""
    saved = session_store.read(session.get("management_token"))
    if not saved:
        session.pop("user", None)
        abort(401, description="unauthorized")
    user, revision = saved
    current = _revision(user)
    if not current or not hmac.compare_digest(current, revision):
        session_store.revoke(session.get("management_token"))
        session.clear()
        abort(401, description="session_expired")
    if not isinstance(user, dict) or not user.get("id"):
        abort(401, description="unauthorized")
    roles = user.get("roles")
    if not isinstance(roles, list) or not _MANAGEMENT_ROLES.intersection(roles):
        abort(403, description="forbidden")
    if platform_only and not is_platform_admin(user):
        abort(403, description="platform_admin_required")
    return user


def require_management(platform_only: bool = False):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            management_user(platform_only=platform_only)
            return fn(*args, **kwargs)
        return wrapped
    return decorate


def authorized_tenant(requested: Optional[str] = None, default: Optional[str] = None) -> str:
    """Resolve a tenant using server-assigned owner scope, with explicit admin override."""
    user = management_user()
    if requested is not None and not isinstance(requested, str):
        abort(400, description="invalid_tenant")
    selected = (requested or "").strip()
    if not is_platform_admin(user):
        assigned = user.get("tenant")
        if not isinstance(assigned, str) or not _TENANT_KEY.fullmatch(assigned):
            abort(403, description="tenant_required")
        if selected and selected != assigned:
            abort(403, description="tenant_forbidden")
        return assigned
    if not selected:
        container = getattr(current_app, "container", None)
        settings = getattr(container, "settings", None)
        selected = default or getattr(settings, "BUSINESS_KEY", "")
    if not isinstance(selected, str) or not _TENANT_KEY.fullmatch(selected):
        abort(400, description="invalid_tenant")
    return selected
