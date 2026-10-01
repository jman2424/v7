"""Shared revocable browser sessions for both management interfaces."""
from __future__ import annotations
from typing import Any
from flask import session
from werkzeug.exceptions import Unauthorized
from service.security import management_user, start_management_session
from service import session_store

def establish_authenticated_session(user: dict[str, Any], tenant: str, *, mfa_verified: bool = False) -> dict[str, Any]:
    return start_management_session(user, tenant, mfa_verified=mfa_verified)

def clear_authenticated_session(*, revoke_device: bool = False) -> None:
    from service.account_mfa import cancel_pending
    from service.trusted_devices import revoke_current
    cancel_pending()
    if revoke_device:
        revoke_current()
    session_store.revoke(session.get("management_token"))
    session.clear()

def is_authenticated_account_active(storage: Any) -> bool:
    try:
        management_user()
        return True
    except Unauthorized:
        return False
