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


def get_statistics(*, tenant: str, days: int, channel: str = "all", now: datetime | None = None, catalog: dict | None = None) -> dict:
    if not 1 <= days <= 365 or channel not in {"all", "web", "whatsapp"}:
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
        replies = reply_report(db, tenant, start, end, channel)
        previous_replies = reply_report(db, tenant, previous_start, start, channel)
        hours = [dict(row) for row in db.execute(f"SELECT substr(ts_utc,12,2) AS hour, SUM(event_type='msg_in') AS inbound, SUM(event_type='msg_out') AS outbound FROM events WHERE {condition} GROUP BY hour ORDER BY hour", current_params)]
        topics_daily = [dict(row) for row in db.execute(f"SELECT substr(ts_utc,1,10) AS day,COALESCE(NULLIF(intent,''),'unknown') AS topic,COUNT(*) AS count FROM events WHERE {condition} AND event_type='msg_out' GROUP BY day,topic", current_params)]
        from service.product_metrics import product_report
        commerce = product_report(db, tenant, start.isoformat(), end.isoformat(), channel, catalog or {})
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
            "intents": intents, "errors": errors, "fallbacks": fallbacks, "pipeline": pipeline,
            "replies":replies, "previous_replies":previous_replies, "hours":hours,
            "topics_daily":topics_daily, "commerce":commerce}


def reply_report(db, tenant, start, end, channel):
    """Pair each inbound to its route-generated response ID, never to another user."""
    condition = "i.tenant=? AND i.ts_utc>=? AND i.ts_utc<? AND i.event_type='msg_in'"
    values = (end.isoformat(),tenant.upper(),start.isoformat(),end.isoformat())
    if channel != 'all':
        condition += ' AND i.channel=?'
        values += (channel,)
    rows = [dict(row) for row in db.execute(f'''SELECT substr(i.ts_utc,1,10) AS day,
        COUNT(*) AS inbound, SUM(COALESCE(i.message_id,'')!='') AS eligible,
        COUNT(o.id) AS replied,
        SUM(CASE WHEN o.id IS NOT NULL AND o.intent NOT IN ('system_error','system_no_results','system_clarify','unknown','out_of_scope')
            AND COALESCE(json_extract(CASE WHEN json_valid(o.meta_json) THEN o.meta_json ELSE '{{}}' END,'$.fallback'),0)=0 THEN 1 ELSE 0 END) AS answered,
        SUM(CASE WHEN o.id IS NOT NULL THEN MAX(0,(julianday(o.ts_utc)-julianday(i.ts_utc))*86400) ELSE 0 END) AS response_seconds
        FROM events i LEFT JOIN events o ON o.tenant=i.tenant AND o.channel=i.channel AND o.session_id=i.session_id
          AND o.event_type='msg_out' AND COALESCE(i.message_id,'')!=''
          AND o.message_id=i.message_id || CASE WHEN i.channel='whatsapp' THEN ':out' ELSE ':reply' END
          AND o.ts_utc>=i.ts_utc AND o.ts_utc<?
        WHERE {condition} GROUP BY day ORDER BY day''', values)]
    total = {key:sum(row[key] for row in rows) for key in ('inbound','eligible','replied','answered','response_seconds')}
    return {'total':total,'daily':rows}
