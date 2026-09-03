from __future__ import annotations
from flask import Blueprint, abort, jsonify, request, session

from retrieval.storage import KNOWN_FILES
from routes import get_container
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
    require_admin_role()


@bp.get("/raw/<path:filename>")
def get_file(filename: str):
    return jsonify(get_container().storage.read_json(_tenant(), _filename(filename)))


@bp.put("/raw/<path:filename>")
def put_file(filename: str):
    filename = _filename(filename)
    payload = request.get_json(force=True)
    schema_map = {
        "catalog.json": "catalog.schema.json",
        "faq.json": "faq.schema.json",
        "delivery.json": "delivery.schema.json",
        "branches.json": "branches.schema.json",
        "store_info.json": "store_info.schema.json",
    }
    tenant = _tenant()
    snap = get_container().storage.write_json(tenant, filename, payload, schema=schema_map.get(filename))
    from services.audit import append_audit

    append_audit(actor="admin", action="files.put", target=f"{tenant}/{filename}", before=None, after="snapshot:" + snap)
    return jsonify({"ok": True, "snapshot_path": snap})


@bp.get("/versions")
def list_versions():
    return jsonify({"versions": get_container().storage.list_versions(_tenant())})
