from __future__ import annotations

from flask import Blueprint, request, jsonify, render_template, redirect, url_for, session
from routes import get_container, require_auth

bp = Blueprint("admin", __name__, url_prefix="/admin")


# -------------------------
# HTML pages
# -------------------------

@bp.get("/login")
def admin_login_page():
    # renders templates/login.html
    return render_template("login.html", error=None)


@bp.post("/login")
def admin_login_submit():
    """
    HTML form login:
    - validates credentials
    - sets session["user"]
    - redirects to /admin/
    """
    c = get_container()

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    totp_code = (request.form.get("totp_code") or "").strip() or None

    from services.security import authenticate_user, verify_totp

    # allow username OR email — your security service decides
    user = authenticate_user(email=username.lower(), password=password) or authenticate_user(
        email=username, password=password
    )

    if not user:
        return render_template("login.html", error="Invalid username/password"), 401

    # If user has TOTP enabled, require it
    if user.get("totp_secret"):
        if not totp_code or not verify_totp(user["totp_secret"], totp_code):
            return render_template("login.html", error="TOTP code required/invalid"), 401

    roles = user.get("roles") or []
    session["user"] = {
        "id": user.get("id"),
        "email": user.get("email") or username,
        "roles": roles,
    }

    return redirect(url_for("admin.admin_home"))


@bp.get("/logout")
def admin_logout():
    session.pop("user", None)
    return redirect(url_for("admin.admin_login_page"))


@bp.get("/")
@require_auth(roles=("Owner", "Manager", "Staff"))
def admin_home():
    c = get_container()
    user = session.get("user") or {}
    roles = user.get("roles") or []
    role = roles[0] if roles else "Staff"

    # if you have branding in container, pass it; otherwise keep safe defaults
    branding = getattr(c, "branding", None)

    return render_template(
        "admin.html",
        tenant=c.settings.BUSINESS_KEY,
        role=role,
        session_id=user.get("id") or "",
        branding=branding,
    )


# -------------------------
# Admin JSON APIs
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
