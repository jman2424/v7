from __future__ import annotations

import logging
from flask import Blueprint, jsonify, request

from service.analytics_db import (
    get_kpis,
    get_timeseries,
    get_sessions_timeseries,
    get_channels_split,
    get_top_intents,
    get_fallbacks,
    get_errors,
    get_common_questions,
    get_leads,
    whatsapp_store_share,   # ✅ correct name
)

logger = logging.getLogger("ADMIN.API")
bp = Blueprint("admin_api", __name__, url_prefix="/admin/api")


# -------------------------------------------------
# helpers
# -------------------------------------------------
def _tenant() -> str:
    return (request.args.get("tenant") or "default").strip() or "default"


def _int_arg(name: str, default: int) -> int:
    try:
        return int(request.args.get(name) or default)
    except Exception:
        return default


# -------------------------------------------------
# MAIN DASHBOARD PAYLOAD
# -------------------------------------------------
@bp.get("/insights")
def api_insights():
    tenant = _tenant()
    minutes = _int_arg("minutes", 1440)
    bucket = _int_arg("bucket", 60)
    top = _int_arg("top", 10)
    limit = _int_arg("limit", 50)

    kpis = get_kpis(tenant=tenant, minutes=minutes)
    message_volume = get_timeseries(tenant=tenant, minutes=minutes, bucket_minutes=bucket)
    sessions = get_sessions_timeseries(tenant=tenant, minutes=minutes, bucket_minutes=bucket)

    channels = get_channels_split(tenant=tenant, minutes=minutes)

    payload = {
        "tenant": tenant,
        "window_minutes": minutes,
        "bucket_minutes": bucket,

        # KPIs
        "kpis": kpis,

        # charts
        "message_volume": message_volume,
        "sessions_per_bucket": sessions,
        "channels": channels,

        # derived shapes (bars / pies)
        "channels_total": [
            {"label": ch, "count": v["total"]} for ch, v in channels.items()
        ],
        "channels_inbound": [
            {"label": ch, "count": v["inbound"]} for ch, v in channels.items()
        ],
        "channels_outbound": [
            {"label": ch, "count": v["outbound"]} for ch, v in channels.items()
        ],

        # intents / errors
        "top_intents": get_top_intents(tenant=tenant, minutes=minutes, top=top),
        "fallbacks": get_fallbacks(tenant=tenant, minutes=minutes, top=top),
        "errors": get_errors(tenant=tenant, minutes=minutes, top=top),

        # tables
        "common_questions": get_common_questions(tenant=tenant, minutes=minutes, top=top),
        "leads": get_leads(tenant=tenant, limit=limit),

        # ✅ WhatsApp store/location pie
        "whatsapp_store_share": whatsapp_store_share(
            tenant=tenant,
            minutes=minutes,
        ),
    }

    return jsonify(payload)


# -------------------------------------------------
# INDIVIDUAL ENDPOINTS (debug / reuse)
# -------------------------------------------------
@bp.get("/kpis")
def api_kpis():
    return jsonify(get_kpis(tenant=_tenant(), minutes=_int_arg("minutes", 1440)))


@bp.get("/timeseries")
def api_timeseries():
    return jsonify(
        get_timeseries(
            tenant=_tenant(),
            minutes=_int_arg("minutes", 1440),
            bucket_minutes=_int_arg("bucket", 60),
        )
    )


@bp.get("/sessions_timeseries")
def api_sessions():
    return jsonify(
        get_sessions_timeseries(
            tenant=_tenant(),
            minutes=_int_arg("minutes", 1440),
            bucket_minutes=_int_arg("bucket", 60),
        )
    )


@bp.get("/channels")
def api_channels():
    return jsonify(get_channels_split(tenant=_tenant(), minutes=_int_arg("minutes", 1440)))


@bp.get("/intents")
def api_intents():
    return jsonify(
        get_top_intents(
            tenant=_tenant(),
            minutes=_int_arg("minutes", 1440),
            top=_int_arg("top", 10),
        )
    )


@bp.get("/fallbacks")
def api_fallbacks():
    return jsonify(
        get_fallbacks(
            tenant=_tenant(),
            minutes=_int_arg("minutes", 1440),
            top=_int_arg("top", 10),
        )
    )


@bp.get("/errors")
def api_errors():
    return jsonify(
        get_errors(
            tenant=_tenant(),
            minutes=_int_arg("minutes", 1440),
            top=_int_arg("top", 10),
        )
    )


@bp.get("/questions")
def api_questions():
    return jsonify(
        get_common_questions(
            tenant=_tenant(),
            minutes=_int_arg("minutes", 1440),
            top=_int_arg("top", 10),
        )
    )


@bp.get("/leads")
def api_leads():
    return jsonify(get_leads(tenant=_tenant(), limit=_int_arg("limit", 50)))


@bp.get("/whatsapp_store_share")
def api_whatsapp_store_share():
    return jsonify(
        whatsapp_store_share(
            tenant=_tenant(),
            minutes=_int_arg("minutes", 1440),
        )
    )
