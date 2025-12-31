from __future__ import annotations

import secrets
from flask import Blueprint, request, render_template, redirect, url_for, session, abort

from routes import get_container, require_auth

bp = Blueprint("admin_routes", __name__, url_prefix="/admin")


def _get_or_set_csrf() -> str:
    """
    Creates a per-session CSRF token and returns it.
    Middleware will validate against session['_csrf'].
    """
    token = session.get("_csrf")
    if not token:
        token = secrets.token_hex(16)
        session["_csrf"] = token
    return token


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
    # allow querystring error display (optional)
    err = request.args.get("error")
    return render_template("login.html", csrf_token=_get_or_set_csrf(), error=err)


@bp.post("/login")
def admin_login_submit():
    form = request.form or {}

    got = (form.get("csrf_token") or "").strip()
    expected = session.get("_csrf") or ""
    if not expected or not got or got != expected:
        abort(403, description="csrf_failed")

    email = (form.get("email") or "").strip().lower()
    password = form.get("password") or ""
    totp = (form.get("totp") or "").strip()

    from services.security import authenticate_user, verify_totp

    user = authenticate_user(email=email, password=password)
    if not user:
        return render_template("login.html", csrf_token=_get_or_set_csrf(), error="Invalid email or password"), 401

    if user.get("totp_secret"):
        if not totp or not verify_totp(user["totp_secret"], totp):
            return render_template("login.html", csrf_token=_get_or_set_csrf(), error="TOTP required/invalid"), 401

    session["user"] = {
        "id": user["id"],
        "email": user["email"],
        "roles": user.get("roles", []),
    }

    return redirect(url_for("admin_routes.admin_home"))


@bp.post("/logout")
def admin_logout():
    session.pop("user", None)
    # keep csrf, or clear both — your choice:
    # session.pop("_csrf", None)
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
        csrf_token=_get_or_set_csrf(),
        branding=None,
    )


# ---------------- API endpoints ----------------

@bp.get("/api/leads")
@require_auth(roles=("Owner", "Manager", "Staff"))
def api_leads():
    c = get_container()
    limit = int(request.args.get("limit", "50"))
    leads = c.crm.list_leads(limit=limit)
    return {"leads": leads}


@bp.get("/api/summary")
@require_auth(roles=("Owner", "Manager", "Staff"))
def api_summary():
    c = get_container()
    return c.analytics.summary(c.settings.BUSINESS_KEY)
