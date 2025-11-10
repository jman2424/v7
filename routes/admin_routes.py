from __future__ import annotations
import json
from flask import Blueprint, request, jsonify, render_template
from routes import get_container, require_auth

bp = Blueprint("admin", __name__, url_prefix="/admin")

# -------- HTML pages --------

@bp.get("/")
@require_auth(roles=("Owner","Manager","Staff"))
def admin_home():
    c = get_container()
    return render_template("admin.html", tenant=c.settings.BUSINESS_KEY)

@bp.get("/login")
def admin_login_page():
    return render_template("login.html")

# -------- Session / Auth JSON --------
# Auth flows are implemented in routes/auth_routes.py (login, TOTP, etc.)
# This file focuses on Admin APIs.

# -------- Leads / CRM --------

@bp.get("/api/leads")
@require_auth(roles=("Owner","Manager","Staff"))
def api_leads():
    c = get_container()
    limit = int(request.args.get("limit", "50"))
    leads = c.crm.list_leads(limit=limit)
    return jsonify({"leads": leads})

# -------- Catalog / FAQ CRUD (validated + versioned) --------

@bp.put("/api/catalog")
@require_auth(roles=("Owner","Manager"))
def api_put_catalog():
    c = get_container()
    payload = request.get_json(force=True) or {}
    tenant = payload.get("tenant") or c.settings.BUSINESS_KEY
    catalog = payload.get("catalog")
    if not isinstance(catalog, dict):
        return jsonify({"ok": False, "error": "invalid_catalog"}), 400

    # Schema validation + snapshot handled by storage
    snap = c.storage.write_json(tenant, "catalog.json", catalog, schema="schemas/catalog.schema.json")
    c.analytics.emit_admin_event("catalog.update", tenant=tenant)
    return jsonify({"ok": True, "snapshot_path": snap})

@bp.put("/api/faq")
@require_auth(roles=("Owner","Manager"))
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
@require_auth(roles=("Owner","Manager"))
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
@require_auth(roles=("Owner","Manager"))
def api_audit():
    c = get_container()
    items = c.storage.list_audit_entries(c.settings.BUSINESS_KEY)
    return jsonify({"audit": items})

# -------- Analytics summaries (delegates to analytics_routes for heavy) --------

@bp.get("/api/summary")
@require_auth(roles=("Owner","Manager","Staff"))
def api_summary():
    c = get_container()
    summary = c.analytics.summary(c.settings.BUSINESS_KEY)
    return jsonify(summary)
