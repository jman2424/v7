"""
Route helpers.

Exports:
- require_auth(): RBAC gate for admin JSON endpoints.
- get_container(): typed access to app.container
"""

from __future__ import annotations
from typing import Callable, Any, Optional, Iterable
from functools import wraps

from flask import current_app, request, abort

# ---- Container access ----

def get_container():
    c = getattr(current_app, "container", None)
    if c is None:
        raise RuntimeError("Container not initialized on app")
    return c

# ---- Auth / RBAC decorator for admin JSON ----

def require_auth(roles: Optional[Iterable[str]] = None) -> Callable[..., Any]:
    roles = set(roles or ())

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            container = get_container()
            sec = container  # type: ignore
            # services.security is not attached directly; import here:
            from services.security import require_bearer_or_session, ensure_roles

            user = require_bearer_or_session(container, request)
            if roles:
                ensure_roles(user, roles)
            return fn(*args, **kwargs)
        return wrapper
    return deco
