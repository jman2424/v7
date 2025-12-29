"""
Route helpers.

Exports:
- require_auth(): RBAC gate for admin endpoints
- get_container(): access to app.container
"""

from __future__ import annotations
from typing import Callable, Any, Optional, Iterable
from functools import wraps

from flask import current_app, request, abort, session


def get_container():
    c = getattr(current_app, "container", None)
    if c is None:
        raise RuntimeError("Container not initialized on app")
    return c


def require_auth(roles: Optional[Iterable[str]] = None) -> Callable[..., Any]:
    need_roles = set(roles or ())

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            c = get_container()

            # Session auth first
            user = session.get("user")

            # Optional: allow bearer auth for API calls
            if not user:
                from services.security import require_bearer_or_none  # you implement this or stub it
                user = require_bearer_or_none(c, request)

            if not user:
                abort(401, description="unauthorized")

            if need_roles:
                from services.security import ensure_roles
                ensure_roles(user, need_roles)

            return fn(*args, **kwargs)
        return wrapper
    return deco
