"""Authenticated browser session helpers shared by console and legacy routes."""

from __future__ import annotations

import secrets
from typing import Any

from flask import session


def establish_authenticated_session(user: dict[str, Any], tenant: str) -> dict[str, Any]:
    """Replace the anonymous session with the minimum safe browser identity."""
    roles = user.get("roles") or []
    safe_roles = [str(role) for role in roles if str(role).strip()]
    identity = {
        "id": str(user.get("id") or "user"),
        "email": str(user.get("email") or "").strip().lower(),
        "roles": safe_roles,
        "tenant": str(user.get("tenant") or tenant).strip(),
    }

    # Flask's signed cookie is readable by its holder, so never retain the
    # authentication result or TOTP material returned by the server-side lookup.
    session.clear()
    session.permanent = True
    session["_csrf"] = f"csrf_{secrets.token_urlsafe(32)}"
    session["user"] = identity
    return identity


def clear_authenticated_session() -> None:
    session.clear()


def is_authenticated_account_active(storage: Any) -> bool:
    """Confirm that a tenant-managed account has not been disabled since login."""
    identity = session.get("user")
    if not isinstance(identity, dict):
        return False

    account_id = str(identity.get("id") or "")
    if not account_id.startswith("account:"):
        # Platform and migration accounts are authenticated from server-only
        # configuration instead of a tenant account file.
        return True

    tenant = str(identity.get("tenant") or "").strip()
    if not tenant:
        return False
    try:
        from service.account_service import AccountService

        account = AccountService(storage).get_account(tenant, account_id)
    except (AttributeError, OSError, ValueError):
        return False
    return bool(account and account.get("active") is not False)
