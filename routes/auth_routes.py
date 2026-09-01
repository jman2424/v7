# routes/auth_routes.py
from __future__ import annotations

from flask import Blueprint, abort, jsonify, request, session
from routes import get_container
from retrieval.storage import Storage

# Unique blueprint name to avoid: "auth already registered"
bp = Blueprint("auth_api", __name__, url_prefix="/auth")


@bp.post("/login")
def login_post():
    c = get_container()

    if not request.is_json:
        return jsonify({"ok": False, "error": "json_required"}), 400

    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    totp = (data.get("totp") or None)
    tenant = str(data.get("tenant") or c.settings.BUSINESS_KEY).strip()
    try:
        tenant = Storage.validate_tenant_key(tenant)
        if not c.storage.tenant_dir(tenant).is_dir():
            return jsonify({"ok": False, "error": "unknown_tenant"}), 404
    except ValueError:
        return jsonify({"ok": False, "error": "invalid_tenant"}), 400

    from service.security import authenticate_user, verify_totp

    # IMPORTANT: pass container
    user = authenticate_user(c, email=email, password=password, tenant=tenant)
    if not user:
        return jsonify({"ok": False, "error": "invalid_credentials"}), 401

    if user.get("totp_secret"):
        if not totp or not verify_totp(user["totp_secret"], totp):
            return jsonify({"ok": False, "error": "totp_required"}), 401

    session["user"] = {
        "id": user["id"],
        "email": user["email"],
        "roles": user.get("roles", []),
        "tenant": str(user.get("tenant") or tenant),
    }
    return jsonify({"ok": True, "user": session["user"], "csrf_token": session.get("_csrf", "")})


@bp.get("/session")
def session_get():
    user = session.get("user")
    if not isinstance(user, dict):
        abort(401, description="unauthorized")
    return jsonify({"ok": True, "user": user, "csrf_token": session.get("_csrf", "")})


@bp.post("/logout")
def logout_post():
    session.pop("user", None)
    return jsonify({"ok": True})
