# routes/admin_routes.py
from __future__ import annotations

from flask import Blueprint, render_template, request, redirect, url_for, session
from routes import get_container

bp = Blueprint("admin_ui", __name__, url_prefix="/admin")


def _is_logged_in() -> bool:
    return bool(session.get("user"))


def _csrf_token() -> str:
    try:
        from flask import g  # type: ignore
        tok = getattr(g, "csrf_token", None)
        if tok:
            return tok
    except Exception:
        pass
    return session.get("csrf_token", "") or ""


def _tenant() -> str:
    t = (request.args.get("tenant") or "").strip()
    if t:
        return t
    c = get_container()
    return (str(getattr(c.settings, "BUSINESS_KEY", "") or "").strip() or "default")


def _redirect(endpoint: str, **kwargs):
    kwargs.setdefault("tenant", _tenant())
    return redirect(url_for(endpoint, **kwargs))


@bp.get("/")
def dashboard():
    if not _is_logged_in():
        return _redirect("admin_ui.login_page")

    user = session.get("user") or {}
    role = (user.get("roles") or ["admin"])[0]
    session_id = session.get("admin_session_id") or user.get("id") or "admin"

    return render_template(
        "dashboard.html",
        tenant=_tenant(),
        role=role,
        session_id=session_id,
        branding=None,
        csrf_token=_csrf_token(),
        version="7",
    )


@bp.get("/login")
def login_page():
    if _is_logged_in():
        return _redirect("admin_ui.dashboard")

    return render_template(
        "login.html",
        tenant=_tenant(),
        error=None,
        csrf_token=_csrf_token(),
    )


@bp.post("/login")
def login_submit():
    tenant = _tenant()
    identifier = (request.form.get("email") or request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    totp_code = (request.form.get("totp") or "").strip()

    if not identifier or not password:
        return (
            render_template(
                "login.html",
                tenant=tenant,
                error="Missing email/username or password",
                csrf_token=_csrf_token(),
            ),
            400,
        )

    from service.security import authenticate_user, verify_totp

    c = get_container()

    # ✅ IMPORTANT: your authenticate_user signature is (c, *, email=, password=)
    user = authenticate_user(c, email=identifier, password=password)
    if not user:
        return (
            render_template(
                "login.html",
                tenant=tenant,
                error="Invalid credentials",
                csrf_token=_csrf_token(),
            ),
            401,
        )

    secret = user.get("totp_secret") or ""
    if not verify_totp(secret, totp_code):
        return (
            render_template(
                "login.html",
                tenant=tenant,
                error="Invalid TOTP code",
                csrf_token=_csrf_token(),
            ),
            401,
        )

    # ✅ store tenant in session so admin_api defaults correctly
    user["tenant"] = tenant
    session["user"] = user
    session["admin_session_id"] = user.get("id") or "admin"

    return _redirect("admin_ui.dashboard")


@bp.get("/logout")
def logout():
    session.pop("user", None)
    session.pop("admin_session_id", None)
    return _redirect("admin_ui.login_page")
