# service/analytics_db.py
from __future__ import annotations

import csv
import io
import sqlite3
from flask import Response

DB_PATH = "logs/analytics.db"  # change if yours differs

def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def get_kpis(*, tenant: str, minutes: int) -> dict:
    # assumes events table has: tenant, ts_utc, event_type, session_id
    q = """
    WITH w AS (
      SELECT *
      FROM events
      WHERE tenant = ?
        AND ts_utc >= datetime('now', ?)
    )
    SELECT
      (SELECT COUNT(*) FROM w WHERE event_type='msg_in')  AS inbound,
      (SELECT COUNT(*) FROM w WHERE event_type='msg_out') AS outbound,
      (SELECT COUNT(*) FROM w WHERE event_type IN ('msg_in','msg_out')) AS total_messages,
      (SELECT COUNT(DISTINCT session_id) FROM w WHERE event_type IN ('msg_in','msg_out')) AS sessions,
      (SELECT COUNT(*) FROM w WHERE event_type='fallback') AS fallbacks,
      (SELECT COUNT(*) FROM w WHERE event_type='error') AS errors
    ;
    """
    window = f"-{int(minutes)} minutes"
    with _conn() as con:
        row = con.execute(q, (tenant, window)).fetchone()
    return {
        "tenant": tenant,
        "minutes": int(minutes),
        "inbound": int(row["inbound"] or 0),
        "outbound": int(row["outbound"] or 0),
        "total_messages": int(row["total_messages"] or 0),
        "sessions": int(row["sessions"] or 0),
        "fallbacks": int(row["fallbacks"] or 0),
        "errors": int(row["errors"] or 0),
    }

def get_timeseries(*, tenant: str, minutes: int, bucket_minutes: int) -> dict:
    # Bucket by hour-ish using integer division on unix epoch
    q = """
    WITH w AS (
      SELECT *
      FROM events
      WHERE tenant = ?
        AND ts_utc >= datetime('now', ?)
        AND event_type IN ('msg_in','msg_out')
    ),
    b AS (
      SELECT
        datetime((strftime('%s', ts_utc) / (? * 60)) * (? * 60), 'unixepoch') AS t_bucket,
        SUM(CASE WHEN event_type='msg_in'  THEN 1 ELSE 0 END) AS inbound,
        SUM(CASE WHEN event_type='msg_out' THEN 1 ELSE 0 END) AS outbound,
        COUNT(DISTINCT CASE WHEN event_type IN ('msg_in','msg_out') THEN session_id END) AS sessions
      FROM w
      GROUP BY t_bucket
      ORDER BY t_bucket ASC
    )
    SELECT * FROM b;
    """
    window = f"-{int(minutes)} minutes"
    bm = int(bucket_minutes)
    with _conn() as con:
        rows = con.execute(q, (tenant, window, bm, bm)).fetchall()

    points = []
    for r in rows:
        points.append({
            "t": r["t_bucket"],
            "inbound": int(r["inbound"] or 0),
            "outbound": int(r["outbound"] or 0),
            "sessions": int(r["sessions"] or 0),
        })

    return {"tenant": tenant, "minutes": int(minutes), "bucket": bm, "points": points}

def _top_kv(con, sql: str, params: tuple) -> list[dict]:
    rows = con.execute(sql, params).fetchall()
    return [{"key": r["key"], "count": int(r["count"] or 0)} for r in rows]

def get_insights(*, tenant: str, minutes: int, top: int) -> dict:
    window = f"-{int(minutes)} minutes"
    topn = int(top)

    with _conn() as con:
        # Channels: ONLY messages, not lead_upsert/session events
        channels = _top_kv(con, """
          SELECT channel AS key, COUNT(*) AS count
          FROM events
          WHERE tenant=?
            AND ts_utc >= datetime('now', ?)
            AND event_type IN ('msg_in','msg_out')
          GROUP BY channel
          ORDER BY count DESC
          LIMIT ?;
        """, (tenant, window, topn))

        # Intents: take from msg_out only (where intent exists)
        intents = _top_kv(con, """
          SELECT COALESCE(intent,'unknown') AS key, COUNT(*) AS count
          FROM events
          WHERE tenant=?
            AND ts_utc >= datetime('now', ?)
            AND event_type='msg_out'
          GROUP BY COALESCE(intent,'unknown')
          ORDER BY count DESC
          LIMIT ?;
        """, (tenant, window, topn))

        # Fallbacks: use explicit fallback events
        fallbacks = _top_kv(con, """
          SELECT COALESCE(intent,'fallback') AS key, COUNT(*) AS count
          FROM events
          WHERE tenant=?
            AND ts_utc >= datetime('now', ?)
            AND event_type='fallback'
          GROUP BY COALESCE(intent,'fallback')
          ORDER BY count DESC
          LIMIT ?;
        """, (tenant, window, topn))

        # Errors
        errors = _top_kv(con, """
          SELECT COALESCE(error_type,'error') AS key, COUNT(*) AS count
          FROM events
          WHERE tenant=?
            AND ts_utc >= datetime('now', ?)
            AND event_type='error'
          GROUP BY COALESCE(error_type,'error')
          ORDER BY count DESC
          LIMIT ?;
        """, (tenant, window, topn))

        # Common questions: count msg_in text (basic)
        common_questions = []
        rows = con.execute("""
          SELECT text AS text, COUNT(*) AS count
          FROM events
          WHERE tenant=?
            AND ts_utc >= datetime('now', ?)
            AND event_type='msg_in'
            AND text IS NOT NULL
            AND length(trim(text)) > 0
          GROUP BY text
          ORDER BY count DESC
          LIMIT ?;
        """, (tenant, window, topn)).fetchall()
        for r in rows:
            common_questions.append({"text": r["text"], "count": int(r["count"] or 0)})

    return {
        "tenant": tenant,
        "minutes": int(minutes),
        "channels": channels,
        "intents": intents,
        "fallbacks": fallbacks,
        "errors": errors,
        "common_questions": common_questions,
    }

def get_leads(*, tenant: str, limit: int) -> dict:
    q = """
    SELECT updated_utc, name, phone, status, tags
    FROM leads
    WHERE tenant=?
    ORDER BY updated_utc DESC
    LIMIT ?;
    """
    with _conn() as con:
        rows = con.execute(q, (tenant, int(limit))).fetchall()
    return {"items": [dict(r) for r in rows]}

def export_leads_csv(*, tenant: str) -> Response:
    data = get_leads(tenant=tenant, limit=5000)["items"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["updated_utc", "name", "phone", "status", "tags"])
    for r in data:
        w.writerow([r.get("updated_utc",""), r.get("name",""), r.get("phone",""), r.get("status",""), r.get("tags","")])
    buf.seek(0)

    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="leads_{tenant}.csv"'},
    )
