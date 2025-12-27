"""
routes/__init__.py

Route helpers.

Exports:
- get_container(): access to app.container
- require_auth(): auth + RBAC gate that behaves correctly for HTML vs JSON

Behavior:
- Browser page requests (Accept: text/html) -> redirect to /admin/login when unauthenticated
- API requests (Accept: application/json / X-Requested-With / /api/*) -> JSON 401/403
"""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable, Iterable, Optional

from flask import current_app, request, redirect, url_for, jsonify


# -------------------------
# Container access
# -------------------------

def get_container():
    c = getattr(current_app, "container", None)
    if c is None:
        raise RuntimeError("Container not initialized on app")
    return c


# -------------------------
# Request type detection
# -------------------------

def _is_api_request() -> bool:
    """
    Decide whether to respond with JSON errors (API) or redirects (HTML).
    """
    path = (request.path or "").lower()
    accept = (request.headers.get("Accept") or "").lower()
    xrw = (request.headers.get("X-Requested-With") or "").lower()

    if path.startswith("/admin/api/") or path.startswith("/analytics/") or path.endswith(".json"):
        return True
    if "application/json" in accept:
        return True
    if xrw == "xmlhttprequest":
        return True
    return False


def _unauthorized_response():
    if _is_api_request():
        return jsonify({"error": "unauthorized"}), 401
    return redirect(url_for("admin.admin_login_page"))


def _forbidden_response():
    if _is_api_request():
        return jsonify({"error": "forbidden"}), 403
    # For HTML, forbidden should not redirect to login (they *are* logged in),
    # so return a clean 403 page-ish response.
    return ("Forbidden", 403)


# -------------------------
# Auth / RBAC decorator
# -------------------------

def require_auth(roles: Optional[Iterable[str]] = None) -> Callable[..., Any]:
    """
    Enforce authentication and optional role membership.

    roles: iterable of allowed role strings, e.g. ("Owner","Manager","Staff")
    """
    allowed_roles = set(roles or ())

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            container = get_container()

            # IMPORTANT: keep this import path consistent across repo
            # If your project uses "services.security", change it here and everywhere.
            from service.security import require_bearer_or_session, ensure_roles  # type: ignore

            try:
                user = require_bearer_or_session(container, request)
            except Exception:
                return _unauthorized_response()

            if allowed_roles:
                try:
                    ensure_roles(user, allowed_roles)
                except Exception:
                    return _forbidden_response()

            return fn(*args, **kwargs)

        return wrapper

    return deco
