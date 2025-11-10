from __future__ import annotations
from flask import Blueprint, request, jsonify, abort
from routes import get_container, require_auth

bp = Blueprint("files", __name__, url_prefix="/files")

# Download raw tenant file
@bp.get("/raw/<path:filename>")
@require_auth(roles=("Owner","Manager","Staff"))
def get_file(filename: str):
    c = get_container()
    try:
        data = c.storage.read_json(c.settings.BUSINESS_KEY, filename)
        return jsonify(data)
    except FileNotFoundError:
        abort(404)

# Upload/replace with validation + snapshot
@bp.put("/raw/<path:filename>")
@require_auth(roles=("Owner","Manager"))
def put_file(filename: str):
    c = get_container()
    payload = request.get_json(force=True)
    # Optional schema inference by filename
    schema_map = {
        "catalog.json": "schemas/catalog.schema.json",
        "faq.json": "schemas/faq.schema.json",
        "delivery.json": "schemas/delivery.schema.json",
        "branches.json": "schemas/branches.schema.json",
    }
    schema = schema_map.get(filename)
    snap = c.storage.write_json(c.settings.BUSINESS_KEY, filename, payload, schema=schema)
    from services.audit import append_audit
    append_audit(actor="admin", action="files.put", target=filename, before=None, after="snapshot:"+snap)
    return jsonify({"ok": True, "snapshot_path": snap})

# List snapshots
@bp.get("/versions")
@require_auth(roles=("Owner","Manager"))
def list_versions():
    c = get_container()
    versions = c.storage.list_versions(c.settings.BUSINESS_KEY)
    return jsonify({"versions": versions})
