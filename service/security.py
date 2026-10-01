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
from typing import Any, Dict, Mapping, Optional

from flask import abort, current_app, g, session
from werkzeug.security import check_password_hash, generate_password_hash

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
    """Hash new passwords without bcrypt's 72-byte truncation."""
    return generate_password_hash(password or "", method="scrypt")


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a bcrypt or scrypt hash."""
    try:
        if password_hash.startswith("scrypt:"):
            return _verify_password(password, password_hash)
        return bcrypt.checkpw((password or "").encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def generate_totp_token(secret: str, *, at: Optional[float] = None) -> str:
    return pyotp.TOTP(secret).now() if at is None else pyotp.TOTP(secret).at(at)

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


def _account_tenant(c: Any, tenant: str) -> str:
    storage = getattr(c, 'storage', None)
    return storage.canonical_tenant_key(tenant) if storage is not None and tenant else tenant



def _scoped_business_users(c, tenant):
    # Environment records require their own scope; tenant files supply scope.
    configured = []
    for record in _business_users():
        roles = record.get('roles', ['business_owner'])
        platform = _valid_roles(roles) and bool({'admin', 'platform_admin'}.intersection(roles))
        assigned = record.get('tenant')
        try:
            if platform or (isinstance(assigned, str) and assigned.strip()
                            and _account_tenant(c, assigned.strip()) == tenant):
                configured.append(record)
        except ValueError:
            continue
    local = [record for record in _stored_business_users(c, tenant)
             if not (_valid_roles(record.get('roles', ['business_owner']))
                     and {'admin', 'platform_admin'}.intersection(record.get('roles', ['business_owner'])))]
    return [*configured, *local]

def _authenticate_configured(
    c: Any = None, *, email: str = "", password: str = "", tenant: str = ""
) -> Optional[Dict[str, Any]]:
    email_norm = email.strip().lower()
    try:
        target = _account_tenant(c, tenant.strip())
    except ValueError:
        return None
    candidates = [record for record in _scoped_business_users(c, target)
                  if str(record.get('email') or '').strip().lower() == email_norm]
    if len(candidates) != 1:
        return None
    record = candidates[0]
    roles = record.get('roles', ['business_owner'])
    password_hash = record.get('password_hash')
    if (not _valid_roles(roles) or record.get('active') is False or record.get('disabled')
            or not _TENANT_KEY.fullmatch(target)
            or not isinstance(password_hash, str) or not verify_password(password, password_hash)):
        return None
    platform = bool({'admin', 'platform_admin'}.intersection(roles))
    assigned = str(record.get('tenant') or target).strip()
    try:
        configured_tenant = _account_tenant(c, assigned)
        permissions = _record_permissions(record, roles)
    except ValueError:
        return None
    if not platform and configured_tenant != target:
        return None
    secret = record.get('totp_secret') or ''
    if not isinstance(secret, str):
        return None
    return {'id': str(record.get('id') or f'owner:{assigned}:{email_norm}'),
            'email': email_norm, 'roles': roles, 'tenant': None if platform else configured_tenant,
            'totp_secret': secret, 'permissions': permissions, '_credential_account': record}

_TENANT_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_MANAGEMENT_ROLES = {"admin", "platform_admin", "business_owner", "business_staff"}

ALL_PERMISSIONS = frozenset({
    "analytics.read", "conversations.read", "customers.read", "offerings.read", "offerings.write",
    "offers.read", "offers.write", "users.read", "roles.read", "business_settings.read", "business_settings.write",
    "integrations.read", "health.read", "errors.read", "models.read", "models.write", "platform.read",
    "view_costs", "view_subscriptions",
})
OWNER_PERMISSIONS = ALL_PERMISSIONS - {"models.read", "models.write", "platform.read"}


def _valid_roles(roles):
    return (isinstance(roles, list) and bool(roles)
            and all(isinstance(role, str) and role in _MANAGEMENT_ROLES for role in roles))


def _record_permissions(record, roles):
    if not _valid_roles(roles):
        raise ValueError("invalid_account_roles")
    platform = bool({"admin", "platform_admin"}.intersection(roles))
    allowed = ALL_PERMISSIONS if platform else OWNER_PERMISSIONS
    default = allowed if platform or "business_owner" in roles else frozenset()
    # Earlier tenant owner records carried the staff-only permissions field,
    # which never restricted owners. Explicit new owner subsets are versioned.
    legacy_owner = ("business_owner" in roles and "roles" in record and "password_hash" in record
                    and record.get("permissions_version") != 1)
    configured = sorted(default) if legacy_owner else record.get("permissions", sorted(default))
    if (not isinstance(configured, list)
            or any(not isinstance(value, str) or value not in allowed for value in configured)):
        raise ValueError("invalid_account_permissions")
    return sorted(set(configured))


def _account_revision(record):
    return hmac.new(current_app.secret_key.encode(), json.dumps(record, sort_keys=True).encode(), hashlib.sha256).hexdigest()


def _bound_revision(account_revision, enrolled):
    protected = {"account_revision": account_revision, "mfa_policy": "all-accounts-v2", "enrolled_secret": enrolled}
    return hmac.new(current_app.secret_key.encode(), json.dumps(protected, sort_keys=True).encode(), hashlib.sha256).hexdigest()


def _revision(identity):
    """Changing/removing/disabling credentials immediately invalidates sessions."""
    if not isinstance(identity, dict) or not _valid_roles(identity.get('roles')):
        return None
    c = getattr(current_app, 'container', None)
    try:
        records = _registry_users(c)
    except (OSError, ValueError, TypeError):
        return None
    email = identity.get('email')
    matches = [r for r in records if str(r.get('email', '')).strip().lower() == email]
    try:
        if matches:
            if len(matches) != 1 or matches[0].get('disabled'):
                return None
            data = matches[0]
            roles = [data.get('role')]
            expected_tenant = (_account_tenant(c, data.get('tenant'))
                               if data.get('role') in ('business_owner', 'business_staff') else identity.get('tenant'))
        elif identity.get('id') == 'admin' and email == os.getenv('ADMIN_USERNAME', '').strip().lower():
            data = {key: os.getenv(key, '') for key in ('ADMIN_USERNAME', 'ADMIN_PASSWORD', 'ADMIN_PASSWORD_HASH', 'ADMIN_TOTP_SECRET')}
            if not data['ADMIN_PASSWORD'] and not data['ADMIN_PASSWORD_HASH']:
                return None
            roles = ['platform_admin']
            expected_tenant = identity.get('tenant')
        else:
            target = _account_tenant(c, str(identity.get('tenant') or ''))
            platform = bool({'admin', 'platform_admin'}.intersection(identity['roles']))
            candidates = [r for r in _scoped_business_users(c, target)
                          if str(r.get('email', '')).strip().lower() == email
                          and str(r.get('id') or f"owner:{r.get('tenant') or target}:{email}") == identity.get('id')
                          and ((platform and _valid_roles(r.get('roles'))
                                and {'admin', 'platform_admin'}.intersection(r['roles']))
                               or (not platform and _account_tenant(c, str(r.get('tenant') or target)) == target))]
            if len(candidates) != 1 or candidates[0].get('active') is False or candidates[0].get('disabled'):
                return None
            data = candidates[0]
            roles = data.get('roles', ['business_owner'])
            expected_tenant = identity.get('tenant') if platform else target
        if not _valid_roles(roles) or identity.get('roles') != roles or identity.get('tenant') != expected_tenant:
            return None
        permissions = _record_permissions(data, roles)
        if 'permissions' in identity and identity['permissions'] != permissions:
            return None
        from service.account_mfa import enrolled_secret
        return _bound_revision(_account_revision(data), enrolled_secret(identity))
    except (ValueError, TypeError):
        return None

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
    from service import session_store
    if session_store._using_postgres():
        with session_store.postgres_connection() as db:
            rows = db.execute(
                "SELECT payload FROM v7_private.operator_accounts ORDER BY email"
            ).fetchall()
        users = [row[0] for row in rows]
        if not all(isinstance(user, dict) for user in users):
            raise ValueError("Invalid account record")
        return users
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
    return _bind_authenticated_user(user, c, tenant) if user else None


def _bind_authenticated_user(user, container, tenant=''):
    """Bind the exact checked account snapshot to subsequent MFA/session work."""
    from service.account_mfa import enrolled_secret
    try:
        if user.get('tenant'):
            user['tenant'] = _account_tenant(container, user['tenant'])
        if user.get('tenant') and tenant and user['tenant'] != _account_tenant(container, tenant):
            return None
        enrolled = enrolled_secret(user)
        user['totp_secret'] = user.get('totp_secret') or enrolled
        record = user.pop('_credential_account')
        user['_account_revision'] = _account_revision(record)
        user['_credential_revision'] = _bound_revision(user['_account_revision'], enrolled)
        return user
    except (ValueError, TypeError):
        return None

def login_tenant_scope(c: Any, *, email: str, tenant: str) -> str:
    """Operator accounts share one attempt bound regardless of selected tenant."""
    try:
        records = _registry_users(c)
    except (OSError, ValueError, TypeError):
        return tenant
    matches = [record for record in records if str(record.get('email', '')).strip().lower() == email]
    if matches:
        role = matches[0].get('role') if len(matches) == 1 else None
        return '' if isinstance(role, str) and role in {'admin', 'platform_admin'} else tenant
    if email == os.getenv('ADMIN_USERNAME', '').strip().lower():
        return ''
    for record in _business_users():
        roles = record.get('roles', [])
        if (str(record.get('email', '')).strip().lower() == email and isinstance(roles, list)
                and any(role in {'admin', 'platform_admin'} for role in roles if isinstance(role, str))):
            return ''
    return tenant



def resolve_linked_account(reference: Mapping[str, object], container=None) -> Optional[Dict[str, Any]]:
    """Resolve an explicitly linked immutable identity without trusting provider roles."""
    if (not isinstance(reference, Mapping) or not isinstance(reference.get('id'), str)
            or not isinstance(reference.get('email'), str)
            or (reference.get('tenant') is not None and not isinstance(reference.get('tenant'), str))):
        return None
    c = container if container is not None else getattr(current_app, 'container', None)
    email = reference['email']
    if not email or email != email.strip().lower() or len(email) > 254:
        return None
    try:
        tenant = _account_tenant(c, reference.get('tenant') or '')
        records = _registry_users(c)
    except (OSError, ValueError, TypeError):
        return None
    matches = [record for record in records if str(record.get('email', '')).strip().lower() == email]
    if matches:
        if len(matches) != 1:
            return None
        record = matches[0]
        role = record.get('role')
        password_hash = record.get('password_hash')
        if (record.get('disabled') or not isinstance(role, str) or role not in _MANAGEMENT_ROLES
                or not isinstance(password_hash, str) or not password_hash.startswith('scrypt:')):
            return None
        try:
            assigned = _account_tenant(c, record.get('tenant') or '') if role in {'business_owner', 'business_staff'} else ''
        except (ValueError, TypeError):
            return None
        if role in {'business_owner', 'business_staff'} and not _TENANT_KEY.fullmatch(assigned):
            return None
        user = {'id': email, 'email': email, 'roles': [role], 'tenant': assigned or None,
                'totp_secret': record.get('totp_secret') or '', '_credential_account': record}
    elif email == os.getenv('ADMIN_USERNAME', '').strip().lower():
        if not os.getenv('ADMIN_PASSWORD') and not os.getenv('ADMIN_PASSWORD_HASH'):
            return None
        user = {'id': 'admin', 'email': email, 'roles': ['platform_admin'], 'tenant': None,
                'totp_secret': os.getenv('ADMIN_TOTP_SECRET', '').strip(),
                '_credential_account': {key: os.getenv(key, '') for key in ('ADMIN_USERNAME', 'ADMIN_PASSWORD', 'ADMIN_PASSWORD_HASH', 'ADMIN_TOTP_SECRET')}}
    else:
        user = None
        candidates = _scoped_business_users(c, tenant)
        for record in candidates:
            assigned = str(record.get('tenant') or tenant)
            roles = record.get('roles', ['business_owner'])
            if (str(record.get('email', '')).strip().lower() != email
                    or str(record.get('id') or f'owner:{assigned}:{email}') != reference['id']
                    or record.get('active') is False or record.get('disabled') or not isinstance(record.get('password_hash'), str)
                    or not record['password_hash']
                    or not _valid_roles(roles)):
                continue
            try:
                assigned = _account_tenant(c, assigned)
            except ValueError:
                continue
            platform = bool({'admin', 'platform_admin'}.intersection(roles))
            if not platform and assigned != tenant:
                continue
            if user is not None:
                return None
            user = {'id': reference['id'], 'email': email, 'roles': roles, 'tenant': None if platform else assigned,
                    'totp_secret': record.get('totp_secret') or '', '_credential_account': record}
        if user is None:
            return None
    platform = bool({'admin', 'platform_admin'}.intersection(user['roles']))
    if (user['id'] != reference['id'] or (platform and reference.get('tenant') is not None)
            or (not platform and (not tenant or user['tenant'] != tenant))
            or not isinstance(user['totp_secret'], str)):
        return None
    try:
        user['permissions'] = _record_permissions(user['_credential_account'], user['roles'])
    except ValueError:
        return None
    bound = _bind_authenticated_user(user, c)
    current = _revision(bound) if bound else None
    return bound if current and hmac.compare_digest(current, bound['_credential_revision']) else None


def _authenticate_user(
    c: Any = None, *, email: str = "", password: str = "", tenant: str = ""
) -> Optional[Dict[str, Any]]:
    """Authenticate a server-configured account; never take role/tenant from input."""
    if not isinstance(email, str) or not isinstance(password, str) or not isinstance(tenant, str):
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
        if record.get("disabled") or not isinstance(role, str) or role not in _MANAGEMENT_ROLES:
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
        try:
            permissions = _record_permissions(record, [role])
        except ValueError:
            return None
        return {
            "id": email_norm,
            "email": email_norm,
            "roles": [role],
            "tenant": tenant if role in {"business_owner", "business_staff"} else None,
            "totp_secret": secret, "permissions": permissions, "_credential_account": record,
        }

    environment = {key: os.getenv(key, "") for key in ("ADMIN_USERNAME", "ADMIN_PASSWORD", "ADMIN_PASSWORD_HASH", "ADMIN_TOTP_SECRET")}
    admin_user = environment["ADMIN_USERNAME"].strip().lower()
    if not admin_user or not hmac.compare_digest(email_norm.encode(), admin_user.encode()):
        return _authenticate_configured(c, email=email, password=password, tenant=tenant)
    admin_hash = environment["ADMIN_PASSWORD_HASH"]
    if admin_hash:
        valid = _verify_password(password, admin_hash)
    else:
        # Plaintext legacy credentials are confined to local HTTP compatibility.
        settings = getattr(c, "settings", None)
        if getattr(settings, "BASE_URL", "").startswith("https://"):
            return None
        admin_pass = environment["ADMIN_PASSWORD"]
        valid = bool(admin_pass) and hmac.compare_digest(password.encode(), admin_pass.encode())
    if not valid:
        return None
    return {
        "id": "admin",
        "email": admin_user,
        "roles": ["platform_admin"],
        "tenant": None,
        "totp_secret": environment["ADMIN_TOTP_SECRET"].strip(),
        "permissions": sorted(ALL_PERMISSIONS), "_credential_account": environment,
    }


def verify_totp(secret: str, code: str, identity: Optional[str] = None, database=None) -> bool:
    """Verify a TOTP; authenticated flows additionally consume its time step."""
    step = totp_timestep(secret, code)
    if step is None:
        return False
    if identity is None:
        return True
    normalized = secret.strip().upper().rstrip('=')
    key = base64.b32decode(normalized + '=' * (-len(normalized) % 8), casefold=True)
    return session_store.consume_totp(identity, key.hex(), step, database=database)


def totp_timestep(secret: str, code: str) -> Optional[int]:
    """Return the matching step so login can atomically reject code reuse."""
    if not secret:
        return None
    if not isinstance(secret, str) or not isinstance(code, str):
        return None
    code = code.strip()
    if len(code) != 6 or not code.isascii() or not code.isdigit():
        return None
    try:
        normalized = secret.strip().upper().rstrip("=")
        key = base64.b32decode(normalized + "=" * (-len(normalized) % 8), casefold=True)
        if not key:
            return None
        timestep = int(time.time()) // 30
        for offset in (-1, 0, 1):
            digest = hmac.new(key, struct.pack(">Q", timestep + offset), hashlib.sha1).digest()
            position = digest[-1] & 0x0F
            number = struct.unpack(">I", digest[position:position + 4])[0] & 0x7FFFFFFF
            if hmac.compare_digest(code, f"{number % 1000000:06d}"):
                return timestep + offset
    except (ValueError, binascii.Error, struct.error):
        return None
    return None


def start_management_session(user: dict[str, Any], tenant: str = "", *, mfa_verified: bool = False, transaction=None) -> dict[str, Any]:
    """Rotate login state, storing only a safe, signed identity in the cookie."""
    identity = {key: user[key] for key in ("id", "email", "roles")}
    if not mfa_verified or not user.get("totp_secret"):
        abort(403, description="mfa_setup_required")
    identity["tenant"] = user.get("tenant") or tenant
    if "permissions" in user:
        identity["permissions"] = user["permissions"]
    revision = _revision(identity)
    authenticated = user.get("_credential_revision")
    if not revision or not isinstance(authenticated, str) or not hmac.compare_digest(revision, authenticated):
        abort(401)
    token = session_store.create(identity, revision, transaction=transaction)
    session_store.revoke(session.get("management_token"), transaction=transaction)
    session.clear()
    session.permanent = True
    session["user"] = identity
    session["management_token"] = token
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
    if not _valid_roles(roles):
        abort(403, description="forbidden")
    if platform_only and not is_platform_admin(user):
        abort(403, description="platform_admin_required")
    g.management_identity = user
    g.management_revision = revision
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
    if not isinstance(user, dict) or not _valid_roles(user.get("roles")):
        return []
    if "permissions" in user:
        try:
            return _record_permissions(user, user["roles"])
        except ValueError:
            return []
    # Sessions issued before permission subsets were supported preserve role
    # defaults; staff grants still come only from the server account record.
    if is_platform_admin(user) or "business_owner" in user["roles"]:
        return _record_permissions({}, user["roles"])
    from service.account_service import AccountService
    c = getattr(current_app, "container", None)
    try:
        record = AccountService(c.storage).get_account(user["tenant"], user["id"]) if c else None
        return _record_permissions(record or {}, user["roles"])
    except (KeyError, ValueError, OSError):
        return []


def has_permission(user, permission):
    return permission in ALL_PERMISSIONS and permission in account_permissions(user)


def require_permission(permission, user=None):
    identity = management_user() if user is None else user
    if not has_permission(identity, permission):
        current_app.logger.warning("SECURITY permission_denied permission=%s", permission)
        abort(403, description="permission_required")
    return identity


def public_identity(user):
    return {**{key: value for key, value in user.items() if not key.startswith("_")},
            "permissions": account_permissions(user)}


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
        else:
            selected = assigned
    if not selected:
        container = getattr(current_app, "container", None)
        settings = getattr(container, "settings", None)
        selected = default or getattr(settings, "BUSINESS_KEY", "")
    if not isinstance(selected, str) or not _TENANT_KEY.fullmatch(selected):
        abort(400, description="invalid_tenant")
    # Analytics paths also use this guard, so alias/case conflicts cannot bypass
    # the document repository's tenant checks. Both storage runtimes share it.
    container = getattr(current_app, "container", None)
    try:
        exists = container.storage.tenant_exists(selected)
    except ValueError:
        abort(403, description="tenant_forbidden")
    if not exists:
        abort(404, description="tenant_not_found")
    return selected
