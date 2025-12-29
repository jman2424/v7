# routes/__init__.py
from __future__ import annotations

from typing import Callable, Any, Optional, Iterable
from functools import wraps

from flask import current_app, request


def get_container():
    c = getattr(current_app, "container", None)
    if c is None:
        raise RuntimeError("Container not initialized on app")
    return c


def require_auth(roles: Optional[Iterable[str]] = None) -> Callable[..., Any]:
    required = set(roles or ())

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            container = get_container()

            # SINGLE source of truth
            from services.security import require_bearer_or_session, ensure_roles

            user = require_bearer_or_session(container, request)

            if required:
                ensure_roles(user, required)

            return fn(*args, **kwargs)
        return wrapper
    return deco
