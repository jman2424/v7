"""Serves the built SvelteKit owner console under /console and maps legacy section URLs."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

from flask import Blueprint, abort, current_app, g, make_response, redirect, request, send_from_directory
from werkzeug.exceptions import Unauthorized

from retrieval.storage import Storage
from service.console_navigation import WORKSPACES, effective_section, legacy_location


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUILD_DIR = REPO_ROOT / "frontend" / "build"
SECTIONS = {"subscription", "platform", "pipeline", "statistics", "test", "implementation", "whatsapp-qr", "usage", "conversations", "agent", "website", "integrations", "catalog", "offers", "faqs", "delivery", "profile", "branches", "team", "companies", "errors", "account", "privacy"}
SECTIONS.add('operations')
SECTIONS.update({'applications', 'application'})
SECTIONS.update({'budget','provider-funding'})
SECTIONS.update(WORKSPACES)

bp = Blueprint("owner_console", __name__)


def _build_dir() -> Path:
    configured = current_app.config.get("OWNER_CONSOLE_DIR")
    return Path(configured) if configured else DEFAULT_BUILD_DIR


def _section_permitted(section, user):
    from service.security import has_permission, is_platform_admin
    operator=is_platform_admin(user)
    owner='business_owner' in user.get('roles',[])
    if section in {'platform','applications','provider-funding','usage'} and not operator:
        return False
    if section in {'companies','team','operations','phone','email','application'} and not (operator or owner):
        return False
    if section=='billing-overview':
        return has_permission(user,'view_costs') or has_permission(user,'view_subscriptions')
    permissions={
        'platform':['platform.read'],'pipeline':['analytics.read'],'statistics':['analytics.read'],
        'conversations':['conversations.read'],'catalog':['offerings.read'],'offers':['offers.read'],
        'test':['business_settings.read'],'website':['business_settings.read'],'agent':['business_settings.read'],
        'faqs':['business_settings.read'],'delivery':['business_settings.read'],'profile':['business_settings.read'],
        'branches':['business_settings.read'],'privacy':['business_settings.read'],'team':['users.read'],
        'integrations':['business_settings.read','integrations.read'],'implementation':['business_settings.read','integrations.read'],
        'whatsapp-qr':['integrations.read'],'errors':['errors.read','analytics.read'],
        'budget':['view_costs'],'spending':['view_costs'],'usage':['view_costs'],'subscription':['view_subscriptions'],
        'operations':['customers.read','integrations.read'],'phone':['customers.read','integrations.read'],
        'email':['customers.read','integrations.read'],
    }
    return all(has_permission(user,permission) for permission in permissions.get(section,[]))


def _authorize_section(section):
    from service.security import authorized_tenant, is_platform_admin, management_user
    container = current_app.container
    requested_section=section
    if section in WORKSPACES:
        try:
            section=effective_section(section,request.args.get('view',''))
        except ValueError:
            abort(400,description='invalid_console_view')
    try:
        tenant = container.storage.canonical_tenant_key(Storage.validate_tenant_key(
            request.args['tenant'])) if request.args.get('tenant') else None
    except ValueError:
        abort(400, description='invalid_tenant')
    try:
        user = management_user()
    except Unauthorized:
        if tenant is None:
            tenant = container.storage.canonical_tenant_key(Storage.validate_tenant_key(container.settings.BUSINESS_KEY))
        destination = {'next': requested_section, 'tenant': tenant}
        for key in ('view','panel'):
            if request.args.get(key):
                destination[key]=request.args[key]
        if section == 'subscription':
            from service.plan_catalog import PLANS
            plan = request.args.get('plan')
            if plan in PLANS:
                destination['plan'] = plan
        return redirect('/console/?'+urlencode(destination), code=303)
    tenant = authorized_tenant(tenant, container.settings.BUSINESS_KEY)
    tenant = container.storage.canonical_tenant_key(tenant)
    if not container.storage.tenant_exists(tenant):
        abort(404, description='unknown_tenant')
    if requested_section=='platform' and not is_platform_admin(user):
        abort(403, description='platform_admin_required')
    if requested_section in WORKSPACES and not request.args.get('view'):
        permitted=next((view for view in WORKSPACES[requested_section]['views']
            if not view.get('hidden') and _section_permitted(view['section'],user)),None)
        if permitted:
            section=permitted['section']
            query=request.args.to_dict();query['view']=permitted['id'];query['tenant']=tenant
            return redirect('/console/'+requested_section+'?'+urlencode(query),code=303)
    if not _section_permitted(section,user):
        abort(403,description='permission_required')
    return None


def _serve_console(asset_path: str = ""):
    build_dir = _build_dir().resolve()
    if not build_dir.is_dir():
        abort(404, description="owner_console_not_available")

    requested = asset_path.strip('/') or "index.html"
    if requested.casefold() in SECTIONS:
        requested = requested.casefold()+".html"
    candidate = (build_dir / requested).resolve()
    try:
        relative = candidate.relative_to(build_dir)
    except ValueError:
        abort(404)

    html_page = candidate.suffix.casefold() in {'.html', '.htm'}
    if html_page:
        if relative.parent != Path('.'):
            abort(404)
        if candidate.name.casefold() != 'index.html':
            section = candidate.stem.casefold()
            if section not in SECTIONS or candidate.suffix.casefold() != '.html':
                abort(404)
            denied = _authorize_section(section)
            if denied is not None:
                return denied
            if section not in WORKSPACES:
                destination=legacy_location(section)
                query=request.args.to_dict()
                query.update({key:value for key,value in destination.items() if key!='workspace'})
                return redirect('/console/'+destination['workspace']+'?'+urlencode(query),code=308)

    if not candidate.is_file():
        abort(404)

    if html_page:
        html = candidate.read_text(encoding="utf-8")
        html = html.replace("<script", '<script nonce="' + g.csp_nonce + '"')
        response = make_response(html)
        response.headers["Cache-Control"] = "no-store"
    else:
        response = send_from_directory(build_dir, requested)
        # Only successful compiled assets; never HTML, private data or errors.
        if relative.parts[:2] == ("_app", "immutable"):
            g.console_immutable_asset = True
    return response


@bp.get("/console")
def owner_console_redirect():
    return redirect("/console/", code=308)


@bp.get("/console/")
def owner_console_index():
    return _serve_console()


@bp.get("/console/<path:asset_path>")
def owner_console_asset(asset_path: str):
    return _serve_console(asset_path)
