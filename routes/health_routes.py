"""Liveness (/health), readiness (/ready) and an authenticated /version summary."""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from service.security import authorized_tenant, require_permission

bp = Blueprint("health", __name__)

@bp.get("/health")
def health():
    # lightweight liveness
    return "ok", 200, {"Content-Type": "text/plain; charset=utf-8"}

@bp.get("/version")
def version():
    require_permission("health.read")
    tenant = authorized_tenant(request.args.get("tenant"))
    from service.ai_mode import tenant_mode
    container = getattr(current_app, "container")
    info = {
        "mode": tenant_mode(container.for_tenant(tenant).overrides).upper(),
        "tenant": tenant,
    }
    return jsonify(info)

@bp.get("/ready")
def ready():
    # you can add deeper checks (catalog loaded, etc.)
    try:
        c = getattr(current_app, "container")
        _ = c.catalog.count_items() if hasattr(c.catalog, "count_items") else True
        return jsonify({"ready": True}), 200
    except Exception:
        current_app.logger.exception("Readiness check failed")
        return jsonify({"ready": False}), 503
