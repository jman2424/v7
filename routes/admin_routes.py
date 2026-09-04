# routes/admin_routes.py
from __future__ import annotations

from flask import Blueprint, abort, current_app, render_template, request, redirect, url_for, session
from routes import get_container
from routes.session_auth import clear_authenticated_session, establish_authenticated_session
from routes.tenancy import resolve_admin_tenant
from retrieval.storage import Storage

bp = Blueprint("admin_ui", __name__, url_prefix="/admin")


def _is_logged_in() -> bool:
    return bool(session.get("user"))


def _csrf_token() -> str:
    return session.get("_csrf", "") or ""


def _tenant() -> str:
    t = (request.args.get("tenant") or "").strip()
    if t:
        if session.get("user"):
            c = get_container()
            return resolve_admin_tenant(t, str(getattr(c.settings, "BUSINESS_KEY", "") or "default"))
        try:
            return Storage.validate_tenant_key(t)
        except ValueError:
            abort(400, description="invalid_tenant")
    c = get_container()
    default_tenant = str(getattr(c.settings, "BUSINESS_KEY", "") or "").strip() or "default"
    if session.get("user"):
        return resolve_admin_tenant("", default_tenant)
    return default_tenant


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


@bp.get("/widget")
def widget_settings():
    if not _is_logged_in():
        return _redirect("admin_ui.login_page")

    user = session.get("user") or {}
    role = (user.get("roles") or [user.get("role") or "business_owner"])[0]
    return render_template(
        "widget_settings.html",
        tenant=_tenant(),
        role=role,
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

    limiter = current_app.extensions["auth_login_limiter"]
    attempt_key = limiter.key(client_address=request.remote_addr or "unknown", tenant=tenant, identifier=identifier)
    if limiter.retry_after(attempt_key):
        return (
            render_template(
                "login.html",
                tenant=tenant,
                error="Too many sign-in attempts. Please try again later.",
                csrf_token=_csrf_token(),
            ),
            429,
        )

    from service.security import authenticate_user, verify_totp

    c = get_container()

    # ✅ IMPORTANT: your authenticate_user signature is (c, *, email=, password=)
    user = authenticate_user(c, email=identifier, password=password, tenant=tenant)
    if not user:
        limiter.record_failure(attempt_key)
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
        limiter.record_failure(attempt_key)
        return (
            render_template(
                "login.html",
                tenant=tenant,
                error="Invalid credentials",
                csrf_token=_csrf_token(),
            ),
            401,
        )

    limiter.reset(attempt_key)
    identity = establish_authenticated_session(user, tenant)
    session["admin_session_id"] = identity["id"]

    return _redirect("admin_ui.dashboard")


@bp.post("/logout")
def logout():
    clear_authenticated_session()
    return _redirect("admin_ui.login_page")
