"""
Route helpers.

Exports:
- get_container(): access to app.container
- require_auth(): RBAC gate for admin endpoints/pages
"""

from __future__ import annotations
from typing import Callable, Any, Optional, Iterable, Set
from functools import wraps

from flask import current_app, request, session, abort


def get_container():
    c = getattr(current_app, "container", None)
    if c is None:
        raise RuntimeError("Container not initialized on app")
    return c


def get_tenant_container(tenant: str):
    """Return the container whose retrieval stores are bound to `tenant`."""
    return get_container().for_tenant(tenant)


def _has_any_role(user_roles: Iterable[str], required: Set[str]) -> bool:
    user_set = {str(r) for r in (user_roles or [])}
    return bool(user_set.intersection(required))


def require_auth(roles: Optional[Iterable[str]] = None) -> Callable[..., Any]:
    """
    Requires a logged-in session user.
    Optionally requires at least one role in `roles`.
    """
    required = set(roles or ())

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = session.get("user")
            if not user:
                abort(401, description="unauthorized")

            if required:
                if not _has_any_role(user.get("roles", []), required):
                    abort(403, description="forbidden")

            return fn(*args, **kwargs)

        return wrapper

    return deco
