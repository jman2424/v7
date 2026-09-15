"""Compatibility redirects for retired Flask dashboard URLs."""
from __future__ import annotations

from flask import Blueprint, abort, request, redirect, url_for, session
from werkzeug.exceptions import Unauthorized
from routes.session_auth import clear_authenticated_session
from service.security import management_user, authorized_tenant, is_platform_admin

bp = Blueprint("admin_ui", __name__, url_prefix="/admin")

PAGES = {
    "overview": "pipeline", "companies": "companies", "conversations": "conversations",
    "business": "profile", "settings": "agent", "errors": "errors",
    "integrations": "integrations", "products": "catalog", "faqs": "faqs",
    "branches": "branches", "delivery": "delivery", "widget": "website",
}


def _console_login():
    return redirect(url_for("owner_console.owner_console_index"), code=303)


@bp.get("/")
@bp.get("/<page>")
def dashboard(page="overview"):
    if page not in PAGES:
        abort(404)
    if not session.get("user"):
        return _console_login()
    try:
        user = management_user(platform_only=page == "companies")
    except Unauthorized:
        clear_authenticated_session()
        return _console_login()
    tenant = authorized_tenant(request.args.get("tenant"))
    section = "platform" if page == "overview" and is_platform_admin(user) else PAGES[page]
    return redirect(url_for("owner_console.owner_console_asset", asset_path=section, tenant=tenant), code=303)


@bp.get("/login")
def login_page():
    return _console_login()


@bp.post("/login")
def login_submit():
    # Retired forms never process credentials or forward their body to another URL.
    # The console uses the existing CSRF-protected /auth login and MFA flow.
    return _console_login()


@bp.post("/logout")
def logout():
    clear_authenticated_session()
    return _console_login()
