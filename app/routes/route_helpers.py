"""
Route helpers.

- get_container(): access DI container safely
- require_admin(): session-based admin auth for dashboard + APIs
- require_api_auth(): bearer-token auth for API endpoints
"""

from __future__ import annotations
from typing import Callable, Iterable, Optional
from functools import wraps

from flask import current_app, request, session, abort


# -------------------------------------------------------------------
# Container access
# -------------------------------------------------------------------

def get_container():
    container = getattr(current_app, "container", None)
    if container is None:
        raise RuntimeError("App container not initialized")
    return container


# -------------------------------------------------------------------
# Session-based ADMIN auth (dashboard + internal JSON)
# -------------------------------------------------------------------

def require_admin(roles: Optional[Iterable[str]] = None) -> Callable:
    """
    Requires a logged-in admin user via Flask session.
    Used for:
      - /admin/*
      - internal admin JSON APIs
    """
    required_roles = set(roles or ())

    def decorator(fn: Callable):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = session.get("user")

            if not user:
                abort(401, description="unauthorized")

            if required_roles:
                user_roles = set(user.get("roles", []))
                if not user_roles.intersection(required_roles):
                    abort(403, description="forbidden")

            return fn(*args, **kwargs)

        return wrapper

    return decorator


# -------------------------------------------------------------------
# Bearer-token API auth (public / programmatic APIs)
# -------------------------------------------------------------------

def require_api_auth(roles: Optional[Iterable[str]] = None) -> Callable:
    """
    Requires Authorization: Bearer <token>
    Used for:
      - webhook APIs
      - external integrations
    """
    required_roles = set(roles or ())

    def decorator(fn: Callable):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            container = get_container()
            from service.security import (
                authenticate_bearer_token,
                ensure_roles,
            )

            user = authenticate_bearer_token(container, request)
            if not user:
                abort(401, description="unauthorized")

            if required_roles:
                ensure_roles(user, required_roles)

            return fn(*args, **kwargs)

        return wrapper

    return decorator
