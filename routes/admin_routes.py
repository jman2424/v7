from __future__ import annotations

from functools import wraps
from flask import Blueprint, request, session, redirect, url_for, render_template

from routes import get_container

bp = Blueprint("admin_ui", __name__, url_prefix="/admin")


def _is_logged_in() -> bool:
    return bool(session.get("user"))


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not _is_logged_in():
            return redirect(url_for("admin_ui.login_page"))
        return fn(*args, **kwargs)

    return wrapper


@bp.get("/")
@login_required
def admin_home():
    # If you have a dashboard template, use it. Otherwise keep it simple.
    # Change "dashboard.html" to whatever you actually have.
    return render_template("dashboard.html")


@bp.get("/login")
def login_page():
    # Change "login.html" to your actual template file name in dashboard/templates
    return render_template("login.html")


@bp.post("/login")
def login_submit():
    c = get_container()

    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    totp = (request.form.get("totp") or "").strip() or None

    from service.security import authenticate_user, verify_totp

    user = authenticate_user(c, email=email, password=password)
    if not user:
        # simplest: bounce back (you can add flash() later)
        return redirect(url_for("admin_ui.login_page"))

    if user.get("totp_secret"):
        if not totp or not verify_totp(user["totp_secret"], totp):
            return redirect(url_for("admin_ui.login_page"))

    session["user"] = {
        "id": user["id"],
        "email": user["email"],
        "roles": user.get("roles", []),
    }
    return redirect(url_for("admin_ui.admin_home"))


@bp.post("/logout")
def logout_submit():
    session.pop("user", None)
    return redirect(url_for("admin_ui.login_page"))
