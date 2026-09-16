from __future__ import annotations
from flask import Blueprint, abort, jsonify, request, session
from jsonschema.exceptions import ValidationError
from service.business_validation import validate_settings

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
    try:
        return jsonify(get_container().storage.read_json(_tenant(), _filename(filename)))
    except FileNotFoundError:
        abort(404)
    except ValueError:
        abort(422)


@bp.put("/raw/<path:filename>")
def put_file(filename: str):
    filename = _filename(filename)
    payload = request.get_json(force=True)
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
    try:
        if filename in {"branding.json", "overrides.json", "store_info.json", "synonyms.json"} and not isinstance(payload, dict):
            abort(400)
        validate_settings(filename, payload)
        if filename == "offers.json":
            from retrieval.offer_store import OfferStore
            OfferStore.validate(payload)
        snap = container.storage.write_json(tenant, filename, payload, schema=schema_map.get(filename))
    except (ValidationError, ValueError):
        abort(400, description="invalid_business_data")
    container.invalidate_tenant(tenant)
    from service.audit import AuditService

    identity = session.get("user") or {}
    actor = str(identity.get("email") or identity.get("id") or "admin")
    AuditService().record(user=actor, role=(identity.get("roles") or ["unknown"])[0], ip=request.remote_addr or "",
                          action="files.put", target=f"{tenant}/{filename}", extra={"snapshot": snap})
    return jsonify({"ok": True, "snapshot_path": snap, "snapshot": snap})


@bp.get("/versions")
def list_versions():
    return jsonify({"versions": get_container().storage.list_versions(_tenant())})
