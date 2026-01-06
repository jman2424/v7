from __future__ import annotations

from flask import Blueprint, request, jsonify, session, redirect, url_for

from routes import get_container

bp = Blueprint("auth_api", __name__, url_prefix="/auth")


@bp.get("/login")
def login_get():
    # Never show JSON login page in browser
    return redirect(url_for("admin_ui.login_page"))


@bp.post("/login")
def login_post():
    c = get_container()

    if not request.is_json:
        # if someone posts a form here by accident, send them back to /admin/login
        return redirect(url_for("admin_ui.login_page"))

    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    totp = (data.get("totp") or "").strip() or None

    # IMPORTANT: your folder is "service", not "services"
    from service.security import authenticate_user, verify_totp

    user = authenticate_user(c, email=email, password=password)
    if not user:
        return jsonify({"ok": False, "error": "invalid_credentials"}), 401

    if user.get("totp_secret"):
        if not totp or not verify_totp(user["totp_secret"], totp):
            return jsonify({"ok": False, "error": "totp_required"}), 401

    session["user"] = {
        "id": user["id"],
        "email": user["email"],
        "roles": user.get("roles", []),
    }
    return jsonify({"ok": True, "user": session["user"]})


@bp.post("/logout")
def logout():
    session.pop("user", None)
    return jsonify({"ok": True})
