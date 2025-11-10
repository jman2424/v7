from __future__ import annotations
from flask import Blueprint, request, jsonify, Response
from routes import get_container, require_auth
import io, csv

bp = Blueprint("analytics", __name__, url_prefix="/analytics")

@bp.get("/kpis.json")
@require_auth(roles=("Owner","Manager","Staff"))
def kpis_json():
    c = get_container()
    tenant = request.args.get("tenant") or c.settings.BUSINESS_KEY
    res = c.analytics.summary(tenant)
    return jsonify(res)

@bp.get("/rollups.json")
@require_auth(roles=("Owner","Manager","Staff"))
def rollups_json():
    c = get_container()
    tenant = request.args.get("tenant") or c.settings.BUSINESS_KEY
    res = c.analytics.rollups(tenant, by=request.args.get("by", "day"))
    return jsonify(res)

@bp.get("/export.csv")
@require_auth(roles=("Owner","Manager"))
def export_csv_route():
    c = get_container()
    tenant = request.args.get("tenant") or c.settings.BUSINESS_KEY
    rows = c.analytics.fetch_raw(tenant)

    # Stream CSV
    output = io.StringIO()
    if rows:
        header = sorted({k for r in rows for k in r.keys()})
        w = csv.DictWriter(output, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in header})

    return Response(output.getvalue(), mimetype="text/csv")
