"""
Route helpers.

Exports:
- get_container(): access DI container attached to app
- require_auth(): session/bearer auth + optional RBAC
"""

from __future__ import annotations

from typing import Callable, Any, Optional, Iterable
from functools import wraps

from flask import current_app, request, abort


def get_container():
    c = getattr(current_app, "container", None)
    if c is None:
        raise RuntimeError("Container not initialized on app")
    return c


def require_auth(roles: Optional[Iterable[str]] = None) -> Callable[..., Any]:
    required_roles = set(roles or ())

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            container = get_container()

            # NOTE: correct module name is services.security (plural)
            from services.security import require_bearer_or_session, ensure_roles

            user = require_bearer_or_session(container, request)

            if required_roles:
                ensure_roles(user, required_roles)

            return fn(*args, **kwargs)

        return wrapper

    return deco
