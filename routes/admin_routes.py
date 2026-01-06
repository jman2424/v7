from __future__ import annotations

from flask import Blueprint, request, jsonify, session, redirect, url_for

from routes import get_container

# IMPORTANT:
# Don't call this blueprint "auth" because you already have/had another blueprint with that name.
# Name must be unique across the entire app.
bp = Blueprint("auth_routes", __name__, url_prefix="/auth")


@bp.get("/login")
def login_get():
    # Never show JSON login page in browser
    return redirect(url_for("admin_routes.admin_login_page"))


@bp.post("/login")
def login_post():
    c = get_container()

    # Only accept JSON here (admin login form is handled by /admin/login)
    if not request.is_json:
        return redirect(url_for("admin_routes.admin_login_page"))

    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    totp = (data.get("totp") or "").strip() or None

    # Your folder is: service/security.py (NOT services/security.py)
    from service.security import authenticate_user, verify_totp

    # FIX: authenticate_user requires container as first arg (your crash)
    user = authenticate_user(c, email=email, password=password)
    if not user:
        return jsonify({"ok": False, "error": "invalid_credentials"}), 401

    # If TOTP is enabled for this user, require a valid code
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
