# routes/admin_routes.py
from __future__ import annotations

import inspect
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


def _call_auth(auth_fn, identifier: str, password: str):
    """
    Supports authenticate_user signatures like:
      - authenticate_user(email=..., password=...)
      - authenticate_user(identifier=..., password=...)
      - authenticate_user(email, password)
      - authenticate_user(identifier, password)
    """
    try:
        sig = inspect.signature(auth_fn)
        params = sig.parameters

        if "email" in params and "password" in params:
            return auth_fn(email=identifier, password=password)

        if "identifier" in params and "password" in params:
            return auth_fn(identifier=identifier, password=password)

        # Positional (identifier, password)
        if len(params) == 2:
            return auth_fn(identifier, password)

        # Last resort: try positional anyway
        return auth_fn(identifier, password)
    except Exception:
        # Ultra-defensive fallback
        try:
            return auth_fn(email=identifier, password=password)
        except Exception:
            try:
                return auth_fn(identifier=identifier, password=password)
            except Exception:
                return auth_fn(identifier, password)


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

    # Import the module so we can safely inspect/call
    from service import security

    auth_fn = getattr(security, "authenticate_user", None)
    verify_fn = getattr(security, "verify_totp", None)

    if not callable(auth_fn):
        return (
            render_template(
                "login.html",
                tenant=tenant,
                error="Auth misconfigured (authenticate_user missing)",
                csrf_token=_csrf_token(),
            ),
            500,
        )

    user_ok = _call_auth(auth_fn, identifier, password)

    # authenticate_user might return bool OR user dict; treat falsy as fail
    if not user_ok:
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
    if callable(verify_fn):
        try:
            if not verify_fn(totp):
                return (
                    render_template(
                        "login.html",
                        tenant=tenant,
                        error="Invalid TOTP code",
                        csrf_token=_csrf_token(),
                    ),
                    401,
                )
        except Exception:
            # If verify_totp has a different signature, fail closed with a readable error
            return (
                render_template(
                    "login.html",
                    tenant=tenant,
                    error="TOTP verification misconfigured",
                    csrf_token=_csrf_token(),
                ),
                500,
            )

    # ✅ IMPORTANT: store tenant so /admin/api defaults to the same tenant
    session["user"] = {
        "id": "admin",
        "email": identifier,
        "roles": ["admin"],
        "tenant": tenant,
    }
    session["admin_session_id"] = "admin"

    return _redirect("admin_ui.dashboard")


@bp.get("/logout")
def logout():
    session.pop("user", None)
    session.pop("admin_session_id", None)
    return _redirect("admin_ui.login_page")
