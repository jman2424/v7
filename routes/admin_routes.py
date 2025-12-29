# routes/admin_routes.py
from __future__ import annotations

from flask import Blueprint, request, jsonify, render_template, redirect, url_for, session
from routes import get_container, require_auth

bp = Blueprint("admin", __name__, url_prefix="/admin")

# ---------- Pages ----------

@bp.get("/login")
def admin_login_page():
    # CSRF token comes from session (middleware ensures it exists)
    csrf_token = session.get("csrf_token", "")
    return render_template("login.html", csrf_token=csrf_token, error=None)

@bp.post("/login")
def admin_login_submit():
    c = get_container()

    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    totp = (request.form.get("totp") or "").strip()

    from services.security import authenticate_user, verify_totp  # <-- make sure this path is correct in YOUR repo

    user = authenticate_user(email=email, password=password)
    if not user:
        csrf_token = session.get("csrf_token", "")
        return render_template("login.html", csrf_token=csrf_token, error="Invalid email or password"), 401

    if user.get("totp_secret"):
        if not totp or not verify_totp(user["totp_secret"], totp):
            csrf_token = session.get("csrf_token", "")
            return render_template("login.html", csrf_token=csrf_token, error="TOTP required/invalid"), 401

    # IMPORTANT: roles MUST match your require_auth decorator values
    roles = user.get("roles") or ["Owner"]  # fallback so you don’t lock yourself out during dev

    session["user"] = {
        "id": user.get("id"),
        "email": user.get("email"),
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
    return render_template(
        "admin.html",
        tenant=c.settings.BUSINESS_KEY,
        role=(session.get("user") or {}).get("roles", ["Staff"])[0],
        session_id=(session.get("user") or {}).get("id", ""),
        csrf_token=session.get("csrf_token", ""),
    )

# ---------- APIs (examples) ----------

@bp.get("/api/leads")
@require_auth(roles=("Owner", "Manager", "Staff"))
def api_leads():
    c = get_container()
    limit = int(request.args.get("limit", "50"))
    leads = c.crm.list_leads(limit=limit)
    return jsonify({"leads": leads})
