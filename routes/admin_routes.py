from __future__ import annotations

import secrets
from flask import Blueprint, request, render_template, redirect, url_for, session

from routes import get_container, require_auth

bp = Blueprint("admin_routes", __name__, url_prefix="/admin")


def _ensure_csrf_token() -> str:
    """
    CSRF token is stored per-session.
    Middleware expects session['_csrf'] and form field 'csrf_token'.
    """
    tok = session.get("_csrf")
    if not tok:
        tok = secrets.token_urlsafe(24)
        session["_csrf"] = tok
    return tok


def _session_role_label() -> str:
    u = session.get("user") or {}
    roles = u.get("roles") or []

    # Template checks role in ['admin','staff']
    if "Owner" in roles or "Manager" in roles or "Admin" in roles:
        return "admin"
    return "staff"


@bp.get("/login")
def admin_login_page():
    """
    Renders the HTML login page.
    IMPORTANT: This is the page route. Do not POST here when using option B.
    """
    c = get_container()
    token = _ensure_csrf_token()

    error = request.args.get("error")
    return render_template(
        "login.html",
        csrf_token=token,
        error=error,
        tenant=c.settings.BUSINESS_KEY,
    )


@bp.get("/")
@require_auth(roles=("Owner", "Manager", "Staff"))
def admin_home():
    """
    Admin dashboard page (HTML).
    """
    c = get_container()
    u = session.get("user") or {}

    tenant = c.settings.BUSINESS_KEY
    tenants = [tenant]  # expand later for multi-tenant
    role = _session_role_label()

    return render_template(
        "admin.html",
        tenant=tenant,
        tenants=tenants,
        role=role,
        session_id=f"sess_{u.get('id','')}",
        csrf_token=_ensure_csrf_token(),
        branding=None,
    )


@bp.post("/logout")
def admin_logout():
    """
    Clears session and returns to login page.
    """
    session.pop("user", None)
    session.pop("_csrf", None)
    return redirect(url_for("admin_routes.admin_login_page"))
