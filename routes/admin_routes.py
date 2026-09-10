from flask import Blueprint, abort, redirect, render_template, request, session, url_for
from werkzeug.exceptions import Unauthorized

from routes import get_container
from service.security import (
    authenticate_user,
    authorized_tenant,
    is_platform_admin,
    management_user,
    start_management_session,
    verify_totp,
)

bp = Blueprint("admin_ui", __name__, url_prefix="/admin")


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


@bp.get("/login")
def login_page():
    if session.get("user"):
        return redirect(url_for("admin_ui.dashboard"))
    return render_template("login.html", error=None, csrf_token=session["_csrf"])


@bp.post("/login")
def login_submit():
    user = authenticate_user(get_container(), email=request.form.get("email", ""),
                             password=request.form.get("password", ""))
    if not user or not verify_totp(user.get("totp_secret"), request.form.get("totp", "")):
        return render_template("login.html", error="Invalid credentials or verification code",
                               csrf_token=session["_csrf"]), 401
    start_management_session(user)
    return redirect(url_for("admin_ui.dashboard"))


@bp.post("/logout")
def logout():
    from service import session_store
    session_store.revoke(session.get("management_token"))
    session.clear()
    return redirect(url_for("admin_ui.login_page"))
