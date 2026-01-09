# routes/admin_routes.py
from __future__ import annotations

import secrets
from flask import Blueprint, render_template, request, redirect, url_for, session

from routes import get_container

bp = Blueprint("admin_ui", __name__, url_prefix="/admin")


def _is_logged_in() -> bool:
    return bool(session.get("user"))


def _csrf_token() -> str:
    """
    Supports either:
    - csrf_token stored on flask.g by middleware, OR
    - csrf_token stored in session
    """
    try:
        from flask import g  # type: ignore
        token = getattr(g, "csrf_token", None)
        if token:
            return token
    except Exception:
        pass
    return session.get("csrf_token", "") or ""


def _get_tenant() -> str:
    """
    Tenant selection priority:
    1) query param ?tenant=
    2) saved in session
    3) fallback "default"
    """
    t = (request.args.get("tenant") or "").strip()
    if t:
        session["tenant"] = t
        return t
    return (session.get("tenant") or "default").strip() or "default"


def _get_role(user: dict) -> str:
    """
    Normalizes role for template checks.
    Your templates use: ['Owner','Manager','Staff']
    """
    roles = user.get("roles") or []
    if isinstance(roles, str):
        roles = [roles]
    roles = [r for r in roles if r]

    # map legacy roles to display roles if needed
    # (keep admin as Owner so UI buttons show up)
    r0 = (roles[0] if roles else "Owner").strip()

    if r0.lower() in ("admin", "owner"):
        return "Owner"
    if r0.lower() in ("manager",):
        return "Manager"
    if r0.lower() in ("staff", "support"):
        return "Staff"
    return r0 or "Owner"


def _ensure_session_id() -> str:
    """
    Used by frontend to associate dashboard session.
    """
    sid = session.get("admin_session_id")
    if not sid:
        sid = secrets.token_urlsafe(16)
        session["admin_session_id"] = sid
    return sid


@bp.get("/")
def dashboard():
    if not _is_logged_in():
        # preserve tenant in redirect
        tenant = _get_tenant()
        return redirect(url_for("admin_ui.login_page", tenant=tenant))

    user = session.get("user") or {}
    tenant = _get_tenant()
    role = _get_role(user)
    session_id = _ensure_session_id()

    # branding is optional (template handles missing)
    branding = None

    return render_template(
        "dashboard.html",
        tenant=tenant,
        role=role,
        session_id=session_id,
        branding=branding,
        csrf_token=_csrf_token(),
    )


@bp.get("/login")
def login_page():
    tenant = _get_tenant()

    if _is_logged_in():
        return redirect(url_for("admin_ui.dashboard", tenant=tenant))

    return render_template(
        "login.html",
        error=None,
        tenant=tenant,
        csrf_token=_csrf_token(),
    )


@bp.post("/login")
def login_submit():
    tenant = _get_tenant()

    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    totp = (request.form.get("totp") or "").strip() or None

    if not email or not password:
        return render_template(
            "login.html",
            error="Missing email or password",
            tenant=tenant,
            csrf_token=_csrf_token(),
        ), 400

    c = get_container()
    from service.security import authenticate_user, verify_totp

    # authenticate_user must accept (container, email=..., password=...)
    user = authenticate_user(c, email=email, password=password)

    if not user:
        return render_template(
            "login.html",
            error="Invalid credentials",
            tenant=tenant,
            csrf_token=_csrf_token(),
        ), 401

    # Optional TOTP
    if user.get("totp_secret"):
        if not totp or not verify_totp(user["totp_secret"], totp):
            return render_template(
                "login.html",
                error="TOTP required (check your authenticator code)",
                tenant=tenant,
                csrf_token=_csrf_token(),
            ), 401

    session["user"] = {
        "id": user.get("id", "admin"),
        "email": user.get("email", email),
        "roles": user.get("roles", ["Owner"]),
        # Optional: save tenant on user if you want server-side tenant enforcement later
        # "tenant": tenant,
    }

    _ensure_session_id()

    return redirect(url_for("admin_ui.dashboard", tenant=tenant))


@bp.get("/logout")
def logout():
    tenant = _get_tenant()
    session.pop("user", None)
    session.pop("admin_session_id", None)
    return redirect(url_for("admin_ui.login_page", tenant=tenant))
