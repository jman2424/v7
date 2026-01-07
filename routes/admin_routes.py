# routes/admin_routes.py
from __future__ import annotations

from flask import Blueprint, render_template, request, redirect, url_for, session
from routes import get_container

bp = Blueprint("admin_ui", __name__, url_prefix="/admin")


def _is_logged_in() -> bool:
    return bool(session.get("user"))


def _csrf_token() -> str:
    # Your csrf middleware likely stores token in g or session.
    # This keeps templates happy either way.
    try:
        from flask import g  # type: ignore
        token = getattr(g, "csrf_token", None)
        if token:
            return token
    except Exception:
        pass
    return session.get("csrf_token", "") or ""


@bp.get("/")
def dashboard():
    if not _is_logged_in():
        return redirect(url_for("admin_ui.login_page"))

    user = session.get("user") or {}
    role = (user.get("roles") or ["admin"])[0]

    return render_template(
        "dashboard.html",
        role=role,
        csrf_token=_csrf_token(),
    )


@bp.get("/login")
def login_page():
    if _is_logged_in():
        return redirect(url_for("admin_ui.dashboard"))

    return render_template(
        "login.html",
        error=None,
        csrf_token=_csrf_token(),
    )


@bp.post("/login")
def login_submit():
    # Form POST from login.html
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    totp = (request.form.get("totp") or "").strip() or None

    if not email or not password:
        return render_template(
            "login.html",
            error="Missing email or password",
            csrf_token=_csrf_token(),
        ), 400

    c = get_container()

    from service.security import authenticate_user, verify_totp

    user = authenticate_user(c, email=email, password=password)
    if not user:
        return render_template(
            "login.html",
            error="Invalid credentials",
            csrf_token=_csrf_token(),
        ), 401

    if user.get("totp_secret"):
        if not totp or not verify_totp(user["totp_secret"], totp):
            return render_template(
                "login.html",
                error="TOTP required (check your authenticator code)",
                csrf_token=_csrf_token(),
            ), 401

    session["user"] = {
        "id": user["id"],
        "email": user["email"],
        "roles": user.get("roles", []),
    }

    return redirect(url_for("admin_ui.dashboard"))


@bp.get("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("admin_ui.login_page"))
