# routes/auth_routes.py
from __future__ import annotations

from flask import Blueprint, request, jsonify, session, redirect, url_for

from routes import get_container

# IMPORTANT:
# Blueprint "name" must be UNIQUE across the entire Flask app.
# Using "auth_api_v1" avoids collisions like: "auth_routes already registered".
bp = Blueprint("auth_api_v1", __name__, url_prefix="/auth")


@bp.get("/login")
def login_get():
    # Never show JSON login page in browser
    return redirect(url_for("admin_routes.admin_login_page"))


@bp.post("/login")
def login_post():
    c = get_container()

    # Only accept JSON here. If a browser posts a form here by accident,
    # redirect them to the proper admin login page.
    if not request.is_json:
        return redirect(url_for("admin_routes.admin_login_page"))

    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "").strip()
    totp = (data.get("totp") or "").strip() or None

    # Use the correct package path: services.security (NOT service.security)
    from services.security import authenticate_user, verify_totp

    # Your services.security.authenticate_user requires container as first arg
    user = authenticate_user(c, email=email, password=password, totp_code=totp)
    if not user:
        return jsonify({"ok": False, "error": "invalid_credentials"}), 401

    # Store minimal session user
    session["user"] = {
        "email": user.get("email"),
        "roles": user.get("roles", []),
    }

    return jsonify({"ok": True, "user": session["user"]})


@bp.post("/logout")
def logout():
    session.pop("user", None)
    return jsonify({"ok": True})
