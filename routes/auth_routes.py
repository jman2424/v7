from __future__ import annotations

from flask import Blueprint, request, jsonify, session, redirect, url_for

from routes import get_container

bp = Blueprint("auth", __name__, url_prefix="/auth")


def _wants_json() -> bool:
    # If fetch() or API client is calling us
    accept = (request.headers.get("Accept") or "").lower()
    return request.is_json or "application/json" in accept


@bp.get("/login")
def login_get():
    # Browsers should never land on the POST endpoint
    return redirect(url_for("admin.admin_login_page"), code=302)


@bp.post("/login")
def login():
    """
    Supports:
      - JSON: {"email": "...", "password": "...", "totp": "..."}
      - Form: username/password/totp_code from templates/login.html
    On success:
      - sets session['user'] = {...}
      - returns JSON for API callers
      - redirects to /admin/ for browser form submit
    """
    get_container()  # keep for DI side-effects / parity

    # ---- Parse input (JSON OR Form) ----
    if request.is_json:
        data = request.get_json(silent=True) or {}
        email = (data.get("email") or data.get("username") or "").strip().lower()
        password = data.get("password") or ""
        totp = data.get("totp") or data.get("totp_code")
    else:
        # HTML form submit
        email = (request.form.get("email") or request.form.get("username") or "").strip().lower()
        password = request.form.get("password") or ""
        totp = request.form.get("totp") or request.form.get("totp_code")

    from service.security import authenticate_user, verify_totp  # NOTE: your tree shows "service/", not "services/"

    user = authenticate_user(email=email, password=password)
    if not user:
        if _wants_json():
            return jsonify({"ok": False, "error": "invalid_credentials"}), 401
        return redirect(url_for("admin.admin_login_page", error="invalid_credentials"), code=302)

    # If user has TOTP enabled, require it
    if user.get("totp_secret"):
        if not totp or not verify_totp(user["totp_secret"], totp):
            if _wants_json():
                return jsonify({"ok": False, "error": "totp_required"}), 401
            return redirect(url_for("admin.admin_login_page", error="totp_required"), code=302)

    session["user"] = {
        "id": user["id"],
        "email": user["email"],
        "roles": user.get("roles", []),
    }

    if _wants_json():
        return jsonify({"ok": True, "user": session["user"]})

    # Browser flow: go to dashboard
    return redirect(url_for("admin.admin_home"), code=302)


@bp.post("/logout")
def logout():
    session.pop("user", None)
    if _wants_json():
        return jsonify({"ok": True})
    return redirect(url_for("admin.admin_login_page"), code=302)


@bp.post("/totp/bootstrap")
def totp_bootstrap():
    """
    Returns provisioning URI for Authenticator apps.
    """
    get_container()
    from service.security import bootstrap_totp, current_user_or_401

    user = current_user_or_401()
    uri = bootstrap_totp(user)
    return jsonify({"ok": True, "provisioning_uri": uri})


@bp.post("/password/reset")
def password_reset():
    # API-only for now
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    return jsonify({"ok": True, "message": f"If {email} exists, a reset link will be sent."})
