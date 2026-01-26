# service/analytics_db.py
from __future__ import annotations

import json
import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

DB_PATH = os.environ.get("ANALYTICS_DB_PATH") or os.path.join("logs", "analytics.db")

_INIT_LOCK = threading.Lock()
_INIT_DONE = False


# -----------------------------
# Core helpers
# -----------------------------
def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row

    # Reliability under concurrency
    try:
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
        con.execute("PRAGMA foreign_keys=ON;")
        con.execute("PRAGMA busy_timeout=30000;")
    except Exception:
        # PRAGMAs can fail on some platforms; not fatal
        pass

    return con


def _table_columns(con: sqlite3.Connection, table: str) -> set[str]:
    rows = con.execute(f"PRAGMA table_info({table})").fetchall()
    return {r["name"] for r in rows}


def _ensure_columns(con: sqlite3.Connection, table: str, wanted: dict[str, str]) -> None:
    existing = _table_columns(con, table)
    for col, ddl in wanted.items():
        if col not in existing:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def _ensure_ready() -> None:
    global _INIT_DONE
    if _INIT_DONE:
        return
    with _INIT_LOCK:
        if _INIT_DONE:
            return
        init_db()
        _INIT_DONE = True


def init_db() -> None:
    """
    REQUIRED by app_factory: init_db()
    Safe to call repeatedly.
    """
    with _conn() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
              id          INTEGER PRIMARY KEY AUTOINCREMENT,
              ts_utc      TEXT NOT NULL,
              tenant      TEXT NOT NULL,
              channel     TEXT NOT NULL,
              session_id  TEXT NOT NULL,
              lead_id     TEXT,
              event_type  TEXT NOT NULL,
              text        TEXT,
              intent      TEXT,
              error_type  TEXT,
              error_code  TEXT,
              meta_json   TEXT
            );
            """
        )

        con.execute(
            """
            CREATE TABLE IF NOT EXISTS leads (
              id              INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant          TEXT NOT NULL,
              lead_id         TEXT NOT NULL,
              last_session_id TEXT,
              updated_utc     TEXT NOT NULL,
              UNIQUE(tenant, lead_id)
            );
            """
        )

        # Dashboard-compatible lead columns
        _ensure_columns(
            con,
            "leads",
            {
                "name": "name TEXT",
                "phone": "phone TEXT",
                "status": "status TEXT",
                "tags": "tags TEXT",         # legacy string/json
                "tags_json": "tags_json TEXT",  # preferred json string
            },
        )

        # Indexes for speed
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_tenant_ts ON events(tenant, ts_utc)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_tenant_type_ts ON events(tenant, event_type, ts_utc)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_tenant_channel_ts ON events(tenant, channel, ts_utc)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_tenant_session ON events(tenant, session_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_leads_tenant_updated ON leads(tenant, updated_utc)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_leads_tenant_lead ON leads(tenant, lead_id)")


def _since_iso(minutes: int) -> str:
    minutes = max(1, int(minutes or 1440))
    dt = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sqlite_ts_expr() -> str:
    # ts_utc stored like "2026-01-26T22:00:00Z"
    # Convert to "2026-01-26 22:00:00"
    return "replace(replace(ts_utc,'T',' '),'Z','')"


def _bucket_expr(bucket_minutes: int) -> str:
    """
    Floor timestamps to a bucket size.
    Returns SQL expression producing "YYYY-MM-DD HH:MM:00"
    """
    bucket_minutes = max(5, int(bucket_minutes or 60))
    ts_expr = _sqlite_ts_expr()
    return f"""
    datetime(
      strftime('%Y-%m-%d %H:', {ts_expr}) ||
      printf('%02d:00', (cast(strftime('%M',{ts_expr}) as int)/{bucket_minutes})*{bucket_minutes})
    )
    """


# -----------------------------
# Writes
# -----------------------------
def upsert_lead(*, tenant: str, lead_id: str) -> None:
    _ensure_ready()
    tenant = (tenant or "default").strip() or "default"
    lead_id = (lead_id or "unknown").strip() or "unknown"
    now = _utc_now_iso()

    with _conn() as con:
        con.execute(
            """
            INSERT INTO leads (tenant, lead_id, last_session_id, updated_utc, status, tags, tags_json)
            VALUES (?, ?, '', ?, 'Open', '[]', '[]')
            ON CONFLICT(tenant, lead_id) DO UPDATE SET
              updated_utc = excluded.updated_utc;
            """,
            (tenant, lead_id, now),
        )


def set_lead_session(*, tenant: str, lead_id: str, session_id: str) -> None:
    _ensure_ready()
    tenant = (tenant or "default").strip() or "default"
    lead_id = (lead_id or "unknown").strip() or "unknown"
    session_id = (session_id or "unknown").strip() or "unknown"
    now = _utc_now_iso()

    with _conn() as con:
        con.execute(
            """
            UPDATE leads
            SET last_session_id=?, updated_utc=?
            WHERE tenant=? AND lead_id=?
            """,
            (session_id, now, tenant, lead_id),
        )


def log_event(
    *,
    tenant: str,
    channel: str,
    session_id: str,
    event_type: str,
    text: str = "",
    lead_id: str = "",
    intent: str = "",
    error_type: str = "",
    error_code: str = "",
    meta: Optional[dict[str, Any]] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    """
    Accepts BOTH meta= and metadata= (prevents crash).
    """
    _ensure_ready()

    tenant = (tenant or "default").strip() or "default"
    channel = (channel or "unknown").strip() or "unknown"
    session_id = (session_id or "unknown").strip() or "unknown"
    event_type = (event_type or "unknown").strip() or "unknown"

    payload = meta if meta is not None else metadata
    meta_json = ""
    if payload is not None:
        try:
            meta_json = json.dumps(payload, ensure_ascii=False)
        except Exception:
            meta_json = json.dumps({"_meta_error": "serialize_failed"}, ensure_ascii=False)

    with _conn() as con:
        con.execute(
            """
            INSERT INTO events (
              ts_utc, tenant, channel, session_id, lead_id,
              event_type, text, intent, error_type, error_code, meta_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _utc_now_iso(),
                tenant,
                channel,
                session_id,
                lead_id or "",
                event_type,
                text or "",
                intent or "",
                error_type or "",
                error_code or "",
                meta_json,
            ),
        )


# -----------------------------
# Dashboard reads
# -----------------------------
def get_kpis(*, tenant: str, minutes: int = 1440) -> dict[str, Any]:
    """
    KPI rules:
    - inbound/outbound/total count ONLY msg_in/msg_out
    - fallbacks/errors are separate event types
    - sessions = distinct session_id among message events
    """
    _ensure_ready()
    tenant = (tenant or "default").strip() or "default"
    since = _since_iso(minutes)

    with _conn() as con:
        inbound = con.execute(
            "SELECT COUNT(*) AS n FROM events WHERE tenant=? AND ts_utc>=? AND event_type='msg_in'",
            (tenant, since),
        ).fetchone()["n"]

        outbound = con.execute(
            "SELECT COUNT(*) AS n FROM events WHERE tenant=? AND ts_utc>=? AND event_type='msg_out'",
            (tenant, since),
        ).fetchone()["n"]

        fallbacks = con.execute(
            "SELECT COUNT(*) AS n FROM events WHERE tenant=? AND ts_utc>=? AND event_type='fallback'",
            (tenant, since),
        ).fetchone()["n"]

        errors = con.execute(
            "SELECT COUNT(*) AS n FROM events WHERE tenant=? AND ts_utc>=? AND event_type='error'",
            (tenant, since),
        ).fetchone()["n"]

        sessions = con.execute(
            """
            SELECT COUNT(DISTINCT session_id) AS n
            FROM events
            WHERE tenant=? AND ts_utc>=? AND event_type IN ('msg_in','msg_out')
            """,
            (tenant, since),
        ).fetchone()["n"]

    inbound = int(inbound or 0)
    outbound = int(outbound or 0)
    fallbacks = int(fallbacks or 0)
    errors = int(errors or 0)
    sessions = int(sessions or 0)

    total = inbound + outbound
    return {
        "inbound": inbound,
        "outbound": outbound,
        "total": total,
        "sessions": sessions,
        "fallbacks": fallbacks,
        "errors": errors,
        "fallback_rate": (fallbacks / float(inbound or 1)),
        "error_rate": (errors / float(total or 1)),
    }


def get_channels_split(*, tenant: str, minutes: int = 1440) -> dict[str, Any]:
    """
    Counts ONLY message events (fixes the '9' bug).
    Returns per-channel inbound/outbound/total.
    """
    _ensure_ready()
    tenant = (tenant or "default").strip() or "default"
    since = _since_iso(minutes)

    with _conn() as con:
        rows = con.execute(
            """
            SELECT channel,
                   SUM(CASE WHEN event_type='msg_in'  THEN 1 ELSE 0 END) AS inbound,
                   SUM(CASE WHEN event_type='msg_out' THEN 1 ELSE 0 END) AS outbound
            FROM events
            WHERE tenant=? AND ts_utc>=? AND event_type IN ('msg_in','msg_out')
            GROUP BY channel
            ORDER BY (inbound+outbound) DESC
            """,
            (tenant, since),
        ).fetchall()

    out: dict[str, Any] = {}
    for r in rows:
        ch = (r["channel"] or "unknown").strip() or "unknown"
        inbound = int(r["inbound"] or 0)
        outbound = int(r["outbound"] or 0)
        out[ch] = {"inbound": inbound, "outbound": outbound, "total": inbound + outbound}
    return out


def get_timeseries(*, tenant: str, minutes: int = 1440, bucket_minutes: int = 60) -> list[dict[str, Any]]:
    """
    Message volume per bucket (inbound/outbound).
    """
    _ensure_ready()
    tenant = (tenant or "default").strip() or "default"
    since = _since_iso(minutes)
    b = _bucket_expr(bucket_minutes)

    with _conn() as con:
        rows = con.execute(
            f"""
            SELECT {b} AS bucket,
                   SUM(CASE WHEN event_type='msg_in'  THEN 1 ELSE 0 END) AS inbound,
                   SUM(CASE WHEN event_type='msg_out' THEN 1 ELSE 0 END) AS outbound
            FROM events
            WHERE tenant=? AND ts_utc>=? AND event_type IN ('msg_in','msg_out')
            GROUP BY bucket
            ORDER BY bucket ASC
            """,
            (tenant, since),
        ).fetchall()

    return [{"t": r["bucket"], "inbound": int(r["inbound"] or 0), "outbound": int(r["outbound"] or 0)} for r in rows]


def get_sessions_timeseries(*, tenant: str, minutes: int = 1440, bucket_minutes: int = 60) -> list[dict[str, Any]]:
    """
    Sessions per bucket (distinct session_id in each bucket).
    This powers your 'SESSIONS per bucket' chart.
    """
    _ensure_ready()
    tenant = (tenant or "default").strip() or "default"
    since = _since_iso(minutes)
    b = _bucket_expr(bucket_minutes)

    with _conn() as con:
        rows = con.execute(
            f"""
            SELECT {b} AS bucket,
                   COUNT(DISTINCT session_id) AS sessions
            FROM events
            WHERE tenant=? AND ts_utc>=? AND event_type IN ('msg_in','msg_out')
            GROUP BY bucket
            ORDER BY bucket ASC
            """,
            (tenant, since),
        ).fetchall()

    return [{"t": r["bucket"], "sessions": int(r["sessions"] or 0)} for r in rows]


def get_top_intents(*, tenant: str, minutes: int = 1440, top: int = 10) -> list[dict[str, Any]]:
    _ensure_ready()
    tenant = (tenant or "default").strip() or "default"
    since = _since_iso(minutes)
    top = max(1, min(int(top or 10), 50))

    with _conn() as con:
        rows = con.execute(
            """
            SELECT COALESCE(NULLIF(intent,''),'unknown') AS intent, COUNT(*) AS n
            FROM events
            WHERE tenant=? AND ts_utc>=? AND event_type='msg_out'
            GROUP BY intent
            ORDER BY n DESC
            LIMIT ?
            """,
            (tenant, since, top),
        ).fetchall()

    return [{"label": r["intent"], "count": int(r["n"] or 0)} for r in rows]


def get_fallbacks(*, tenant: str, minutes: int = 1440, top: int = 10) -> list[dict[str, Any]]:
    _ensure_ready()
    tenant = (tenant or "default").strip() or "default"
    since = _since_iso(minutes)
    top = max(1, min(int(top or 10), 50))

    with _conn() as con:
        rows = con.execute(
            """
            SELECT COALESCE(NULLIF(intent,''),'fallback') AS intent, COUNT(*) AS n
            FROM events
            WHERE tenant=? AND ts_utc>=? AND event_type='fallback'
            GROUP BY intent
            ORDER BY n DESC
            LIMIT ?
            """,
            (tenant, since, top),
        ).fetchall()

    return [{"label": r["intent"], "count": int(r["n"] or 0)} for r in rows]


def get_errors(*, tenant: str, minutes: int = 1440, top: int = 10) -> list[dict[str, Any]]:
    _ensure_ready()
    tenant = (tenant or "default").strip() or "default"
    since = _since_iso(minutes)
    top = max(1, min(int(top or 10), 50))

    with _conn() as con:
        rows = con.execute(
            """
            SELECT COALESCE(NULLIF(error_code,''),'error') AS code, COUNT(*) AS n
            FROM events
            WHERE tenant=? AND ts_utc>=? AND event_type='error'
            GROUP BY code
            ORDER BY n DESC
            LIMIT ?
            """,
            (tenant, since, top),
        ).fetchall()

    return [{"label": r["code"], "count": int(r["n"] or 0)} for r in rows]


def get_common_questions(*, tenant: str, minutes: int = 1440, top: int = 10) -> list[dict[str, Any]]:
    """
    Common inbound texts (lowercased).
    """
    _ensure_ready()
    tenant = (tenant or "default").strip() or "default"
    since = _since_iso(minutes)
    top = max(1, min(int(top or 10), 50))

    with _conn() as con:
        rows = con.execute(
            """
            SELECT LOWER(TRIM(COALESCE(text,''))) AS q, COUNT(*) AS n
            FROM events
            WHERE tenant=? AND ts_utc>=? AND event_type='msg_in' AND TRIM(COALESCE(text,''))!=''
            GROUP BY q
            ORDER BY n DESC
            LIMIT ?
            """,
            (tenant, since, top),
        ).fetchall()

    return [{"question": r["q"], "count": int(r["n"] or 0)} for r in rows]


def get_leads(*, tenant: str, limit: int = 50) -> list[dict[str, Any]]:
    """
    Returns latest leads in a dashboard-friendly shape.
    """
    _ensure_ready()
    tenant = (tenant or "default").strip() or "default"
    limit = max(1, min(int(limit or 50), 500))

    with _conn() as con:
        cols = _table_columns(con, "leads")

        name_sel = "name" if "name" in cols else "'' AS name"
        phone_sel = "phone" if "phone" in cols else "'' AS phone"
        status_sel = "status" if "status" in cols else "'Open' AS status"

        # Prefer tags_json, fallback to tags
        if "tags_json" in cols and "tags" in cols:
            tags_sel = "COALESCE(NULLIF(tags_json,''), NULLIF(tags,''), '[]') AS tags_any"
        elif "tags_json" in cols:
            tags_sel = "COALESCE(NULLIF(tags_json,''), '[]') AS tags_any"
        elif "tags" in cols:
            tags_sel = "COALESCE(NULLIF(tags,''), '[]') AS tags_any"
        else:
            tags_sel = "'[]' AS tags_any"

        q = f"""
        SELECT lead_id, updated_utc,
               {name_sel},
               {phone_sel},
               {status_sel},
               {tags_sel}
        FROM leads
        WHERE tenant=?
        ORDER BY updated_utc DESC
        LIMIT ?
        """

        rows = con.execute(q, (tenant, limit)).fetchall()

    out: list[dict[str, Any]] = []
    for r in rows:
        raw = r["tags_any"] or "[]"
        try:
            tags = json.loads(raw)
            if not isinstance(tags, list):
                tags = []
        except Exception:
            tags = []
        out.append(
            {
                "lead_id": r["lead_id"],
                "updated_utc": r["updated_utc"],
                "name": r["name"],
                "phone": r["phone"],
                "status": r["status"],
                "tags": tags,
            }
        )
    return out
