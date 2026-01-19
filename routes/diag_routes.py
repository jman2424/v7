# routes/diag_routes.py
from __future__ import annotations

import os
from flask import Blueprint, jsonify, request, current_app

from routes import get_container, require_auth

bp = Blueprint("diag", __name__, url_prefix="/__diag")


@bp.get("/selfrepair")
@require_auth(roles=("Owner", "Manager"))
def selfrepair_report():
    """
    Run self-repair diagnostics across catalog/policy/geo/synonyms.
    """
    c = get_container()
    from service.self_repair import run_diagnostics

    report = run_diagnostics(c.storage, c.catalog, c.policy, c.geo, c.synonyms)
    return jsonify({"ok": True, "report": report})


# ✅ alias for the UI typo / mismatch
@bp.get("/self_repair")
@require_auth(roles=("Owner", "Manager"))
def self_repair_alias():
    return selfrepair_report()


@bp.post("/apply-fixes")
@require_auth(roles=("Owner", "Manager"))
def apply_fixes():
    """
    Body: { fixes: [{file, path, value}], dry_run: bool }
    Applies self-repair fixes to the tenant's data files.
    """
    c = get_container()
    data = request.get_json(force=True) or {}
    fixes = data.get("fixes") or []
    dry = bool(data.get("dry_run", True))

    from service.self_repair import apply_fixes as apply

    result = apply(c.storage, c.settings.BUSINESS_KEY, fixes, dry_run=dry)
    return jsonify(result)


@bp.get("/validate")
@require_auth(roles=("Owner", "Manager", "Staff"))
def validate_all():
    """
    Validate the tenant's data (JSON schemas, catalogs, etc.).
    """
    c = get_container()
    res = c.storage.validate_tenant(c.settings.BUSINESS_KEY)
    return jsonify({"ok": True, "validation": res})


@bp.get("/catalog_env")
@require_auth(roles=("Owner", "Manager"))
def catalog_env():
    """
    Quick env sanity check for the catalog webhook integration.
    """
    info = {
        "CATALOG_WEBHOOK_SECRET_present": bool(os.getenv("CATALOG_WEBHOOK_SECRET")),
        "CATALOG_WEBHOOK_DISABLE_HMAC_raw": os.getenv("CATALOG_WEBHOOK_DISABLE_HMAC"),
        "CATALOG_FILE": os.getenv("CATALOG_FILE"),
    }
    current_app.logger.info("Diag catalog_env: %r", info)
    return jsonify(info), 200
