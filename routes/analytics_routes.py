from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any, Dict, Iterable, Optional

from flask import Blueprint, Response, jsonify, request

from routes import get_container
from service.security import authorized_tenant, require_management

bp = Blueprint("analytics", __name__, url_prefix="/analytics")

# Allowed rollup granularities (match what your analytics service supports)
ALLOWED_ROLLUPS = {"hour", "day", "week", "month"}


def _get_tenant(c) -> str:
    return authorized_tenant(request.args.get("tenant"))


def _get_int(name: str, default: int, min_value: int = 1, max_value: int = 10_000_000) -> int:
    raw = request.args.get(name, "").strip()
    if not raw:
        return default
    try:
        v = int(raw)
    except ValueError:
        return default
    if v < min_value:
        return min_value
    if v > max_value:
        return max_value
    return v


def _get_rollup_by(default: str = "day") -> str:
    by = (request.args.get("by") or default).strip().lower()
    return by if by in ALLOWED_ROLLUPS else default


@bp.get("/kpis.json")
@require_management()
def kpis_json():
    """
    Returns dashboard KPI summary payload for a tenant.
    """
    c = get_container()
    tenant = _get_tenant(c)

    # Optional time window (minutes). Your service can ignore if unsupported.
    minutes = _get_int("minutes", default=1440, min_value=1, max_value=60 * 24 * 365)

    res = c.analytics.get_kpis(tenant=tenant, minutes=minutes)
    return jsonify(res)


@bp.get("/rollups.json")
@require_management()
def rollups_json():
    """
    Returns time-series rollups for charts (message volume, sessions, etc).
    """
    c = get_container()
    tenant = _get_tenant(c)

    minutes = _get_int("minutes", default=1440, min_value=1, max_value=60 * 24 * 365)

    res = c.analytics.get_overview_daily(tenant=tenant, minutes=minutes)
    return jsonify(res)


def _csv_safe(value):
    text = str(value if value is not None else "")
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text


def _iter_csv(rows: Iterable[Dict[str, Any]], fieldnames: list[str]) -> Iterable[str]:
    """
    Stream CSV content as chunks (strings). Works with Flask Response generator.
    """
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    yield output.getvalue()
    output.seek(0)
    output.truncate(0)

    for r in rows:
        writer.writerow({k: _csv_safe(r.get(k, "")) for k in fieldnames})
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)


@bp.get("/export.csv")
@require_management()
def export_csv_route():
    """
    Export up to 500 recent leads for the authorized company.
    """
    c = get_container()
    tenant = _get_tenant(c)

    from service.analytics_db import get_leads
    rows = get_leads(tenant=tenant, limit=500)

    # Compute stable header even if empty
    if rows:
        header = sorted({k for r in rows for k in r.keys()})
    else:
        header = ["last_session_id", "lead_id", "name", "phone", "status", "tags", "updated_utc"]

    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    filename = f"analytics-{tenant}-{ts}.csv"

    return Response(
        _iter_csv(rows, header),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
