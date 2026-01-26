# routes/admin_api_routes.py
from __future__ import annotations

import logging
from flask import Blueprint, jsonify, request

from service.analytics_db import (
    get_kpis,
    get_timeseries,
    get_channels_split,
    get_top_intents,
    get_fallbacks,
    get_errors,
    get_common_questions,
    get_leads,
)

logger = logging.getLogger("ADMIN.API")
bp = Blueprint("admin_api", __name__, url_prefix="/admin/api")


def _tenant() -> str:
    return (request.args.get("tenant") or "default").strip() or "default"


@bp.get("/kpis")
def api_kpis():
    minutes = int(request.args.get("minutes") or 1440)
    return jsonify(get_kpis(tenant=_tenant(), minutes=minutes))


@bp.get("/timeseries")
def api_timeseries():
    minutes = int(request.args.get("minutes") or 1440)
    bucket = int(request.args.get("bucket") or 60)
    return jsonify(get_timeseries(tenant=_tenant(), minutes=minutes, bucket_minutes=bucket))


@bp.get("/channels")
def api_channels():
    minutes = int(request.args.get("minutes") or 1440)
    return jsonify(get_channels_split(tenant=_tenant(), minutes=minutes))


@bp.get("/intents")
def api_intents():
    minutes = int(request.args.get("minutes") or 1440)
    top = int(request.args.get("top") or 10)
    return jsonify(get_top_intents(tenant=_tenant(), minutes=minutes, top=top))


@bp.get("/fallbacks")
def api_fallbacks():
    minutes = int(request.args.get("minutes") or 1440)
    top = int(request.args.get("top") or 10)
    return jsonify(get_fallbacks(tenant=_tenant(), minutes=minutes, top=top))


@bp.get("/errors")
def api_errors():
    minutes = int(request.args.get("minutes") or 1440)
    top = int(request.args.get("top") or 10)
    return jsonify(get_errors(tenant=_tenant(), minutes=minutes, top=top))


@bp.get("/questions")
def api_questions():
    minutes = int(request.args.get("minutes") or 1440)
    top = int(request.args.get("top") or 10)
    return jsonify(get_common_questions(tenant=_tenant(), minutes=minutes, top=top))


@bp.get("/leads")
def api_leads():
    limit = int(request.args.get("limit") or 50)
    return jsonify(get_leads(tenant=_tenant(), limit=limit))
