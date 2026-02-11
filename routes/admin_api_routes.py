# routes/admin_api_routes.py
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List

from flask import Blueprint, jsonify, request

logger = logging.getLogger("ADMIN.API")
bp = Blueprint("admin_api", __name__, url_prefix="/admin/api")


def _safe_import(name: str, fallback: Callable[..., Any]) -> Callable[..., Any]:
    try:
        from service import analytics_db  # type: ignore

        fn = getattr(analytics_db, name, None)
        if callable(fn):
            return fn  # type: ignore[return-value]
        logger.warning("analytics_db.%s missing; using fallback", name)
        return fallback
    except Exception as e:
        logger.exception("Failed importing analytics_db.%s (%s); using fallback", name, e)
        return fallback


def _fb_dict(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    return {}


def _fb_list(*args: Any, **kwargs: Any) -> List[Dict[str, Any]]:
    return []


# Canonical analytics functions
get_kpis = _safe_import("get_kpis", _fb_dict)
get_timeseries = _safe_import("get_timeseries", _fb_list)
get_sessions_timeseries = _safe_import("get_sessions_timeseries", _fb_list)
get_channels_split = _safe_import("get_channels_split", _fb_dict)
get_top_intents = _safe_import("get_top_intents", _fb_list)
get_fallbacks = _safe_import("get_fallbacks", _fb_list)
get_errors = _safe_import("get_errors", _fb_list)
get_common_questions = _safe_import("get_common_questions", _fb_list)
get_leads = _safe_import("get_leads", _fb_list)

# NEW: overview daily
get_overview_daily = _safe_import("get_overview_daily", _fb_list)

# Optional extras
get_channel_breakdown = _safe_import("get_channel_breakdown", _fb_dict)
get_whatsapp_store_share = _safe_import("get_whatsapp_store_share", _fb_list)


def _tenant() -> str:
    return (request.args.get("tenant") or "default").strip() or "default"


def _int_arg(name: str, default: int) -> int:
    try:
        return int(request.args.get(name) or default)
    except Exception:
        return default


@bp.get("/insights")
def api_insights():
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

    # NEW: per-day overview for the overview chart
    overview_daily = get_overview_daily(tenant=tenant, minutes=minutes, limit_days=45)

    # Optional extras
    ch_breakdown = get_channel_breakdown(tenant=tenant, minutes=minutes)
    wa_share = get_whatsapp_store_share(tenant=tenant, minutes=minutes, limit=12)

    channels_total = [{"label": ch, "count": v.get("total", 0)} for ch, v in (channels or {}).items()]

    payload = {
        "tenant": tenant,
        "window_minutes": minutes,
        "bucket_minutes": bucket,
        "kpis": kpis,

        "message_volume": msg_series,
        "sessions_per_bucket": sess_series,

        "channels": channels,
        "channels_total": channels_total,

        "channel_breakdown": ch_breakdown,
        "whatsapp_store_share": wa_share,

        "top_intents": intents,
        "fallbacks": fallbacks,
        "errors": errors,

        "common_questions": questions,
        "leads": leads,

        # 👇 what charts.js now uses for the "Errors slot" (Overview line)
        "overview_daily": overview_daily,
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
