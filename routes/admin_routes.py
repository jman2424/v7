from __future__ import annotations

from flask import Blueprint, request, jsonify, render_template, session
from routes import get_container, require_auth

bp = Blueprint("admin_routes", __name__, url_prefix="/admin")


@bp.get("/login")
def admin_login_page():
    # Render login page; csrf_token stored in session by middleware GET handler
    error = request.args.get("error")
    return render_template("login.html", error=error, csrf_token=session.get("csrf_token", ""))


@bp.get("/")
@require_auth(roles=("Owner", "Manager", "Staff"))
def admin_home():
    c = get_container()
    return render_template(
        "admin.html",
        tenant=c.settings.BUSINESS_KEY,
        role=(session.get("user", {}) or {}).get("roles", ["Staff"])[0],
        session_id=(session.get("user", {}) or {}).get("id", ""),
        csrf_token=session.get("csrf_token", ""),
    )


@bp.get("/api/leads")
@require_auth(roles=("Owner", "Manager", "Staff"))
def api_leads():
    c = get_container()
    limit = int(request.args.get("limit", "50"))
    leads = c.crm.list_leads(limit=limit)
    return jsonify({"leads": leads})


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


@bp.get("/api/audit")
@require_auth(roles=("Owner", "Manager"))
def api_audit():
    c = get_container()
    items = c.storage.list_audit_entries(c.settings.BUSINESS_KEY)
    return jsonify({"audit": items})


@bp.get("/api/summary")
@require_auth(roles=("Owner", "Manager", "Staff"))
def api_summary():
    c = get_container()
    summary = c.analytics.summary(c.settings.BUSINESS_KEY)
    return jsonify(summary)
