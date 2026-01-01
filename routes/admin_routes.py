from __future__ import annotations

import secrets
from flask import Blueprint, request, render_template, redirect, url_for, session, abort
from routes import get_container, require_auth

bp = Blueprint("admin_routes", __name__, url_prefix="/admin")


def _ensure_csrf() -> str:
    """
    Create a per-session CSRF token if missing.
    This must match middleware which checks session['_csrf'].
    """
    if not session.get("_csrf"):
        session["_csrf"] = secrets.token_hex(16)  # 32 chars
    return session["_csrf"]


def _session_role_label() -> str:
    u = session.get("user") or {}
    roles = u.get("roles") or []
    if "Owner" in roles or "Manager" in roles:
        return "admin"
    if "Staff" in roles:
        return "staff"
    return "staff"


@bp.get("/login")
def admin_login_page():
    return render_template("login.html", csrf_token=_ensure_csrf(), error=None)


@bp.post("/login")
def admin_login_submit():
    # CSRF check (middleware will also check, but keep this for clarity)
    token = (request.form.get("csrf_token") or "").strip()
    if not token or token != session.get("_csrf"):
        abort(403, description="csrf_failed")

    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    totp = (request.form.get("totp") or "").strip() or None

    from services.security import authenticate_user, verify_totp

    user = authenticate_user(email=email, password=password)
    if not user:
        return render_template("login.html", csrf_token=_ensure_csrf(), error="Invalid credentials"), 401

    if user.get("totp_secret"):
        if not totp or not verify_totp(user["totp_secret"], totp):
            return render_template("login.html", csrf_token=_ensure_csrf(), error="TOTP required/invalid"), 401

    session["user"] = {"id": user["id"], "email": user["email"], "roles": user.get("roles", [])}
    return redirect(url_for("admin_routes.admin_home"))


@bp.post("/logout")
def admin_logout():
    session.pop("user", None)
    return redirect(url_for("admin_routes.admin_login_page"))


@bp.get("/")
@require_auth(roles=("Owner", "Manager", "Staff"))
def admin_home():
    c = get_container()
    u = session.get("user") or {}

    tenant = c.settings.BUSINESS_KEY
    tenants = [tenant]
    role = _session_role_label()

    return render_template(
        "admin.html",
        tenant=tenant,
        tenants=tenants,
        role=role,
        session_id=f"sess_{u.get('id','')}",
        csrf_token=_ensure_csrf(),
        branding=None,
    )
