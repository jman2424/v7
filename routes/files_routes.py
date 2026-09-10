"""Tenant-scoped, allowlisted business data management."""
from flask import Blueprint, abort, jsonify, request
from jsonschema import ValidationError

from routes import get_container
from service.audit import AuditService
from service.security import authorized_tenant, management_user

bp = Blueprint("files", __name__, url_prefix="/files")
FILES = {"catalog.json", "faq.json", "delivery.json", "branches.json",
         "branding.json", "store_info.json", "overrides.json", "synonyms.json"}
SCHEMAS = {name: name.replace(".json", ".schema.json") for name in
           ("catalog.json", "faq.json", "delivery.json", "branches.json")}


@bp.before_request
def protect_files():
    management_user()


def target(filename=None):
    c = get_container()
    tenant = authorized_tenant(request.args.get("tenant"))
    if filename is not None and filename not in FILES:
        abort(404)
    if not c.storage.tenant_dir(tenant).is_dir():
        abort(404)
    return c, tenant


@bp.get("/raw/<path:filename>")
def get_file(filename):
    c, tenant = target(filename)
    try:
        return jsonify(c.storage.read_json(tenant, filename))
    except FileNotFoundError:
        abort(404)
    except ValueError:
        abort(422, description="Invalid stored JSON")


@bp.put("/raw/<path:filename>")
def put_file(filename):
    c, tenant = target(filename)
    payload = request.get_json()
    if not isinstance(payload, (dict, list)):
        abort(400, description="Structured JSON required")
    schema = SCHEMAS.get(filename)
    # Existing sheet catalogs use product_catalog; validate that supported format.
    if filename == "catalog.json" and isinstance(payload, dict) and "product_catalog" in payload:
        schema = "catalog-sheet.schema.json"
    if filename in {"branding.json", "store_info.json", "overrides.json", "synonyms.json"} and not isinstance(payload, dict):
        abort(400, description="JSON object required")
    if filename in {"branding.json", "store_info.json", "overrides.json", "synonyms.json"}:
        from service.business_validation import validate_settings
        validate_settings(filename, payload)
    try:
        snapshot = c.storage.write_json(tenant, filename, payload, schema=schema)
    except ValidationError:
        abort(400, description="Business data does not match the schema")
    user = management_user()
    AuditService().record(user=user["id"], role=user["roles"][0], ip=request.remote_addr or "",
                          action="business.update", target=f"{tenant}/{filename}",
                          extra={"snapshot": snapshot})
    return jsonify(ok=True, snapshot=snapshot)


@bp.get("/versions")
def list_versions():
    c, tenant = target()
    return jsonify(versions=c.storage.list_versions(tenant))
