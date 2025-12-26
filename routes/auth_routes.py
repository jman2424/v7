from __future__ import annotations

from flask import Blueprint, request, jsonify, session, redirect, url_for, render_template
from routes import get_container

bp = Blueprint("auth", __name__, url_prefix="/auth")


def _wants_json() -> bool:
    accept = (request.headers.get("Accept") or "").lower()
    ctype = (request.headers.get("Content-Type") or "").lower()
    return "application/json" in accept or "application/json" in ctype or request.is_json


@bp.get("/login")
def login_get():
    """
    Browsing /auth/login should not be a thing in Option A.
    Redirect users to the real HTML login page.
    """
    return redirect(url_for("admin.admin_login_page"), code=302)


@bp.post("/login")
def login_post():
    """
    Supports BOTH:
    - HTML form POST (application/x-www-form-urlencoded) -> sets session -> redirect to /admin/
    - JSON POST -> returns JSON {ok: true}
    """

    c = get_container()

    if request.is_json:
        data = request.get_json(silent=True) or {}
        email = (data.get("email") or data.get("username") or "").strip().lower()
        password = data.get("password") or ""
        totp = (data.get("totp") or data.get("totp_code") or "").strip()
    else:
        # HTML form fields (match your login.html)
        email = (request.form.get("email") or request.form.get("username") or "").strip().lower()
        password = request.form.get("password") or ""
        totp = (request.form.get("totp") or request.form.get("totp_code") or "").strip()

    from service.security import authenticate_user, verify_totp  # adjust import to your repo

    user = authenticate_user(email=email, password=password)
    if not user:
        if _wants_json():
            return jsonify({"ok": False, "error": "invalid_credentials"}), 401
        return render_template("login.html", error="Invalid username/password"), 401

    # If user has TOTP enabled, require it
    if user.get("totp_secret"):
        if not totp or not verify_totp(user["totp_secret"], totp):
            if _wants_json():
                return jsonify({"ok": False, "error": "totp_required"}), 401
            return render_template("login.html", error="TOTP code required/invalid"), 401

    # Store minimal session payload
    session["user"] = {
        "id": user["id"],
        "email": user["email"],
        "roles": user.get("roles", []),
    }

    # Option A: browser login -> redirect to admin
    if not _wants_json():
        return redirect(url_for("admin.admin_home"), code=302)

    return jsonify({"ok": True, "user": session["user"]})


@bp.get("/logout")
def logout_get():
    session.pop("user", None)
    return redirect(url_for("admin.admin_login_page"), code=302)


@bp.post("/logout")
def logout_post():
    session.pop("user", None)
    return jsonify({"ok": True})
