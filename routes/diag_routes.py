# routes/diag_routes.py
from __future__ import annotations

import os
from flask import Blueprint, jsonify, request, current_app
from routes import get_container, require_auth

bp = Blueprint("diag", __name__, url_prefix="/__diag")


def _run_report():
    c = get_container()
    from service.self_repair import run_diagnostics
    report = run_diagnostics(c.storage, c.catalog, c.policy, c.geo, c.synonyms)
    return jsonify({"ok": True, "report": report})


@bp.get("/selfrepair")
@require_auth(roles=("Owner", "Manager"))
def selfrepair_report():
    return _run_report()


@bp.get("/self_repair")  # ✅ alias your dashboard was calling
@require_auth(roles=("Owner", "Manager"))
def self_repair_alias():
    return _run_report()


@bp.post("/apply-fixes")
@require_auth(roles=("Owner", "Manager"))
def apply_fixes():
    c = get_container()
    data = request.get_json(force=True) or {}
    fixes = data.get("fixes") or []
    dry = bool(data.get("dry_run", True))

    from service.self_repair import apply_fixes as apply
    result = apply(c.storage, c.settings.BUSINESS_KEY, fixes, dry_run=dry)
    return jsonify(result)


@bp.get("/validate")
@require_auth(roles=("Owner", "Manager", "Staff", "admin"))
def validate_all():
    c = get_container()
    res = c.storage.validate_tenant(c.settings.BUSINESS_KEY)
    return jsonify({"ok": True, "validation": res})


@bp.get("/catalog_env")
@require_auth(roles=("Owner", "Manager", "admin"))
def catalog_env():
    info = {
        "CATALOG_WEBHOOK_SECRET_present": bool(os.getenv("CATALOG_WEBHOOK_SECRET")),
        "CATALOG_WEBHOOK_DISABLE_HMAC_raw": os.getenv("CATALOG_WEBHOOK_DISABLE_HMAC"),
        "CATALOG_FILE": os.getenv("CATALOG_FILE"),
    }
    current_app.logger.info("Diag catalog_env: %r", info)
    return jsonify(info), 200
