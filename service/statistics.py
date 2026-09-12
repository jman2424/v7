"""Bounded, aggregate-only company statistics from recorded channel events."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from service import analytics_db

_FALLBACK = "json_extract(CASE WHEN json_valid(meta_json) THEN meta_json ELSE '{}' END, '$.fallback')=1"
_SUMMARY = f"""
    COALESCE(SUM(event_type='msg_in'),0) AS inbound,
    COALESCE(SUM(event_type='msg_out'),0) AS outbound,
    COUNT(DISTINCT CASE WHEN event_type IN ('msg_in','msg_out') AND session_id!=''
        THEN channel || ':' || session_id END) AS sessions,
    COALESCE(SUM(event_type='msg_out' AND {_FALLBACK}),0) AS fallbacks,
    COALESCE(SUM(event_type='error'),0) AS errors,
    COUNT(DISTINCT CASE WHEN event_type='msg_out' AND intent IN ('human_handoff','handoff')
        AND session_id!='' THEN channel || ':' || session_id END) AS handoffs,
    COUNT(DISTINCT CASE WHEN event_type='msg_out' AND intent='handoff_contact_captured'
        AND COALESCE(lead_id,'')!='' THEN lead_id END) AS contacts
"""


def get_statistics(*, tenant: str, days: int, channel: str = "all", now: datetime | None = None) -> dict:
    if not 1 <= days <= 90 or channel not in {"all", "web", "whatsapp"}:
        raise ValueError("invalid_statistics_filter")
    analytics_db._ensure_ready()
    end = now or datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    previous_start = start - timedelta(days=days)
    condition = "tenant=? AND ts_utc>=? AND ts_utc<?"
    if channel != "all":
        condition += " AND channel=?"

    def params(left: datetime, right: datetime) -> tuple:
        values = (tenant.upper(), left.isoformat(), right.isoformat())
        return values + (channel,) if channel != "all" else values

    current_params = params(start, end)
    with analytics_db._conn() as db:
        # All panels share the same database snapshot and time boundary.
        db.execute("BEGIN")
        current = dict(db.execute(f"SELECT {_SUMMARY} FROM events WHERE {condition}", current_params).fetchone())
        previous = dict(db.execute(f"SELECT {_SUMMARY} FROM events WHERE {condition}", params(previous_start, start)).fetchone())
        daily_rows = db.execute(f"SELECT substr(ts_utc,1,10) AS day, {_SUMMARY} FROM events WHERE {condition} GROUP BY day ORDER BY day", current_params).fetchall()
        channels = [dict(row) for row in db.execute(f"SELECT channel, {_SUMMARY} FROM events WHERE {condition} GROUP BY channel ORDER BY channel", current_params)]
        intents = [dict(row) for row in db.execute(f"SELECT COALESCE(NULLIF(intent,''),'unknown') AS label, COUNT(*) AS count FROM events WHERE {condition} AND event_type='msg_out' GROUP BY label ORDER BY count DESC, label LIMIT 20", current_params)]
        errors = [dict(row) for row in db.execute(f"SELECT substr(COALESCE(NULLIF(error_code,''),'Unspecified error'),1,120) AS label, COUNT(*) AS count FROM events WHERE {condition} AND event_type='error' GROUP BY label ORDER BY count DESC, label LIMIT 20", current_params)]
        fallbacks = [dict(row) for row in db.execute(f"SELECT COALESCE(NULLIF(intent,''),'unknown') AS label, COUNT(*) AS count FROM events WHERE {condition} AND event_type='msg_out' AND {_FALLBACK} GROUP BY label ORDER BY count DESC, label LIMIT 20", current_params)]
        # Leads have no reliable channel or creation-time field. Show the current
        # company pipeline separately rather than inventing historical conversion.
        pipeline = {key: 0 for key in ("Open", "Contacted", "Qualified", "Won", "Lost", "Other")}
        for row in db.execute("SELECT COALESCE(NULLIF(status,''),'Open') AS status, COUNT(*) AS count FROM leads WHERE tenant=? GROUP BY status", (tenant.upper(),)):
            pipeline[row['status'] if row['status'] in pipeline else 'Other'] += row['count']
    daily_map = {row['day']: dict(row) for row in daily_rows}
    daily = []
    day = start.date()
    while day <= end.date():
        key = day.isoformat()
        daily.append(daily_map.get(key, {'day': key, **{name: 0 for name in current}}))
        day += timedelta(days=1)
    return {"tenant": tenant, "days": days, "channel": channel, "start": start.isoformat(),
            "end": end.isoformat(), "previous_start": previous_start.isoformat(),
            "current": current, "previous": previous, "daily": daily, "channels": channels,
            "intents": intents, "errors": errors, "fallbacks": fallbacks, "pipeline": pipeline}
