from __future__ import annotations
from flask import Blueprint, jsonify, request
from routes import get_container, require_auth

bp = Blueprint("diag", __name__, url_prefix="/__diag")

@bp.get("/selfrepair")
@require_auth(roles=("Owner","Manager"))
def selfrepair_report():
    c = get_container()
    from services.self_repair import run_diagnostics
    report = run_diagnostics(c.storage, c.catalog, c.policy, c.geo, c.synonyms)
    return jsonify({"ok": True, "report": report})

@bp.post("/apply-fixes")
@require_auth(roles=("Owner","Manager"))
def apply_fixes():
    """
    Body: { fixes: [{file, path, value}], dry_run: bool }
    """
    c = get_container()
    data = request.get_json(force=True) or {}
    fixes = data.get("fixes") or []
    dry = bool(data.get("dry_run", True))
    from services.self_repair import apply_fixes as apply
    result = apply(c.storage, c.settings.BUSINESS_KEY, fixes, dry_run=dry)
    return jsonify(result)

@bp.get("/validate")
@require_auth(roles=("Owner","Manager","Staff"))
def validate_all():
    c = get_container()
    res = c.storage.validate_tenant(c.settings.BUSINESS_KEY)
    return jsonify({"ok": True, "validation": res})
