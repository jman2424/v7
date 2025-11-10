from __future__ import annotations
from flask import Blueprint, request, jsonify, session
from routes import get_container

bp = Blueprint("auth", __name__, url_prefix="/auth")

@bp.post("/login")
def login():
    """
    Body: { "email": "", "password": "", "totp": "123456"? }
    On success: sets session['user'] = {...}
    """
    c = get_container()
    data = request.get_json(force=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    totp = data.get("totp")
    from services.security import authenticate_user, verify_totp

    user = authenticate_user(email=email, password=password)
    if not user:
        return jsonify({"ok": False, "error": "invalid_credentials"}), 401

    # If user has TOTP enabled, require it
    if user.get("totp_secret"):
        if not totp or not verify_totp(user["totp_secret"], totp):
            return jsonify({"ok": False, "error": "totp_required"}), 401

    session["user"] = {"id": user["id"], "email": user["email"], "roles": user.get("roles", [])}
    return jsonify({"ok": True, "user": session["user"]})

@bp.post("/logout")
def logout():
    session.pop("user", None)
    return jsonify({"ok": True})

@bp.post("/totp/bootstrap")
def totp_bootstrap():
    """
    Returns provisioning URI for Authenticator apps.
    """
    c = get_container()
    from services.security import bootstrap_totp, current_user_or_401
    user = current_user_or_401()
    uri = bootstrap_totp(user)
    return jsonify({"ok": True, "provisioning_uri": uri})

@bp.post("/password/reset")
def password_reset():
    data = request.get_json(force=True) or {}
    email = (data.get("email") or "").strip().lower()
    # You can integrate with connectors.emailer here
    return jsonify({"ok": True, "message": f"If {email} exists, a reset link will be sent."})
