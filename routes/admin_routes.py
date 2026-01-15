# routes/admin_routes.py
from __future__ import annotations

from flask import Blueprint, render_template, request, redirect, url_for, session
from routes import get_container

bp = Blueprint("admin_ui", __name__, url_prefix="/admin")


def _is_logged_in() -> bool:
    return bool(session.get("user"))


def _csrf_token() -> str:
    # If you have CSRF middleware putting it on g, use it. Otherwise session token.
    try:
        from flask import g  # type: ignore
        tok = getattr(g, "csrf_token", None)
        if tok:
            return tok
    except Exception:
        pass
    return session.get("csrf_token", "") or ""


def _tenant() -> str:
    """
    Tenant resolution priority:
      1) URL query ?tenant=...
      2) Container settings BUSINESS_KEY
      3) 'default'
    """
    t = (request.args.get("tenant") or "").strip()
    if t:
        return t

    c = get_container()
    t2 = str(getattr(c.settings, "BUSINESS_KEY", "") or "").strip()
    return t2 or "default"


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
    totp = (request.form.get("totp") or "").strip()

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

    if not authenticate_user(username=identifier, password=password):
        return (
            render_template(
                "login.html",
                tenant=tenant,
                error="Invalid credentials",
                csrf_token=_csrf_token(),
            ),
            401,
        )

    # If TOTP is disabled verify_totp should return True
    if not verify_totp(totp):
        return (
            render_template(
                "login.html",
                tenant=tenant,
                error="Invalid TOTP code",
                csrf_token=_csrf_token(),
            ),
            401,
        )

    session["user"] = {"id": "admin", "email": identifier, "roles": ["admin"]}
    session["admin_session_id"] = "admin"

    return _redirect("admin_ui.dashboard")


@bp.get("/logout")
def logout():
    session.pop("user", None)
    session.pop("admin_session_id", None)
    return _redirect("admin_ui.login_page")
