from __future__ import annotations

from flask import Blueprint, request, jsonify, session, redirect, url_for

from routes import get_container

bp = Blueprint("auth_routes", __name__, url_prefix="/auth")


@bp.get("/login")
def login_get():
    return redirect(url_for("admin_routes.admin_login_page"))


@bp.post("/login")
def login_post():
    c = get_container()
    is_json = request.is_json

    if is_json:
        data = request.get_json(silent=True) or {}
        email = (data.get("email") or "").strip().lower()
        password = data.get("password") or ""
        totp = (data.get("totp") or "").strip() or None
    else:
        return redirect(url_for("admin_routes.admin_login_page"))

    from service.security import authenticate_user  # verify_totp not needed here

    # ✅ FIX: pass container + totp_code
    user = authenticate_user(c, email=email, password=password, totp_code=totp)
    if not user:
        return jsonify({"ok": False, "error": "invalid_credentials"}), 401

    session["user"] = {"email": user["email"], "roles": user.get("roles", [])}
    return jsonify({"ok": True, "user": session["user"]})


@bp.post("/logout")
def logout():
    session.pop("user", None)
    return jsonify({"ok": True})
