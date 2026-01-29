from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Iterable, Dict, Any, Optional

from flask import Blueprint, request, jsonify, Response

from routes import get_container, require_auth

bp = Blueprint("analytics", __name__, url_prefix="/analytics")

# Allowed rollup granularities (match what your analytics service supports)
ALLOWED_ROLLUPS = {"hour", "day", "week", "month"}


def _get_tenant(c) -> str:
    tenant = (request.args.get("tenant") or "").strip()
    return tenant or c.settings.BUSINESS_KEY


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
@require_auth(roles=("Owner", "Manager", "Staff"))
def kpis_json():
    """
    Returns dashboard KPI summary payload for a tenant.
    """
    c = get_container()
    tenant = _get_tenant(c)

    # Optional time window (minutes). Your service can ignore if unsupported.
    minutes = _get_int("minutes", default=1440, min_value=1, max_value=60 * 24 * 365)

    res = c.analytics.summary(tenant, minutes=minutes)
    return jsonify(res)


@bp.get("/rollups.json")
@require_auth(roles=("Owner", "Manager", "Staff"))
def rollups_json():
    """
    Returns time-series rollups for charts (message volume, sessions, etc).
    """
    c = get_container()
    tenant = _get_tenant(c)

    by = _get_rollup_by(default="day")
    minutes = _get_int("minutes", default=1440, min_value=1, max_value=60 * 24 * 365)

    res = c.analytics.rollups(tenant, by=by, minutes=minutes)
    return jsonify(res)


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
        writer.writerow({k: r.get(k, "") for k in fieldnames})
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)


@bp.get("/export.csv")
@require_auth(roles=("Owner", "Manager"))
def export_csv_route():
    """
    Streams raw analytics events as CSV.
    """
    c = get_container()
    tenant = _get_tenant(c)

    # Optional time window (minutes)
    minutes = _get_int("minutes", default=1440, min_value=1, max_value=60 * 24 * 365)

    rows = c.analytics.fetch_raw(tenant, minutes=minutes) or []

    # Compute stable header even if empty
    if rows:
        header = sorted({k for r in rows for k in r.keys()})
    else:
        header = ["timestamp", "tenant", "direction", "channel", "intent", "session_id", "message"]

    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    filename = f"analytics-{tenant}-{ts}.csv"

    return Response(
        _iter_csv(rows, header),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
