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
def _business_users() -> list[Dict[str, Any]]:
    """Load tenant-bound users from a server-only JSON environment variable."""
    raw = (os.getenv("BUSINESS_USERS_JSON") or "").strip()
    if not raw:
        return []
    try:
        users = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [user for user in users if isinstance(user, dict)] if isinstance(users, list) else []


def _stored_business_users(c: Any, tenant: str) -> list[Dict[str, Any]]:
    """Load tenant-local accounts without making account records public."""
    if c is None or not tenant:
        return []
    try:
        from service.account_service import ACCOUNT_FILE

        users = c.storage.read_json(tenant, ACCOUNT_FILE)
    except (FileNotFoundError, ValueError, OSError, AttributeError, json.JSONDecodeError):
        return []
    return [user for user in users if isinstance(user, dict)] if isinstance(users, list) else []


def _authenticate_configured(
    c: Any = None, *, email: str = "", password: str = "", tenant: str = ""
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
    email_norm = (email or "").strip().lower()
    password_norm = password or ""

    if admin_user and admin_pass and (
        hmac.compare_digest(email_norm, admin_user)
        and hmac.compare_digest(password_norm, admin_pass)
    ):
        return {
            "id": "admin",
            "email": admin_user,
            "roles": ["platform_admin"],
            "totp_secret": (os.getenv("ADMIN_TOTP_SECRET") or "").strip() or None,
        }

    target_tenant = (tenant or "").strip()
    for configured in [*_business_users(), *_stored_business_users(c, target_tenant)]:
        configured_email = str(configured.get("email") or "").strip().lower()
        configured_tenant = str(configured.get("tenant") or "").strip()
        if not configured_tenant:
            configured_tenant = target_tenant
        password_hash = str(configured.get("password_hash") or "")
        roles = configured.get("roles") or ["business_owner"]
        if not isinstance(roles, list):
            continue
        if not (
            configured_email
            and configured_tenant
            and password_hash
            and configured.get("active") is not False
            and hmac.compare_digest(email_norm, configured_email)
            and hmac.compare_digest(target_tenant, configured_tenant)
            and verify_password(password_norm, password_hash)
        ):
            continue

        return {
            "id": str(configured.get("id") or f"owner:{configured_tenant}:{configured_email}"),
            "email": configured_email,
            "roles": [str(role) for role in roles],
            "tenant": configured_tenant,
            "totp_secret": str(configured.get("totp_secret") or "").strip() or None,
        }

    return None


_TENANT_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_MANAGEMENT_ROLES = {"admin", "platform_admin", "business_owner", "business_staff"}


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
        target = str(identity.get("tenant") or "")
        candidates = [*_business_users(), *_stored_business_users(c, target)]
        candidates = [r for r in candidates if str(r.get("email", "")).strip().lower() == email
                      and str(r.get("tenant") or target) == target
                      and str(r.get("id") or f"owner:{target}:{email}") == identity.get("id")]
        if len(candidates) != 1 or candidates[0].get("active") is False:
            return None
        data = candidates[0]
    from service.account_mfa import enrolled_secret
    protected = {'account': data, 'mfa_policy': 'all-accounts-v1', 'enrolled_secret': enrolled_secret(identity)}
    return hmac.new(current_app.secret_key.encode(), json.dumps(protected, sort_keys=True).encode(), hashlib.sha256).hexdigest()


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
    c: Any = None, *, email: str = "", password: str = "", tenant: str = ""
) -> Optional[Dict[str, Any]]:
    user = _authenticate_user(c, email=email, password=password, tenant=tenant)
    if user:
        if user.get('tenant') and tenant and user['tenant'] != tenant:
            return None
        from service.account_mfa import enrolled_secret
        user['totp_secret'] = user.get('totp_secret') or enrolled_secret(user)
    return user


def _authenticate_user(
    c: Any = None, *, email: str = "", password: str = "", tenant: str = ""
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
        if role in {"business_owner", "business_staff"} and (
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
            "tenant": tenant if role in {"business_owner", "business_staff"} else None,
            "totp_secret": secret,
        }

    admin_user = (os.getenv("ADMIN_USERNAME") or "").strip().lower()
    if not admin_user or not hmac.compare_digest(email_norm.encode(), admin_user.encode()):
        return _authenticate_configured(c, email=email, password=password, tenant=tenant)
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
        "roles": ["platform_admin"],
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


def start_management_session(user: dict[str, Any], tenant: str = "", *, mfa_verified: bool = False) -> dict[str, Any]:
    """Rotate login state, storing only a safe, signed identity in the cookie."""
    identity = {key: user[key] for key in ("id", "email", "roles")}
    if not mfa_verified or not user.get("totp_secret"):
        abort(403, description="mfa_setup_required")
    identity["tenant"] = user.get("tenant") or tenant
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
    if session.get("user") != user:
        session_store.revoke(session.get("management_token"))
        session.clear()
        abort(401, description="session_expired")
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


def account_permissions(user):
    from service.account_service import AccountService, STAFF_PERMISSIONS
    if is_platform_admin(user) or 'business_owner' in user.get('roles', []):
        return sorted(STAFF_PERMISSIONS)
    c = getattr(current_app, 'container', None)
    record = AccountService(c.storage).get_account(user['tenant'], user['id']) if c else None
    return [value for value in (record or {}).get('permissions', []) if value in STAFF_PERMISSIONS]


def require_permission(permission):
    user = management_user()
    if permission not in account_permissions(user):
        abort(403, description='permission_required')
    return user


def public_identity(user):
    return {**user, 'permissions': account_permissions(user)}


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
            from service.tenant_access import owned_tenants
            if selected not in owned_tenants(user):
                abort(403, description="tenant_forbidden")
            return selected
        return assigned
    if not selected:
        container = getattr(current_app, "container", None)
        settings = getattr(container, "settings", None)
        selected = default or getattr(settings, "BUSINESS_KEY", "")
    if not isinstance(selected, str) or not _TENANT_KEY.fullmatch(selected):
        abort(400, description="invalid_tenant")
    return selected
