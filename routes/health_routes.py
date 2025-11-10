from __future__ import annotations
from flask import Blueprint, current_app, jsonify
from app.config import Settings

bp = Blueprint("health", __name__)

@bp.get("/health")
def health():
    # lightweight liveness
    return "ok", 200, {"Content-Type": "text/plain; charset=utf-8"}

@bp.get("/version")
def version():
    s: Settings = current_app.config.get("SETTINGS") or getattr(current_app, "container").settings
    info = {
        "mode": s.MODE,
        "tenant": s.BUSINESS_KEY,
    }
    return jsonify(info)

@bp.get("/ready")
def ready():
    # you can add deeper checks (catalog loaded, etc.)
    try:
        c = getattr(current_app, "container")
        _ = c.catalog.count_items() if hasattr(c.catalog, "count_items") else True
        return jsonify({"ready": True}), 200
    except Exception as e:
        current_app.logger.error(f"Readiness check failed: {e}")
        return jsonify({"ready": False, "error": str(e)}), 503
