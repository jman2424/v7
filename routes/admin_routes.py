# routes/admin_routes.py
from __future__ import annotations

from flask import Blueprint, abort, current_app, render_template, request, redirect, url_for, session
from routes import get_container
from routes.session_auth import clear_authenticated_session, establish_authenticated_session, is_authenticated_account_active
from routes.tenancy import resolve_admin_tenant
from retrieval.storage import Storage
from werkzeug.exceptions import Unauthorized
from service.security import management_user, authorized_tenant, is_platform_admin

bp = Blueprint("admin_ui", __name__, url_prefix="/admin")


def _is_logged_in() -> bool:
    if not session.get("user"):
        return False
    if is_authenticated_account_active(get_container().storage):
        return True
    clear_authenticated_session()
    return False


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
@bp.get("/<page>")
def dashboard(page="overview"):
    pages = {"overview": "Overview", "companies": "Companies", "conversations": "Conversations & leads",
             "business": "Business information", "settings": "Agent & widget settings",
             "errors": "Errors & health", "integrations": "Integrations", "products": "Products & prices",
             "faqs": "Questions & answers", "branches": "Branches & hours", "delivery": "Delivery"}
    if page not in pages:
        abort(404)
    if not session.get("user"):
        return redirect(url_for("admin_ui.login_page"))
    try:
        user = management_user(platform_only=page == "companies")
    except Unauthorized:
        session.clear()
        return redirect(url_for("admin_ui.login_page"))
    tenant = authorized_tenant(request.args.get("tenant"))
    resources = {"products": "catalog.json", "faqs": "faq.json", "branches": "branches.json",
                 "delivery": "delivery.json", "business": "store_info.json"}
    descriptions = {"overview": "A focused view of your agent's recent activity.",
                    "companies": "Check activity and investigate issues across your businesses.",
                    "conversations": "Review customer messages and leads for this company.",
                    "products": "Keep your catalog, prices and stock up to date.",
                    "faqs": "Give your agent clear answers to common customer questions.",
                    "branches": "Manage the places and opening hours customers ask about.",
                    "delivery": "Set the delivery information your agent can share.",
                    "business": "Manage this company's contact and business information.",
                    "settings": "Customize your agent and website chat.",
                    "errors": "Find recorded failures and check business data.",
                    "integrations": "Connect your website and prepare WhatsApp for later."}
    template = "resource" if page in resources or page == "settings" else page
    return render_template("pages/" + template + ".html", tenant=tenant, role=user["roles"][0],
                           platform_admin=is_platform_admin(user), session_id="",
                           csrf_token=session["_csrf"], version="7", page=page, page_title=pages[page],
                           page_description=descriptions[page], resource_file=resources.get(page),
                           base_url=get_container().settings.BASE_URL.rstrip("/"))


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
    if not secret or not totp_code:
        from service.account_mfa import begin
        begin(user, tenant)
        return redirect('/console/')
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
    identity = establish_authenticated_session(user, tenant, mfa_verified=True)
    session["admin_session_id"] = identity["id"]

    return _redirect("admin_ui.dashboard")


@bp.post("/logout")
def logout():
    clear_authenticated_session()
    return _redirect("admin_ui.login_page")
