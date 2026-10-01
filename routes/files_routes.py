from __future__ import annotations
from flask import Blueprint, abort, jsonify, request, session
from jsonschema.exceptions import ValidationError
from service.business_validation import validate_settings
from service.audit import AuditService
from service.business_management import revision
from service.security import require_permission

from retrieval.storage import KNOWN_FILES
from routes import get_container
from routes.session_auth import clear_authenticated_session, is_authenticated_account_active
from routes.tenancy import require_admin_role, resolve_admin_tenant

bp = Blueprint("files", __name__, url_prefix="/files")


def _tenant() -> str:
    container = get_container()
    return resolve_admin_tenant(
        request.args.get("tenant") or "",
        str(container.settings.BUSINESS_KEY or "EXAMPLE"),
    )


def _filename(value: str) -> str:
    filename = str(value or "").strip()
    if filename not in KNOWN_FILES:
        abort(404)
    return filename


def _permission(filename, write=False):
    resource = "offerings" if filename in {"catalog.json", "business_core.json"} else "offers" if filename == "offers.json" else "business_settings"
    return resource + (".write" if write else ".read")


@bp.before_request
def _require_tenant_admin() -> None:
    if not session.get("user"):
        abort(401, description="unauthorized")
    if not is_authenticated_account_active(get_container().storage):
        clear_authenticated_session()
        abort(401, description="unauthorized")
    require_admin_role()


@bp.get("/raw/<path:filename>")
def get_file(filename: str):
    filename = _filename(filename)
    require_permission(_permission(filename))
    try:
        return jsonify(get_container().storage.read_json(_tenant(), filename))
    except FileNotFoundError:
        abort(404)
    except ValueError:
        abort(422)


@bp.put("/raw/<path:filename>")
def put_file(filename: str):
    filename = _filename(filename)
    identity = require_permission(_permission(filename, write=True))
    if not request.is_json:
        abort(415)
    payload = request.get_json()
    schema_map = {
        "catalog.json": "catalog.schema.json",
        "faq.json": "faq.schema.json",
        "offers.json": "offers.schema.json",
        "delivery.json": "delivery.schema.json",
        "branches.json": "branches.schema.json",
        "store_info.json": "store_info.schema.json",
    }
    tenant = _tenant()
    container = get_container()
    from service.security import is_platform_admin
    if not is_platform_admin():
        from service.tenant_access import require_active
        require_active(tenant)
    try:
        if filename in {"branding.json", "overrides.json", "store_info.json", "synonyms.json"} and not isinstance(payload, dict):
            abort(400)
        validate_settings(filename, payload)
        if filename == "offers.json":
            from retrieval.offer_store import OfferStore
            OfferStore.validate(payload)
        audit = AuditService()
        common = {"user": identity["id"], "role": identity["roles"][0],
                  "ip": request.remote_addr or "", "action": "files.put", "target": f"{tenant}/{filename}"}
        details = {"tenant": tenant, "source": "API"}
        audit.record(**common, extra={**details, "result": "attempted"})
        with container.storage.write_lock(tenant):
            try:
                previous = container.storage.read_json(tenant, filename)
            except FileNotFoundError:
                previous = None
            audit.record(**common, extra={**details, "result": "prepared",
                         "before_revision": revision(previous), "after_revision": revision(payload)})
            snap = container.storage._write_json(tenant, filename, payload, schema=schema_map.get(filename))
        audit.record(**common, extra={**details, "result": "success", "snapshot": snap})
    except (ValidationError, ValueError):
        abort(400, description="invalid_business_data")
    container.invalidate_tenant(tenant)
    return jsonify({"ok": True, "snapshot_path": snap, "snapshot": snap})


@bp.get("/versions")
def list_versions():
    require_permission("business_settings.read")
    return jsonify({"versions": get_container().storage.list_versions(_tenant())})
