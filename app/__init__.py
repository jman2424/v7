"""
Route helpers.

Exports:
- get_container(): access DI container at current_app.container
- require_auth(): RBAC gate for browser + API endpoints

Behavior:
- If request looks like browser HTML -> redirect to /admin/login on 401
- If request looks like API/JSON -> return JSON 401/403
"""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable, Iterable, Optional, Set

from flask import current_app, request, jsonify, redirect, url_for


def get_container():
    c = getattr(current_app, "container", None)
    if c is None:
        raise RuntimeError("Container not initialized on app")
    return c


def _wants_html() -> bool:
    """
    Decide whether to redirect (HTML) or return JSON errors (API).
    """
    accept = (request.headers.get("Accept") or "").lower()
    # browsers commonly send text/html
    if "text/html" in accept and "application/json" not in accept:
        return True
    # if they’re hitting an admin page, treat as HTML
    if (request.path or "").startswith("/admin"):
        return True
    return False


def _normalize_roles(roles: Iterable[str]) -> Set[str]:
    return {str(r).strip().lower() for r in roles if r is not None}


def require_auth(roles: Optional[Iterable[str]] = None) -> Callable[..., Any]:
    """
    Use on routes that require:
      - a valid session user OR a valid Bearer token user
      - optionally certain roles
    """
    required_roles = _normalize_roles(roles or ())

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            container = get_container()

            # Import here to avoid circular imports at startup
            from services.security import require_bearer_or_session

            # 1) Authenticate (session or bearer)
            try:
                user = require_bearer_or_session(container, request)
            except Exception:
                # Treat failures as unauth
                if _wants_html():
                    return redirect(url_for("admin_routes.admin_login_page"))
                return jsonify({"ok": False, "error": "unauthorized"}), 401

            if not user:
                if _wants_html():
                    return redirect(url_for("admin_routes.admin_login_page"))
                return jsonify({"ok": False, "error": "unauthorized"}), 401

            # 2) Authorize (roles)
            if required_roles:
                user_roles = _normalize_roles(user.get("roles", []))

                # allow admin-style role aliasing if you use them anywhere
                # (optional, but helps when templates say "admin"/"staff")
                aliases = set(user_roles)
                if "owner" in user_roles or "manager" in user_roles:
                    aliases.add("admin")
                if "staff" in user_roles:
                    aliases.add("staff")

                if not (aliases & required_roles):
                    if _wants_html():
                        return redirect(url_for("admin_routes.admin_login_page"))
                    return jsonify({"ok": False, "error": "forbidden"}), 403

            return fn(*args, **kwargs)

        return wrapper

    return deco
