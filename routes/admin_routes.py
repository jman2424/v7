from __future__ import annotations

from flask import Blueprint, request, jsonify, render_template, redirect, url_for, session
from routes import get_container, require_auth

bp = Blueprint("admin", __name__, url_prefix="/admin")


# -----------------
# HTML pages
# -----------------

@bp.get("/login")
def admin_login_page():
    # Your middleware can inject csrf_token into templates (see middleware fix below)
    return render_template("login.html")


@bp.post("/login")
def admin_login_submit():
    """
    Server-rendered login:
    - validates creds
    - sets session['user']
    - redirects to /admin/
    """
    c = get_container()

    email = (request.form.get("username") or request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    totp = request.form.get("totp_code") or request.form.get("totp") or ""

    from services.security import authenticate_user, verify_totp

    user = authenticate_user(email=email, password=password)
    if not user:
        return render_template("login.html", error="Invalid username or password"), 401

    if user.get("totp_secret"):
        if not totp or not verify_totp(user["totp_secret"], totp):
            return render_template("login.html", error="TOTP required / invalid code"), 401

    session["user"] = {
        "id": user["id"],
        "email": user["email"],
        "roles": user.get("roles", []),
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

    # make sure these exist even if you haven't wired branding yet
    branding = getattr(c, "branding", None)
    return render_template(
        "admin.html",
        tenant=c.settings.BUSINESS_KEY,
        role=(user.get("roles") or ["Staff"])[0],
        session_id=session.get("sid", ""),
        branding=branding,
    )


# -----------------
# Admin APIs
# -----------------

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
