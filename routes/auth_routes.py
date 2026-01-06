# routes/auth_routes.py
from __future__ import annotations

from flask import Blueprint, request, jsonify, session
from routes import get_container

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

    from service.security import authenticate_user, verify_totp

    # IMPORTANT: pass container
    user = authenticate_user(c, email=email, password=password)
    if not user:
        return jsonify({"ok": False, "error": "invalid_credentials"}), 401

    if user.get("totp_secret"):
        if not totp or not verify_totp(user["totp_secret"], totp):
            return jsonify({"ok": False, "error": "totp_required"}), 401

    session["user"] = {"id": user["id"], "email": user["email"], "roles": user.get("roles", [])}
    return jsonify({"ok": True, "user": session["user"]})


@bp.post("/logout")
def logout_post():
    session.pop("user", None)
    return jsonify({"ok": True})
