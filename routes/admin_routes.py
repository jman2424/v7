# routes/admin_routes.py
from __future__ import annotations

from functools import wraps
from secrets import token_urlsafe

from flask import Blueprint, request, session, redirect, url_for, render_template
from routes import get_container

# This name MUST match what your template uses in url_for("admin_routes....")
bp = Blueprint("admin_routes", __name__, url_prefix="/admin")


def _ensure_csrf_token() -> str:
    """
    Your CSRF middleware may already manage tokens.
    This guarantees a token exists so the template can include it.
    """
    tok = session.get("csrf_token")
    if not tok:
        tok = token_urlsafe(32)
        session["csrf_token"] = tok
    return tok


def _is_logged_in() -> bool:
    return bool(session.get("user"))


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not _is_logged_in():
            return redirect(url_for("admin_routes.admin_login_page"))
        return fn(*args, **kwargs)

    return wrapper


@bp.get("/")
def admin_root():
    # Always redirect /admin/ to either dashboard or login
    if _is_logged_in():
        return redirect(url_for("admin_routes.dashboard"))
    return redirect(url_for("admin_routes.admin_login_page"))


@bp.get("/login")
def admin_login_page():
    csrf = _ensure_csrf_token()
    # Pass csrf into the template so you can add it as a hidden field
    return render_template("login.html", csrf_token=csrf)


@bp.post("/login")
def admin_login_submit():
    c = get_container()

    # --- CSRF check (simple, works even if your middleware is strict) ---
    # If your middleware already blocks before reaching here, you must
    # update the template to include csrf_token (next section).
    form_csrf = (request.form.get("csrf_token") or "").strip()
    sess_csrf = (session.get("csrf_token") or "").strip()
    if not sess_csrf or not form_csrf or form_csrf != sess_csrf:
        # refresh token + bounce back
        _ensure_csrf_token()
        return redirect(url_for("admin_routes.admin_login_page"))

    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    totp = (request.form.get("totp") or "").strip() or None

    from service.security import authenticate_user, verify_totp

    user = authenticate_user(c, email=email, password=password)
    if not user:
        return redirect(url_for("admin_routes.admin_login_page"))

    if user.get("totp_secret"):
        if not totp or not verify_totp(user["totp_secret"], totp):
            return redirect(url_for("admin_routes.admin_login_page"))

    session["user"] = {"id": user["id"], "email": user["email"], "roles": user.get("roles", [])}
    return redirect(url_for("admin_routes.dashboard"))


@bp.post("/logout")
def admin_logout_submit():
    session.pop("user", None)
    return redirect(url_for("admin_routes.admin_login_page"))


@bp.get("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html")
