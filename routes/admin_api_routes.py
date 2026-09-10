# routes/admin_api_routes.py
from __future__ import annotations

import logging
import sqlite3

from flask import Blueprint, abort, jsonify, request
from werkzeug.exceptions import HTTPException

from routes import get_container
from service.analytics_db import (
    get_channel_breakdown,
    get_channels_split,
    get_common_questions,
    get_errors,
    get_fallbacks,
    get_kpis,
    get_leads,
    get_overview_daily,
    get_sessions_by_channel,
    get_sessions_timeseries,
    get_timeseries,
    get_top_intents,
    get_whatsapp_store_share,
)
from service.security import authorized_tenant, management_user

logger = logging.getLogger("ADMIN.API")
bp = Blueprint("admin_api", __name__, url_prefix="/admin/api")


@bp.before_request
def protect_dashboard_api():
    management_user()


@bp.after_request
def private_response(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.errorhandler(HTTPException)
def api_http_error(error):
    return jsonify({"ok": False, "error": error.name}), error.code


@bp.errorhandler(sqlite3.Error)
@bp.errorhandler(OSError)
def analytics_unavailable(error):
    logger.error("Dashboard analytics unavailable (%s)", type(error).__name__)
    return jsonify({"ok": False, "error": "Analytics temporarily unavailable"}), 503


def _tenant() -> str:
    c = get_container()
    return authorized_tenant(request.args.get("tenant"), default=c.settings.BUSINESS_KEY)


def _int_arg(name: str, default: int) -> int:
    try:
        value = int(request.args.get(name, default))
    except (ValueError, TypeError):
        abort(400, description="Invalid query parameter")
    maximum = {"minutes": 43200, "bucket": 1440, "top": 50, "limit": 500,
               "page": 100000}.get(name, 500)
    if not 1 <= value <= maximum:
        abort(400, description="Query parameter out of range")
    return value


@bp.get("/platform")
def api_platform():
    management_user(platform_only=True)
    from service.platform_overview import get_platform_overview

    return jsonify(get_platform_overview(
        get_container(), minutes=_int_arg("minutes", 1440), page=_int_arg("page", 1)
    ))


@bp.get("/insights")
def api_insights():
    """
    Single endpoint the dashboard uses.

    Contract (used by dashboard/static/js/charts.js):
      - kpis
      - message_volume
      - sessions_per_bucket
      - channels_total
      - top_intents
      - fallbacks
      - overview_daily
    """
    tenant = _tenant()
    minutes = _int_arg("minutes", 1440)
    bucket = _int_arg("bucket", 60)
    top = _int_arg("top", 10)
    limit = _int_arg("limit", 50)

    # KPIs
    kpis = get_kpis(tenant=tenant, minutes=minutes)

    # Timeseries
    msg_series = get_timeseries(tenant=tenant, minutes=minutes, bucket_minutes=bucket)
    sess_series = get_sessions_timeseries(tenant=tenant, minutes=minutes, bucket_minutes=bucket)

    # Breakdowns
    channels = get_channels_split(tenant=tenant, minutes=minutes)
    intents = get_top_intents(tenant=tenant, minutes=minutes, top=top)
    fallbacks = get_fallbacks(tenant=tenant, minutes=minutes, top=top)
    errors = get_errors(tenant=tenant, minutes=minutes, top=top)
    questions = get_common_questions(tenant=tenant, minutes=minutes, top=top)
    leads = get_leads(tenant=tenant, limit=limit)

    # Overview daily series (powers the "overview" chart)
    overview_daily = get_overview_daily(tenant=tenant, minutes=minutes, limit_days=45)

    # Optional extras (safe if not implemented)
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
        "sessions_by_channel": get_sessions_by_channel(tenant=tenant, minutes=minutes),
        "channels": channels,
        "channels_total": channels_total,
        "channel_breakdown": ch_breakdown,
        "whatsapp_store_share": wa_share,
        "top_intents": intents,
        "fallbacks": fallbacks,
        "errors": errors,
        "common_questions": questions,
        "leads": leads,
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


@bp.get("/conversations")
def api_conversations():
    from service.analytics_db import _conn, _ensure_ready, _since
    tenant = _tenant().upper()
    since = _since(_int_arg("minutes", 1440))
    try:
        before = int(request.args.get("before", "9223372036854775807"))
    except ValueError:
        abort(400)
    if not 1 <= before <= 9223372036854775807:
        abort(400)
    _ensure_ready()
    with _conn() as db:
        rows = db.execute(
            "SELECT id, ts_utc, channel, event_type, text FROM events "
            "WHERE tenant=? AND id<? AND ts_utc>=? AND event_type IN ('msg_in','msg_out') "
            "ORDER BY id DESC LIMIT 51", (tenant, before, since)
        ).fetchall()
    return jsonify(messages=[dict(row) for row in rows[:50]], has_more=len(rows) > 50,
                   next_before=rows[49]["id"] if len(rows) > 50 else None)


@bp.get("/integrations")
def api_integrations():
    import os
    tenant = _tenant()
    c = get_container()
    assigned = tenant == c.settings.BUSINESS_KEY
    return jsonify(
        tenant=tenant, whatsapp_assigned=assigned,
        meta_configured=assigned and bool(c.settings.WHATSAPP_APP_SECRET and c.settings.WHATSAPP_TOKEN and c.settings.WHATSAPP_PHONE_ID),
        twilio_configured=assigned and bool(os.getenv("TWILIO_AUTH_TOKEN") and os.getenv("TWILIO_WHATSAPP_NUMBER")),
        ai_configured=bool(os.getenv("OPENAI_API_KEY")),
    )
