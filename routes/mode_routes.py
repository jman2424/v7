# routes/mode_routes.py
from __future__ import annotations

from flask import Blueprint, jsonify, request
from routes import get_container

bp = Blueprint("mode", __name__)

@bp.get("/mode")
def get_mode():
    c = get_container()
    tenant = (request.args.get("tenant") or getattr(c.settings, "BUSINESS_KEY", "default") or "default")
    mode = getattr(c.settings, "MODE", "unknown")
    return jsonify({"ok": True, "tenant": tenant, "mode": mode})
