"""Bounded, aggregate-only company statistics from recorded channel events."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from service import analytics_db, session_store

_FALLBACK = "json_extract(CASE WHEN json_valid(meta_json) THEN meta_json ELSE '{}' END, '$.fallback')=1"
_PG_JSON = "CASE WHEN pg_input_is_valid(meta_json, 'jsonb') THEN meta_json::jsonb ELSE '{}'::jsonb END"
_PG_FALLBACK = f"COALESCE(({_PG_JSON} ->> 'fallback') IN ('true', '1'), false)"


def _summary(fallback):
    return f"""
    COALESCE(SUM(CASE WHEN event_type='msg_in' THEN 1 ELSE 0 END),0) AS inbound,
    COALESCE(SUM(CASE WHEN event_type='msg_out' THEN 1 ELSE 0 END),0) AS outbound,
    COUNT(DISTINCT CASE WHEN event_type IN ('msg_in','msg_out') AND session_id!=''
        THEN channel || ':' || session_id END) AS sessions,
    COALESCE(SUM(CASE WHEN event_type='msg_out' AND {fallback} THEN 1 ELSE 0 END),0) AS fallbacks,
    COALESCE(SUM(CASE WHEN event_type='error' THEN 1 ELSE 0 END),0) AS errors,
    COUNT(DISTINCT CASE WHEN event_type='msg_out' AND intent IN ('human_handoff','handoff')
        AND session_id!='' THEN channel || ':' || session_id END) AS handoffs,
    COUNT(DISTINCT CASE WHEN event_type='msg_out' AND intent='handoff_contact_captured'
        AND COALESCE(lead_id,'')!='' THEN lead_id END) AS contacts
"""


def _rows(db, sql, values=(), *, postgres=False):
    if postgres:
        return analytics_db._pg_rows(db, sql, values)
    return [dict(row) for row in db.execute(sql, values)]


def get_statistics(*, tenant: str, days: int, channel: str = "all", now: datetime | None = None, catalog: dict | None = None, offers: list | None = None) -> dict:
    if not 1 <= days <= 365 or channel not in {"all", "web", "whatsapp"}:
        raise ValueError("invalid_statistics_filter")
    analytics_db._ensure_ready()
    end = now or datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    previous_start = start - timedelta(days=days)
    postgres = session_store._using_postgres()
    tenant_key = tenant if postgres else tenant.upper()
    placeholder = "%s" if postgres else "?"
    events = "v7_private.events" if postgres else "events"
    leads = "v7_private.leads" if postgres else "leads"
    fallback = _PG_FALLBACK if postgres else _FALLBACK
    summary = _summary(fallback)
    condition = f"tenant={placeholder} AND ts_utc>={placeholder} AND ts_utc<{placeholder}"
    if channel != "all":
        condition += f" AND channel={placeholder}"

    def params(left: datetime, right: datetime) -> tuple:
        values = (tenant_key, left.isoformat(), right.isoformat())
        return values + (channel,) if channel != "all" else values

    current_params = params(start, end)
    connection = (session_store.postgres_connection(tenant_key, repeatable_read=True)
                  if postgres else analytics_db._conn())
    with connection as db:
        # All panels share the same database snapshot and time boundary.
        if not postgres:
            db.execute("BEGIN")
        def rows(sql, values=current_params):
            return _rows(db, sql, values, postgres=postgres)
        current = rows(f"SELECT {summary} FROM {events} WHERE {condition}")[0]
        previous = rows(f"SELECT {summary} FROM {events} WHERE {condition}", params(previous_start, start))[0]
        daily_rows = rows(f"SELECT substr(ts_utc,1,10) AS day, {summary} FROM {events} WHERE {condition} GROUP BY day ORDER BY day")
        channels = rows(f"SELECT channel, {summary} FROM {events} WHERE {condition} GROUP BY channel ORDER BY channel")
        intents = rows(f"SELECT COALESCE(NULLIF(intent,''),'unknown') AS label, COUNT(*) AS count FROM {events} WHERE {condition} AND event_type='msg_out' GROUP BY label ORDER BY count DESC, label LIMIT 20")
        errors = rows(f"SELECT substr(COALESCE(NULLIF(error_code,''),'Unspecified error'),1,120) AS label, COUNT(*) AS count FROM {events} WHERE {condition} AND event_type='error' GROUP BY label ORDER BY count DESC, label LIMIT 20")
        fallbacks = rows(f"SELECT COALESCE(NULLIF(intent,''),'unknown') AS label, COUNT(*) AS count FROM {events} WHERE {condition} AND event_type='msg_out' AND {fallback} GROUP BY label ORDER BY count DESC, label LIMIT 20")
        # Leads have no reliable channel or creation-time field. Show the current
        # company pipeline separately rather than inventing historical conversion.
        pipeline = {key: 0 for key in ("Open", "Contacted", "Qualified", "Won", "Lost", "Other")}
        for row in rows(f"SELECT COALESCE(NULLIF(status,''),'Open') AS status, COUNT(*) AS count FROM {leads} WHERE tenant={placeholder} GROUP BY status", (tenant_key,)):
            pipeline[row['status'] if row['status'] in pipeline else 'Other'] += row['count']
        replies = reply_report(db, tenant, start, end, channel, postgres=postgres)
        previous_replies = reply_report(db, tenant, previous_start, start, channel, postgres=postgres)
        hours = rows(f"SELECT substr(ts_utc,12,2) AS hour, SUM(CASE WHEN event_type='msg_in' THEN 1 ELSE 0 END) AS inbound, SUM(CASE WHEN event_type='msg_out' THEN 1 ELSE 0 END) AS outbound FROM {events} WHERE {condition} GROUP BY hour ORDER BY hour")
        topics_daily = rows(f"SELECT substr(ts_utc,1,10) AS day,COALESCE(NULLIF(intent,''),'unknown') AS topic,COUNT(*) AS count FROM {events} WHERE {condition} AND event_type='msg_out' GROUP BY day,topic")
        from service.offer_metrics import offer_report
        promotions = offer_report(db, tenant, start, end, channel, offers or [], postgres=postgres)
        from service.product_metrics import product_report
        commerce = product_report(db, tenant, start.isoformat(), end.isoformat(), channel, catalog or {}, postgres=postgres)
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
            "topics_daily":topics_daily, "commerce":commerce, "offers":promotions}


def reply_report(db, tenant, start, end, channel, *, postgres=False):
    """Pair each inbound to its route-generated response ID, never to another user."""
    placeholder = "%s" if postgres else "?"
    events = "v7_private.events" if postgres else "events"
    condition = f"i.tenant={placeholder} AND i.ts_utc>={placeholder} AND i.ts_utc<{placeholder} AND i.event_type='msg_in'"
    values = (end.isoformat(),tenant if postgres else tenant.upper(),start.isoformat(),end.isoformat())
    if channel != 'all':
        condition += f' AND i.channel={placeholder}'
        values += (channel,)
    answered = (f"NOT ({_PG_FALLBACK.replace('meta_json', 'o.meta_json')})" if postgres else
                "COALESCE(json_extract(CASE WHEN json_valid(o.meta_json) THEN o.meta_json ELSE '{}' END,'$.fallback'),0)=0")
    if postgres:
        inbound_timestamp = "CASE WHEN pg_input_is_valid(i.ts_utc,'timestamptz') THEN i.ts_utc::timestamptz END"
        outbound_timestamp = "CASE WHEN pg_input_is_valid(o.ts_utc,'timestamptz') THEN o.ts_utc::timestamptz END"
        timed = f"isfinite({inbound_timestamp}) AND isfinite({outbound_timestamp})"
        duration = f"GREATEST(0,EXTRACT(EPOCH FROM ({outbound_timestamp})-({inbound_timestamp})))"
    else:
        timed = "julianday(i.ts_utc) IS NOT NULL AND julianday(o.ts_utc) IS NOT NULL"
        duration = "MAX(0,(julianday(o.ts_utc)-julianday(i.ts_utc))*86400)"
    # Preserve message/reply counts even when legacy timestamp strings cannot
    # measure elapsed time. The separate denominator keeps averages accurate.
    response_seconds = f"CASE WHEN {timed} THEN {duration} ELSE 0 END"
    rows = _rows(db, f'''SELECT substr(i.ts_utc,1,10) AS day,
        COUNT(*) AS inbound, SUM(CASE WHEN COALESCE(i.message_id,'')!='' THEN 1 ELSE 0 END) AS eligible,
        COUNT(o.id) AS replied,
        SUM(CASE WHEN o.id IS NOT NULL AND {timed} THEN 1 ELSE 0 END) AS timed_replies,
        SUM(CASE WHEN o.id IS NOT NULL AND o.intent NOT IN ('system_error','system_no_results','system_clarify','unknown','out_of_scope')
            AND {answered} THEN 1 ELSE 0 END) AS answered,
        SUM(CASE WHEN o.id IS NOT NULL THEN {response_seconds} ELSE 0 END) AS response_seconds
        FROM {events} i LEFT JOIN {events} o ON o.tenant=i.tenant AND o.channel=i.channel AND o.session_id=i.session_id
          AND o.event_type='msg_out' AND COALESCE(i.message_id,'')!=''
          AND o.message_id=i.message_id || CASE WHEN i.channel='whatsapp' THEN ':out' ELSE ':reply' END
          AND o.ts_utc>=i.ts_utc AND o.ts_utc<{placeholder}
        WHERE {condition} GROUP BY day ORDER BY day''', values, postgres=postgres)
    if postgres:
        for row in rows:
            row['response_seconds'] = float(row['response_seconds'])
    total = {key:sum(row[key] for row in rows) for key in ('inbound','eligible','replied','timed_replies','answered','response_seconds')}
    return {'total':total,'daily':rows}
