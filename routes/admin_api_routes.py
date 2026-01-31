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
    get_sessions_timeseries,

    # ✅ NEW
    get_channel_breakdown,
    get_whatsapp_store_share,
)

logger = logging.getLogger("ADMIN.API")
bp = Blueprint("admin_api", __name__, url_prefix="/admin/api")


def _tenant() -> str:
    return (request.args.get("tenant") or "default").strip() or "default"


def _int_arg(name: str, default: int) -> int:
    try:
        return int(request.args.get(name) or default)
    except Exception:
        return default


@bp.get("/insights")
def api_insights():
    """
    Single payload endpoint for the dashboard.
    """
    tenant = _tenant()
    minutes = _int_arg("minutes", 1440)
    bucket = _int_arg("bucket", 60)
    top = _int_arg("top", 10)
    limit = _int_arg("limit", 50)

    kpis = get_kpis(tenant=tenant, minutes=minutes)
    msg_series = get_timeseries(tenant=tenant, minutes=minutes, bucket_minutes=bucket)
    sess_series = get_sessions_timeseries(tenant=tenant, minutes=minutes, bucket_minutes=bucket)

    channels = get_channels_split(tenant=tenant, minutes=minutes)
    intents = get_top_intents(tenant=tenant, minutes=minutes, top=top)
    fallbacks = get_fallbacks(tenant=tenant, minutes=minutes, top=top)
    errors = get_errors(tenant=tenant, minutes=minutes, top=top)
    questions = get_common_questions(tenant=tenant, minutes=minutes, top=top)
    leads = get_leads(tenant=tenant, limit=limit)

    # ✅ NEW: web vs whatsapp, each with inbound/outbound/fallbacks
    channel_breakdown = get_channel_breakdown(tenant=tenant, minutes=minutes)

    # ✅ NEW: whatsapp store/location pie
    whatsapp_store_share = get_whatsapp_store_share(tenant=tenant, minutes=minutes, limit=12)

    # handy shapes
    channels_total = [{"label": ch, "count": v.get("total", 0)} for ch, v in channels.items()]
    channels_in = [{"label": ch, "count": v.get("inbound", 0)} for ch, v in channels.items()]
    channels_out = [{"label": ch, "count": v.get("outbound", 0)} for ch, v in channels.items()]

    payload = {
        "tenant": tenant,
        "window_minutes": minutes,
        "bucket_minutes": bucket,
        "kpis": kpis,

        # charts
        "message_volume": msg_series,          # [{t/bucket, inbound, outbound}]
        "sessions_per_bucket": sess_series,    # [{t/bucket, sessions}]
        "channels": channels,                  # {"web": {"inbound":..,"outbound":..,"total":..}, ...}
        "channels_total": channels_total,
        "channels_inbound": channels_in,
        "channels_outbound": channels_out,

        # ✅ NEW charts data
        "channel_breakdown": channel_breakdown,            # {"web":{inbound,outbound,fallbacks}, "whatsapp":{...}}
        "whatsapp_store_share": whatsapp_store_share,      # [{"store":"Leyton","count":3}, ...]

        "top_intents": intents,
        "fallbacks": fallbacks,
        "errors": errors,

        # tables
        "common_questions": questions,
        "leads": leads,
    }

    return jsonify(payload)


@bp.get("/kpis")
def api_kpis():
    minutes = _int_arg("minutes", 1440)
    return jsonify(get_kpis(tenant=_tenant(), minutes=minutes))


@bp.get("/timeseries")
def api_timeseries():
    minutes = _int_arg("minutes", 1440)
    bucket = _int_arg("bucket", 60)
    return jsonify(get_timeseries(tenant=_tenant(), minutes=minutes, bucket_minutes=bucket))


@bp.get("/sessions_timeseries")
def api_sessions_timeseries():
    minutes = _int_arg("minutes", 1440)
    bucket = _int_arg("bucket", 60)
    return jsonify(get_sessions_timeseries(tenant=_tenant(), minutes=minutes, bucket_minutes=bucket))


@bp.get("/channels")
def api_channels():
    minutes = _int_arg("minutes", 1440)
    return jsonify(get_channels_split(tenant=_tenant(), minutes=minutes))


@bp.get("/channel_breakdown")
def api_channel_breakdown():
    minutes = _int_arg("minutes", 1440)
    return jsonify(get_channel_breakdown(tenant=_tenant(), minutes=minutes))


@bp.get("/whatsapp_store_share")
def api_whatsapp_store_share():
    minutes = _int_arg("minutes", 1440)
    limit = _int_arg("limit", 12)
    return jsonify(get_whatsapp_store_share(tenant=_tenant(), minutes=minutes, limit=limit))


@bp.get("/intents")
def api_intents():
    minutes = _int_arg("minutes", 1440)
    top = _int_arg("top", 10)
    return jsonify(get_top_intents(tenant=_tenant(), minutes=minutes, top=top))


@bp.get("/fallbacks")
def api_fallbacks():
    minutes = _int_arg("minutes", 1440)
    top = _int_arg("top", 10)
    return jsonify(get_fallbacks(tenant=_tenant(), minutes=minutes, top=top))


@bp.get("/errors")
def api_errors():
    minutes = _int_arg("minutes", 1440)
    top = _int_arg("top", 10)
    return jsonify(get_errors(tenant=_tenant(), minutes=minutes, top=top))


@bp.get("/questions")
def api_questions():
    minutes = _int_arg("minutes", 1440)
    top = _int_arg("top", 10)
    return jsonify(get_common_questions(tenant=_tenant(), minutes=minutes, top=top))


@bp.get("/leads")
def api_leads():
    limit = _int_arg("limit", 50)
    return jsonify(get_leads(tenant=_tenant(), limit=limit))
