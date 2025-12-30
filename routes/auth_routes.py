from __future__ import annotations

from flask import Blueprint, request, jsonify, session, redirect, url_for

from routes import get_container

bp = Blueprint("auth", __name__, url_prefix="/auth")


@bp.post("/login")
def login():
    """
    Supports:
    - HTML form POST from /admin/login
    - JSON POST from API clients

    On success:
      session["user"] = {"id": ..., "email": ..., "roles": [...]}
    """
    _ = get_container()

    is_json = request.is_json

    if is_json:
        data = request.get_json(silent=True) or {}
        email = (data.get("email") or "").strip().lower()
        password = data.get("password") or ""
        totp = data.get("totp") or None
    else:
        email = (request.form.get("email") or request.form.get("username") or "").strip().lower()
        password = request.form.get("password") or ""
        totp = request.form.get("totp") or request.form.get("totp_code") or None

    from services.security import authenticate_user, verify_totp

    user = authenticate_user(email=email, password=password)
    if not user:
        if is_json:
            return jsonify({"ok": False, "error": "invalid_credentials"}), 401
        return redirect(url_for("admin_routes.admin_login", error="invalid_credentials"))

    if user.get("totp_secret"):
        if not totp or not verify_totp(user["totp_secret"], totp):
            if is_json:
                return jsonify({"ok": False, "error": "totp_required"}), 401
            return redirect(url_for("admin_routes.admin_login", error="totp_required"))

    session["user"] = {
        "id": user["id"],
        "email": user["email"],
        "roles": user.get("roles", []),
    }

    if is_json:
        return jsonify({"ok": True, "user": session["user"]})

    return redirect(url_for("admin_routes.admin_home"))


@bp.get("/logout")
def logout_get():
    # Browser-friendly logout without needing CSRF
    session.pop("user", None)
    return redirect(url_for("admin_routes.admin_login"))


@bp.post("/logout")
def logout_post():
    # API-friendly logout
    session.pop("user", None)
    return jsonify({"ok": True})
