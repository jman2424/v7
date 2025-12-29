from __future__ import annotations

from flask import Blueprint, request, render_template, redirect, url_for, session, abort
from routes import get_container, require_auth

bp = Blueprint("admin_routes", __name__, url_prefix="/admin")


def _csrf_token() -> str:
    c = get_container()
    # Must match middleware check (SECRET_KEY[:16])
    return (c.settings.SECRET_KEY or "")[:16]


def _session_role_label() -> str:
    u = session.get("user") or {}
    roles = u.get("roles") or []
    # your template checks role in ['admin','staff'] so we map
    if "Owner" in roles or "Manager" in roles:
        return "admin"
    if "Staff" in roles:
        return "staff"
    return "staff"


@bp.get("/login")
def admin_login_page():
    # IMPORTANT: page is /admin/login (GET)
    return render_template("login.html", csrf_token=_csrf_token(), error=None)


@bp.post("/login")
def admin_login_submit():
    # IMPORTANT: form posts here (NOT /auth/login)
    c = get_container()
    form = request.form or {}

    token = form.get("csrf_token")
    if not token or token != _csrf_token():
        abort(403, description="csrf_failed")

    email = (form.get("email") or "").strip().lower()
    password = form.get("password") or ""
    totp = (form.get("totp") or "").strip()

    from services.security import authenticate_user, verify_totp

    user = authenticate_user(email=email, password=password)
    if not user:
        return render_template("login.html", csrf_token=_csrf_token(), error="Invalid credentials"), 401

    if user.get("totp_secret"):
        if not totp or not verify_totp(user["totp_secret"], totp):
            return render_template("login.html", csrf_token=_csrf_token(), error="TOTP required/invalid"), 401

    session["user"] = {"id": user["id"], "email": user["email"], "roles": user.get("roles", [])}

    # redirect to dashboard (do NOT show JSON endpoint)
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

    # minimal-but-safe context for your admin.html
    tenant = c.settings.BUSINESS_KEY
    tenants = [tenant]  # or load from config if you have multi-tenant keys
    role = _session_role_label()

    return render_template(
        "admin.html",
        tenant=tenant,
        tenants=tenants,
        role=role,
        session_id=f"sess_{u.get('id','')}",
        csrf_token=_csrf_token(),
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
