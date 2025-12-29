from __future__ import annotations

import uuid
from flask import Blueprint, request, jsonify, render_template, session, redirect, url_for

from routes import get_container, require_auth

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _ensure_csrf_token() -> str:
    if "_csrf" not in session:
        session["_csrf"] = uuid.uuid4().hex
    return session["_csrf"]


# -------------------------
# Pages
# -------------------------

@bp.get("/login")
def admin_login_page():
    csrf_token = _ensure_csrf_token()
    return render_template("login.html", csrf_token=csrf_token)


@bp.post("/login")
def admin_login_submit():
    """
    Handles HTML form login safely:
    - validates CSRF via middleware (it reads form csrf_token now)
    - authenticates user
    - sets session["user"]
    - redirects to /admin/
    """
    c = get_container()

    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    totp = (request.form.get("totp") or "").strip()

    from services.security import authenticate_user, verify_totp

    user = authenticate_user(email=email, password=password)
    if not user:
        csrf_token = _ensure_csrf_token()
        return render_template("login.html", error="Invalid credentials", csrf_token=csrf_token), 401

    if user.get("totp_secret"):
        if not totp or not verify_totp(user["totp_secret"], totp):
            csrf_token = _ensure_csrf_token()
            return render_template("login.html", error="TOTP required/invalid", csrf_token=csrf_token), 401

    session["user"] = {"id": user["id"], "email": user["email"], "roles": user.get("roles", [])}

    return redirect(url_for("admin.admin_home"))


@bp.post("/logout")
def admin_logout():
    session.pop("user", None)
    session.pop("_csrf", None)
    return redirect(url_for("admin.admin_login_page"))


@bp.get("/")
@require_auth(roles=("Owner", "Manager", "Staff"))
def admin_home():
    c = get_container()
    csrf_token = _ensure_csrf_token()
    # if your template expects these:
    return render_template(
        "admin.html",
        tenant=c.settings.BUSINESS_KEY,
        csrf_token=csrf_token,
        role=(session.get("user") or {}).get("roles", [""])[0] if session.get("user") else "",
        session_id=session.get("_sid", ""),
        tenants=[c.settings.BUSINESS_KEY],
    )


# -------------------------
# APIs
# -------------------------

@bp.get("/api/leads")
@require_auth(roles=("Owner", "Manager", "Staff"))
def api_leads():
    c = get_container()
    limit = int(request.args.get("limit", "50"))
    leads = c.crm.list_leads(limit=limit)
    return jsonify({"leads": leads})


@bp.get("/api/summary")
@require_auth(roles=("Owner", "Manager", "Staff"))
def api_summary():
    c = get_container()
    summary = c.analytics.summary(c.settings.BUSINESS_KEY)
    return jsonify(summary)


@bp.get("/api/audit")
@require_auth(roles=("Owner", "Manager"))
def api_audit():
    c = get_container()
    items = c.storage.list_audit_entries(c.settings.BUSINESS_KEY)
    return jsonify({"audit": items})
