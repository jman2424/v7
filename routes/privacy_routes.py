"""Public privacy information and revocable, tenant-scoped management edits."""
from datetime import datetime, timezone
import re
from urllib.parse import quote

from flask import Blueprint, abort, current_app, jsonify, render_template, request, url_for

from routes import get_container
from routes.tenancy import require_admin_role, resolve_admin_tenant
from service.audit import AuditService
from service.security import is_platform_admin, management_user
from service import privacy_settings

bp = Blueprint("privacy_pages", __name__)


def management_context(write=False):
    user = management_user()
    require_admin_role()
    if write and not (is_platform_admin(user) or "business_owner" in user.get("roles", [])):
        abort(403, description="company_owner_required")
    container = get_container()
    requested = request.args.get("tenant", "")
    try:
        if requested:
            requested = container.storage.canonical_tenant_key(requested)
        tenant = container.storage.canonical_tenant_key(resolve_admin_tenant(requested, container.settings.BUSINESS_KEY))
    except ValueError:
        abort(400, description="invalid_tenant")
    if not container.storage.tenant_exists(tenant):
        abort(404)
    return user, tenant, container.storage


def management_response(user, tenant, storage):
    result = privacy_settings.status(storage, tenant)
    response = jsonify(tenant=tenant, **result, policy_url=url_for("privacy_pages.privacy_page", tenant=tenant),
                       write_allowed=bool(is_platform_admin(user) or "business_owner" in user.get("roles", [])))
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.get("/admin/api/privacy")
def privacy_get():
    user, tenant, storage = management_context()
    return management_response(user, tenant, storage)


@bp.put("/admin/api/privacy")
def privacy_put():
    user, tenant, storage = management_context(write=True)
    data = request.get_json(silent=True)
    if (not isinstance(data, dict) or set(data) != {"settings", "revision"}
            or not isinstance(data.get("revision"), str) or not re.fullmatch(r"[a-f0-9]{64}", data["revision"])):
        abort(400, description="invalid_privacy_request")
    try:
        settings = privacy_settings.validate_settings(data["settings"])
    except ValueError as exc:
        abort(400, description=str(exc))
    audit = AuditService()
    common = {"user": user["id"], "role": user["roles"][0], "ip": request.remote_addr or "",
              "action": "privacy.update", "target": f"{tenant}/{privacy_settings.FILENAME}"}
    with storage.write_lock(tenant):
        before = privacy_settings.status(storage, tenant)
        if data["revision"] != before["revision"]:
            abort(409, description="privacy_settings_changed")
        audit.record(**common, extra={"result": "prepared", "fields": sorted(settings)})
        storage._write_json(tenant, privacy_settings.FILENAME, settings)
        audit.record(**common, extra={"result": "saved"})
    return management_response(user, tenant, storage)


@bp.get("/privacy")
def privacy_page():
    container = get_container()
    tenant = request.args.get("tenant")
    if tenant is not None:
        try:
            tenant = container.storage.canonical_tenant_key(tenant)
        except ValueError:
            abort(404)
        if not container.storage.tenant_exists(tenant):
            abort(404)
    policy = privacy_settings.status(container.storage, tenant)
    response = current_app.make_response(render_template("privacy.html", policy=policy, tenant=tenant,
        processors=privacy_settings.processors(container, tenant),
        mailto_url="mailto:" + quote(policy["settings"]["contact_email"], safe="@")))
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.get("/cookies")
def cookies_page():
    configured = int(current_app.config["PERMANENT_SESSION_LIFETIME"].total_seconds())
    return render_template("cookies.html", session_cookie=current_app.config.get("SESSION_COOKIE_NAME", "session"),
                           cookie_hours=configured / 3600, account_hours=min(configured, 8 * 3600) / 3600)


@bp.get("/auth/privacy/export")
def own_account_export():
    user = management_user()
    from service.trusted_devices import status
    identity = {key: user[key] for key in ("id", "email", "username", "roles", "tenant") if key in user}
    choice = request.cookies.get("v7_preferences", "")
    choice = choice if choice in {"all", "essential"} else ""
    language = request.cookies.get("v7_language", "")
    language = language if choice == "all" and language in {"en", "es", "fr", "ar"} else ""
    AuditService().record(user=user["id"], role=user["roles"][0], ip=request.remote_addr or "",
                          action="privacy.account_export", target="own_account",
                          extra={"scope": "account_identity_and_preferences_only"})
    response = jsonify(identity=identity, trusted_devices=status(user),
                       preferences={"choice": choice, "saved_language": language},
                       exported_at=datetime.now(timezone.utc).isoformat(),
                       scope="account_identity_and_preferences_only")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Disposition"] = 'attachment; filename="v7-account-data.json"'
    return response
