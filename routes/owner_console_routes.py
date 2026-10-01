from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

from flask import Blueprint, abort, current_app, g, make_response, redirect, request, send_from_directory
from werkzeug.exceptions import Unauthorized

from retrieval.storage import Storage


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUILD_DIR = REPO_ROOT / "frontend" / "build"
SECTIONS = {"subscription", "platform", "pipeline", "statistics", "test", "implementation", "whatsapp-qr", "usage", "conversations", "agent", "website", "integrations", "catalog", "offers", "faqs", "delivery", "profile", "branches", "team", "companies", "errors", "account", "privacy"}

bp = Blueprint("owner_console", __name__)


def _build_dir() -> Path:
    configured = current_app.config.get("OWNER_CONSOLE_DIR")
    return Path(configured) if configured else DEFAULT_BUILD_DIR


def _authorize_section(section):
    from service.security import authorized_tenant, is_platform_admin, management_user, require_permission
    container = current_app.container
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
        return redirect('/console/?'+urlencode({'next': section, 'tenant': tenant}), code=303)
    tenant = authorized_tenant(tenant, container.settings.BUSINESS_KEY)
    tenant = container.storage.canonical_tenant_key(tenant)
    if not container.storage.tenant_exists(tenant):
        abort(404, description='unknown_tenant')
    if section == 'platform' and not is_platform_admin(user):
        abort(403, description='platform_admin_required')
    if section in {'team', 'companies'} and not is_platform_admin(user) and 'business_owner' not in user['roles']:
        abort(403, description='company_owner_required')
    if section == 'usage':
        require_permission('view_costs')
    if section == 'subscription':
        require_permission('view_subscriptions')
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

    if not candidate.is_file():
        abort(404)

    if html_page:
        html = candidate.read_text(encoding="utf-8")
        html = html.replace("<script", '<script nonce="' + g.csp_nonce + '"')
        response = make_response(html)
        response.headers["Cache-Control"] = "no-store"
    else:
        response = send_from_directory(build_dir, requested)
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
