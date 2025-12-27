from __future__ import annotations

from flask import Blueprint, request, jsonify, render_template, redirect, url_for, session
from routes import get_container, require_auth

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _csrf_value() -> str:
    """
    Matches middleware expectation:
    token must equal settings.SECRET_KEY[:16]
    """
    c = get_container()
    return (c.settings.SECRET_KEY or "")[:16]


# -------- HTML pages --------

@bp.get("/login")
def admin_login_page():
    # Render login page with CSRF token
    return render_template("login.html", csrf_token=_csrf_value())

@bp.post("/login")
def admin_login_submit():
    """
    HTML form login. Sets session["user"] then redirects to /admin/.
    """
    c = get_container()

    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    totp = (request.form.get("totp") or "").strip()

    if not email or not password:
        return render_template("login.html", csrf_token=_csrf_value(), error="Missing email or password."), 400

    from services.security import authenticate_user, verify_totp

    user = authenticate_user(email=email, password=password)
    if not user:
        return render_template("login.html", csrf_token=_csrf_value(), error="Invalid credentials."), 401

    # If user has TOTP enabled, require it
    if user.get("totp_secret"):
        if not totp or not verify_totp(user["totp_secret"], totp):
            return render_template("login.html", csrf_token=_csrf_value(), error="TOTP required/invalid."), 401

    # Normalize roles (your require_auth expects Owner/Manager/Staff)
    roles = user.get("roles") or []
    session["user"] = {
        "id": user.get("id"),
        "email": user.get("email") or email,
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
    # pass whatever your admin.html expects; keep it minimal/safe
    return render_template(
        "admin.html",
        tenant=c.settings.BUSINESS_KEY,
        role=(session.get("user", {}) or {}).get("roles", ["Staff"])[0] if session.get("user") else "Staff",
        session_id=session.get("_id", ""),  # optional; ok if empty
        csrf_token=_csrf_value(),
        branding=getattr(c, "branding", None),
        tenants=[c.settings.BUSINESS_KEY],
    )


# -------- Leads / CRM --------

@bp.get("/api/leads")
@require_auth(roles=("Owner", "Manager", "Staff"))
def api_leads():
    c = get_container()
    limit = int(request.args.get("limit", "50"))
    leads = c.crm.list_leads(limit=limit)
    return jsonify({"leads": leads})


# -------- Catalog / FAQ CRUD (validated + versioned) --------

@bp.put("/api/catalog")
@require_auth(roles=("Owner", "Manager"))
def api_put_catalog():
    c = get_container()
    payload = request.get_json(force=True) or {}
    tenant = payload.get("tenant") or c.settings.BUSINESS_KEY
    catalog = payload.get("catalog")
    if not isinstance(catalog, dict):
        return jsonify({"ok": False, "error": "invalid_catalog"}), 400

    snap = c.storage.write_json(tenant, "catalog.json", catalog, schema="schemas/catalog.schema.json")
    c.analytics.emit_admin_event("catalog.update", tenant=tenant)
    return jsonify({"ok": True, "snapshot_path": snap})


@bp.put("/api/faq")
@require_auth(roles=("Owner", "Manager"))
def api_put_faq():
    c = get_container()
    payload = request.get_json(force=True) or {}
    tenant = payload.get("tenant") or c.settings.BUSINESS_KEY
    faq = payload.get("faq")
    if not isinstance(faq, list):
        return jsonify({"ok": False, "error": "invalid_faq"}), 400

    snap = c.storage.write_json(tenant, "faq.json", faq, schema="schemas/faq.schema.json")
    c.analytics.emit_admin_event("faq.update", tenant=tenant)
    return jsonify({"ok": True, "snapshot_path": snap})


@bp.put("/api/delivery")
@require_auth(roles=("Owner", "Manager"))
def api_put_delivery():
    c = get_container()
    payload = request.get_json(force=True) or {}
    tenant = payload.get("tenant") or c.settings.BUSINESS_KEY
    delivery = payload.get("delivery")
    if not isinstance(delivery, dict):
        return jsonify({"ok": False, "error": "invalid_delivery"}), 400

    snap = c.storage.write_json(tenant, "delivery.json", delivery, schema="schemas/delivery.schema.json")
    c.analytics.emit_admin_event("delivery.update", tenant=tenant)
    return jsonify({"ok": True, "snapshot_path": snap})


# -------- Audit log view --------

@bp.get("/api/audit")
@require_auth(roles=("Owner", "Manager"))
def api_audit():
    c = get_container()
    items = c.storage.list_audit_entries(c.settings.BUSINESS_KEY)
    return jsonify({"audit": items})


# -------- Analytics summaries --------

@bp.get("/api/summary")
@require_auth(roles=("Owner", "Manager", "Staff"))
def api_summary():
    c = get_container()
    summary = c.analytics.summary(c.settings.BUSINESS_KEY)
    return jsonify(summary)
