# routes/admin_routes.py
from __future__ import annotations

import inspect
from flask import Blueprint, render_template, request, redirect, url_for, session
from routes import get_container

bp = Blueprint("admin_ui", __name__, url_prefix="/admin")


def _is_logged_in() -> bool:
    return bool(session.get("user"))


def _csrf_token() -> str:
    try:
        from flask import g  # type: ignore
        token = getattr(g, "csrf_token", None)
        if token:
            return token
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


def _call_authenticate_user(auth_fn, container, identifier: str, password: str):
    """
    Supports multiple authenticate_user signatures safely.
    Returns either:
      - dict-like user object (truthy) OR
      - True/False
    """
    try:
        sig = inspect.signature(auth_fn)
        params = list(sig.parameters.keys())

        # Common patterns we support:
        # 1) authenticate_user(c, email=..., password=...)
        if len(params) >= 3 and params[0] in {"c", "container"}:
            # keyword style
            if "email" in params:
                return auth_fn(container, email=identifier, password=password)
            if "username" in params:
                return auth_fn(container, username=identifier, password=password)
            if "identifier" in params:
                return auth_fn(container, identifier=identifier, password=password)
            # positional fallback (c, identifier, password)
            return auth_fn(container, identifier, password)

        # 2) authenticate_user(email=..., password=...)
        if "email" in params and "password" in params:
            return auth_fn(email=identifier, password=password)
        if "username" in params and "password" in params:
            return auth_fn(username=identifier, password=password)
        if "identifier" in params and "password" in params:
            return auth_fn(identifier=identifier, password=password)

        # 3) authenticate_user(email, password) or authenticate_user(username, password)
        if len(params) == 2:
            return auth_fn(identifier, password)

        # Last resort: try keyword-ish then positional
        try:
            return auth_fn(identifier=identifier, password=password)  # type: ignore
        except Exception:
            return auth_fn(identifier, password)

    except Exception:
        # If anything weird happens, do safe tries:
        try:
            return auth_fn(container, email=identifier, password=password)
        except Exception:
            try:
                return auth_fn(identifier, password)
            except Exception:
                return None


def _call_verify_totp(verify_fn, *args):
    """
    Supports verify_totp(secret, code) or verify_totp(code) patterns.
    """
    try:
        sig = inspect.signature(verify_fn)
        params = list(sig.parameters.keys())
        if len(params) >= 2:
            return verify_fn(*args[:2])
        if len(params) == 1:
            return verify_fn(args[1] if len(args) > 1 else args[0])
        return True
    except Exception:
        # If verification fails unexpectedly, treat as invalid
        return False


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

    identifier = (request.form.get("email") or request.form.get("username") or "").strip().lower()
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

    c = get_container()

    from service import security  # import module so we can access functions safely

    auth_fn = getattr(security, "authenticate_user", None)
    if not callable(auth_fn):
        return (
            render_template(
                "login.html",
                tenant=tenant,
                error="Auth misconfigured (authenticate_user not found)",
                csrf_token=_csrf_token(),
            ),
            500,
        )

    user = _call_authenticate_user(auth_fn, c, identifier, password)

    # normalize result:
    # - bool True => ok
    # - dict-like => ok
    # - anything falsy => fail
    ok = bool(user)

    if not ok:
        return (
            render_template(
                "login.html",
                tenant=tenant,
                error="Invalid credentials",
                csrf_token=_csrf_token(),
            ),
            401,
        )

    # TOTP (optional)
    verify_fn = getattr(security, "verify_totp", None)
    if callable(verify_fn):
        # If user is a dict-like with totp_secret, enforce it; otherwise let verify_totp decide.
        secret = None
        if isinstance(user, dict):
            secret = user.get("totp_secret") or user.get("totpSecret")

        if secret:
            if not totp:
                return (
                    render_template(
                        "login.html",
                        tenant=tenant,
                        error="TOTP required",
                        csrf_token=_csrf_token(),
                    ),
                    401,
                )
            if not _call_verify_totp(verify_fn, secret, totp):
                return (
                    render_template(
                        "login.html",
                        tenant=tenant,
                        error="Invalid TOTP code",
                        csrf_token=_csrf_token(),
                    ),
                    401,
                )
        else:
            # If verify_totp is the "single-code" version, let it validate/disable itself
            if totp:
                if not _call_verify_totp(verify_fn, None, totp):
                    return (
                        render_template(
                            "login.html",
                            tenant=tenant,
                            error="Invalid TOTP code",
                            csrf_token=_csrf_token(),
                        ),
                        401,
                    )

    # Save session user
    if isinstance(user, dict):
        session["user"] = {
            "id": user.get("id") or "admin",
            "email": user.get("email") or identifier,
            "roles": user.get("roles", ["admin"]),
        }
    else:
        session["user"] = {"id": "admin", "email": identifier, "roles": ["admin"]}

    session["admin_session_id"] = session["user"]["id"]

    return _redirect("admin_ui.dashboard")


@bp.get("/logout")
def logout():
    session.pop("user", None)
    session.pop("admin_session_id", None)
    return _redirect("admin_ui.login_page")
