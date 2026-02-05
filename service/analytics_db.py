# service/analytics_db.py
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

DB_PATH = os.environ.get("ANALYTICS_DB_PATH", "/app/logs/analytics.db")

_INIT_LOCK = threading.Lock()
_INIT_DONE = False


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _since(minutes: int) -> str:
    m = int(minutes or 1440)
    if m < 1:
        m = 1
    return (datetime.now(timezone.utc) - timedelta(minutes=m)).replace(microsecond=0).isoformat()


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
        con.execute("PRAGMA busy_timeout=30000;")
        con.execute("PRAGMA foreign_keys=ON;")
    except Exception:
        pass
    return con


def _safe_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _table_columns(con: sqlite3.Connection, table: str) -> set[str]:
    rows = con.execute(f"PRAGMA table_info({table})").fetchall()
    return {r["name"] for r in rows}


def _ensure_columns(con: sqlite3.Connection, table: str, wanted: dict[str, str]) -> None:
    existing = _table_columns(con, table)
    for col, ddl in wanted.items():
        if col not in existing:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def _norm_channel(channel: str) -> str:
    ch = (channel or "web").strip().lower() or "web"
    return ch if ch in ("web", "whatsapp") else "web"


def _norm_tenant(tenant: str) -> str:
    return (tenant or "default").strip() or "default"


def _norm_session(session_id: str) -> str:
    return (session_id or "unknown").strip() or "unknown"


def _time_bucket(seconds: int = 10) -> str:
    # retry/double-submit protection window
    now = datetime.now(timezone.utc).replace(microsecond=0)
    s = now.second - (now.second % max(1, int(seconds)))
    return now.replace(second=s).isoformat()


def _make_dedupe_key(
    *,
    tenant: str,
    channel: str,
    session_id: str,
    event_type: str,
    intent: str,
    text: str,
    lead_id: str,
    store: str,
    fallback: bool,
    message_id: str,
) -> str:
    # If caller supplies message_id, make it deterministic. Otherwise use a small time bucket.
    bucket = message_id.strip() or _time_bucket(10)
    raw = f"{tenant}|{channel}|{session_id}|{event_type}|{intent}|{lead_id}|{store}|{int(bool(fallback))}|{text}|{bucket}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------
# Init / migrations
# ---------------------------------------------------------------------
def init_db() -> None:
    """
    Safe to call repeatedly.
    Creates tables and performs light migrations if older schema exists.

    IMPORTANT: This schema supports:
      - msg_in / msg_out events
      - fallbacks as a flag on msg_out rows (meta_json)
      - errors as separate rows (event_type='error') so they NEVER inflate outbound counts
      - dedupe_key to ignore duplicate webhook/widget retries
    """
    with _conn() as con:
        # Base tables (create with full modern columns)
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_utc TEXT NOT NULL,
                tenant TEXT NOT NULL,
                channel TEXT NOT NULL,
                session_id TEXT NOT NULL,
                event_type TEXT NOT NULL,          -- msg_in | msg_out | error
                intent TEXT,
                text TEXT,
                lead_id TEXT,
                error_code TEXT,
                error_type TEXT,
                dedupe_key TEXT,
                meta_json TEXT
            );
            """
        )

        con.execute(
            """
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant TEXT NOT NULL,
                lead_id TEXT NOT NULL,
                name TEXT,
                phone TEXT,
                status TEXT DEFAULT 'Open',
                tags TEXT DEFAULT '[]',
                updated_utc TEXT NOT NULL,
                last_session_id TEXT,
                UNIQUE(tenant, lead_id)
            );
            """
        )

        # Migrations for older DBs (add any missing columns)
        _ensure_columns(
            con,
            "events",
            {
                "text": "text TEXT",
                "lead_id": "lead_id TEXT",
                "error_code": "error_code TEXT",
                "error_type": "error_type TEXT",
                "dedupe_key": "dedupe_key TEXT",
            },
        )
        _ensure_columns(con, "leads", {"last_session_id": "last_session_id TEXT"})

        # Indexes
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_tenant_ts ON events(tenant, ts_utc)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_channel ON events(channel)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_lead_id ON events(lead_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_leads_tenant_updated ON leads(tenant, updated_utc)")

        # Dedupe: ignore duplicate inserts caused by retries/double-submit
        con.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_events_dedupe ON events(dedupe_key)")


def _ensure_ready() -> None:
    global _INIT_DONE
    if _INIT_DONE:
        return
    with _INIT_LOCK:
        if not _INIT_DONE:
            init_db()
            _INIT_DONE = True


# ---------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------
def upsert_lead(*, tenant: str, lead_id: str, name: Optional[str] = None, phone: Optional[str] = None) -> None:
    _ensure_ready()
    tenant = _norm_tenant(tenant)
    lead_id = (lead_id or "unknown").strip() or "unknown"
    now = _utc_now()

    with _conn() as con:
        con.execute(
            """
            INSERT INTO leads (tenant, lead_id, name, phone, status, tags, updated_utc)
            VALUES (?, ?, ?, ?, COALESCE(NULLIF(?,''),'Open'), COALESCE(NULLIF(?,''),'[]'), ?)
            ON CONFLICT(tenant, lead_id) DO UPDATE SET
              name = COALESCE(excluded.name, leads.name),
              phone = COALESCE(excluded.phone, leads.phone),
              updated_utc = excluded.updated_utc;
            """,
            (tenant, lead_id, name, phone, "Open", "[]", now),
        )


def set_lead_session(*, tenant: str, lead_id: str, session_id: str) -> None:
    _ensure_ready()
    tenant = _norm_tenant(tenant)
    lead_id = (lead_id or "unknown").strip() or "unknown"
    session_id = _norm_session(session_id)
    now = _utc_now()

    with _conn() as con:
        con.execute(
            """
            INSERT INTO leads (tenant, lead_id, updated_utc)
            VALUES (?, ?, ?)
            ON CONFLICT(tenant, lead_id) DO UPDATE SET
              updated_utc = excluded.updated_utc;
            """,
            (tenant, lead_id, now),
        )
        con.execute(
            """
            UPDATE leads
            SET last_session_id=?, updated_utc=?
            WHERE tenant=? AND lead_id=?;
            """,
            (session_id, now, tenant, lead_id),
        )


# ---------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------
def log_message(
    *,
    tenant: str,
    channel: str,
    direction: str,  # inbound | outbound
    session_id: str,
    intent: str = "unknown",
    text: str = "",
    lead_id: Optional[str] = None,
    store: Optional[str] = None,
    fallback: bool = False,
    message_id: str = "",
    # legacy fields (kept so old callers don't crash)
    error: bool = False,
    error_code: str = "",
    error_type: str = "",
) -> None:
    """
    Writes ONLY real chat messages:
      - msg_in (direction=inbound)
      - msg_out (direction=outbound)

    Fallbacks are NOT separate event rows.
    They are msg_out rows with meta_json.fallback = 1

    This is what you want:
      outbound KPI = msg_out where fallback=0
      fallbacks KPI = msg_out where fallback=1
      total KPI = inbound + outbound + fallbacks
    """
    _ensure_ready()

    tenant = _norm_tenant(tenant)
    ch = _norm_channel(channel)
    sid = _norm_session(session_id)
    direction = (direction or "inbound").strip().lower()
    event_type = "msg_in" if direction == "inbound" else "msg_out"

    intent = (intent or "unknown").strip() or "unknown"
    txt = text or ""
    lid = (lead_id or "").strip()
    st = (store or "").strip()

    meta = {
        "store": st or None,
        "fallback": bool(fallback),
        # legacy marker only (does not drive KPI errors, errors are separate rows)
        "error": bool(error),
    }

    dedupe_key = _make_dedupe_key(
        tenant=tenant,
        channel=ch,
        session_id=sid,
        event_type=event_type,
        intent=intent,
        text=txt,
        lead_id=lid,
        store=st,
        fallback=bool(fallback),
        message_id=message_id or "",
    )

    with _conn() as con:
        cols = _table_columns(con, "events")

        fields = ["ts_utc", "tenant", "channel", "session_id", "event_type", "intent", "meta_json"]
        vals: list[Any] = [_utc_now(), tenant, ch, sid, event_type, intent, json.dumps(meta, ensure_ascii=False)]

        if "text" in cols:
            fields.append("text")
            vals.append(txt)

        if "lead_id" in cols:
            fields.append("lead_id")
            vals.append(lid)

        if "error_code" in cols:
            fields.append("error_code")
            vals.append(error_code or "")

        if "error_type" in cols:
            fields.append("error_type")
            vals.append(error_type or "")

        if "dedupe_key" in cols:
            fields.append("dedupe_key")
            vals.append(dedupe_key)

        placeholders = ",".join(["?"] * len(fields))
        sql = f"INSERT OR IGNORE INTO events ({','.join(fields)}) VALUES ({placeholders})"
        con.execute(sql, tuple(vals))


def log_error(
    *,
    tenant: str,
    channel: str,
    session_id: str,
    lead_id: Optional[str] = None,
    error_code: str = "",
    error_type: str = "",
    meta: Optional[dict[str, Any]] = None,
    message_id: str = "",
) -> None:
    """
    Errors are separate rows:
      event_type='error'
    So they NEVER inflate outbound/total chat message counts.
    """
    _ensure_ready()

    tenant = _norm_tenant(tenant)
    ch = _norm_channel(channel)
    sid = _norm_session(session_id)
    lid = (lead_id or "").strip()

    m = meta or {}
    m["error"] = True

    dedupe_key = _make_dedupe_key(
        tenant=tenant,
        channel=ch,
        session_id=sid,
        event_type="error",
        intent="system_error",
        text=str(m.get("error") or ""),
        lead_id=lid,
        store="",
        fallback=False,
        message_id=message_id or "",
    )

    with _conn() as con:
        cols = _table_columns(con, "events")

        fields = ["ts_utc", "tenant", "channel", "session_id", "event_type", "intent", "meta_json"]
        vals: list[Any] = [_utc_now(), tenant, ch, sid, "error", "system_error", json.dumps(m, ensure_ascii=False)]

        if "lead_id" in cols:
            fields.append("lead_id")
            vals.append(lid)

        if "error_code" in cols:
            fields.append("error_code")
            vals.append(error_code or "")

        if "error_type" in cols:
            fields.append("error_type")
            vals.append(error_type or "")

        if "dedupe_key" in cols:
            fields.append("dedupe_key")
            vals.append(dedupe_key)

        placeholders = ",".join(["?"] * len(fields))
        sql = f"INSERT OR IGNORE INTO events ({','.join(fields)}) VALUES ({placeholders})"
        con.execute(sql, tuple(vals))


# Backwards compatible shim (old code calling log_event)
def log_event(*args, **kwargs):
    return log_message(*args, **kwargs)


# ---------------------------------------------------------------------
# Reads (Dashboard API)
# ---------------------------------------------------------------------
def get_kpis(*, tenant: str, minutes: int = 1440) -> dict[str, Any]:
    """
    ✅ Correct counting:
      inbound   = msg_in
      outbound  = msg_out where fallback=0
      fallbacks = msg_out where fallback=1
      errors    = error rows
      total     = inbound + outbound + fallbacks
    """
    _ensure_ready()
    tenant = _norm_tenant(tenant)
    since = _since(minutes)

    with _conn() as con:
        row = con.execute(
            """
            SELECT
              SUM(CASE WHEN event_type='msg_in' THEN 1 ELSE 0 END) AS inbound,

              SUM(CASE
                    WHEN event_type='msg_out'
                     AND COALESCE(json_extract(meta_json,'$.fallback'),0) = 0
                    THEN 1 ELSE 0 END
              ) AS outbound,

              SUM(CASE
                    WHEN event_type='msg_out'
                     AND COALESCE(json_extract(meta_json,'$.fallback'),0) = 1
                    THEN 1 ELSE 0 END
              ) AS fallbacks,

              COUNT(DISTINCT CASE WHEN event_type IN ('msg_in','msg_out') THEN session_id END) AS sessions,
              SUM(CASE WHEN event_type='error' THEN 1 ELSE 0 END) AS errors
            FROM events
            WHERE tenant=? AND ts_utc>=?;
            """,
            (tenant, since),
        ).fetchone()

        leads = con.execute(
            "SELECT COUNT(*) AS n FROM leads WHERE tenant=? AND updated_utc>=?;",
            (tenant, since),
        ).fetchone()["n"]

    inbound = int(row["inbound"] or 0)
    outbound = int(row["outbound"] or 0)
    fallbacks = int(row["fallbacks"] or 0)
    sessions = int(row["sessions"] or 0)
    errors = int(row["errors"] or 0)

    return {
        "inbound": inbound,
        "outbound": outbound,  # non-fallback only
        "fallbacks": fallbacks,
        "errors": errors,
        "sessions": sessions,
        "leads": int(leads or 0),
        "total": inbound + outbound + fallbacks,  # ✅ this matches what you want
    }


def get_timeseries(*, tenant: str, minutes: int = 1440, bucket_minutes: int = 60) -> list[dict[str, Any]]:
    """
    Time series for the MESSAGE VOLUME chart.

    ✅ outbound excludes fallbacks so you get:
      outbound = real replies
      fallbacks shown elsewhere
    """
    _ensure_ready()
    tenant = _norm_tenant(tenant)
    since = _since(minutes)

    # Current UI buckets by hour via substr(ts_utc,1,13)
    # (bucket_minutes is accepted but not used by this string-based scheme)
    with _conn() as con:
        rows = con.execute(
            """
            SELECT substr(ts_utc,1,13) AS t,
                   SUM(CASE WHEN event_type='msg_in' THEN 1 ELSE 0 END) AS inbound,
                   SUM(CASE
                         WHEN event_type='msg_out'
                          AND COALESCE(json_extract(meta_json,'$.fallback'),0) = 0
                         THEN 1 ELSE 0 END
                   ) AS outbound
            FROM events
            WHERE tenant=? AND ts_utc>=?
              AND event_type IN ('msg_in','msg_out')
            GROUP BY t
            ORDER BY t;
            """,
            (tenant, since),
        ).fetchall()

    return [{"t": r["t"], "inbound": int(r["inbound"] or 0), "outbound": int(r["outbound"] or 0)} for r in rows]


def get_sessions_timeseries(*, tenant: str, minutes: int = 1440, bucket_minutes: int = 60) -> list[dict[str, Any]]:
    _ensure_ready()
    tenant = _norm_tenant(tenant)
    since = _since(minutes)

    with _conn() as con:
        rows = con.execute(
            """
            SELECT substr(ts_utc,1,13) AS t,
                   COUNT(DISTINCT session_id) AS sessions
            FROM events
            WHERE tenant=? AND ts_utc>=?
              AND event_type IN ('msg_in','msg_out')
            GROUP BY t
            ORDER BY t;
            """,
            (tenant, since),
        ).fetchall()

    return [{"t": r["t"], "sessions": int(r["sessions"] or 0)} for r in rows]


def get_channels_split(*, tenant: str, minutes: int = 1440) -> dict[str, Any]:
    """
    Legacy helper (if anything still uses it):
    outbound excludes fallbacks.
    """
    _ensure_ready()
    tenant = _norm_tenant(tenant)
    since = _since(minutes)

    with _conn() as con:
        rows = con.execute(
            """
            SELECT channel,
                   SUM(CASE WHEN event_type='msg_in' THEN 1 ELSE 0 END) AS inbound,
                   SUM(CASE
                         WHEN event_type='msg_out'
                          AND COALESCE(json_extract(meta_json,'$.fallback'),0) = 0
                         THEN 1 ELSE 0 END
                   ) AS outbound
            FROM events
            WHERE tenant=? AND ts_utc>=?
              AND event_type IN ('msg_in','msg_out')
            GROUP BY channel;
            """,
            (tenant, since),
        ).fetchall()

    out: dict[str, Any] = {}
    for r in rows:
        ch = (r["channel"] or "unknown").strip().lower() or "unknown"
        inbound = int(r["inbound"] or 0)
        outbound = int(r["outbound"] or 0)
        out[ch] = {"inbound": inbound, "outbound": outbound, "total": inbound + outbound}
    return out


def get_top_intents(*, tenant: str, minutes: int = 1440, top: int = 10) -> list[dict[str, Any]]:
    """
    ✅ Top intents should represent REAL successful replies, not fallbacks.
    """
    _ensure_ready()
    tenant = _norm_tenant(tenant)
    since = _since(minutes)
    top = max(1, min(_safe_int(top, 10), 50))

    with _conn() as con:
        rows = con.execute(
            """
            SELECT COALESCE(NULLIF(intent,''),'unknown') AS intent,
                   COUNT(*) AS n
            FROM events
            WHERE tenant=? AND ts_utc>=?
              AND event_type='msg_out'
              AND COALESCE(json_extract(meta_json,'$.fallback'),0) = 0
            GROUP BY intent
            ORDER BY n DESC
            LIMIT ?;
            """,
            (tenant, since, top),
        ).fetchall()

    return [{"label": r["intent"], "count": int(r["n"] or 0)} for r in rows]


def get_fallbacks(*, tenant: str, minutes: int = 1440, top: int = 10) -> list[dict[str, Any]]:
    _ensure_ready()
    tenant = _norm_tenant(tenant)
    since = _since(minutes)
    top = max(1, min(_safe_int(top, 10), 50))

    with _conn() as con:
        rows = con.execute(
            """
            SELECT COALESCE(NULLIF(intent,''),'fallback') AS intent,
                   COUNT(*) AS n
            FROM events
            WHERE tenant=? AND ts_utc>=?
              AND event_type='msg_out'
              AND COALESCE(json_extract(meta_json,'$.fallback'),0) = 1
            GROUP BY intent
            ORDER BY n DESC
            LIMIT ?;
            """,
            (tenant, since, top),
        ).fetchall()

    return [{"label": r["intent"], "count": int(r["n"] or 0)} for r in rows]


def get_errors(*, tenant: str, minutes: int = 1440, top: int = 10) -> list[dict[str, Any]]:
    _ensure_ready()
    tenant = _norm_tenant(tenant)
    since = _since(minutes)
    top = max(1, min(_safe_int(top, 10), 50))

    with _conn() as con:
        cols = _table_columns(con, "events")
        code_expr = "COALESCE(NULLIF(error_code,''),'error')" if "error_code" in cols else "'error'"

        rows = con.execute(
            f"""
            SELECT {code_expr} AS code,
                   COUNT(*) AS n
            FROM events
            WHERE tenant=? AND ts_utc>=?
              AND event_type='error'
            GROUP BY code
            ORDER BY n DESC
            LIMIT ?;
            """,
            (tenant, since, top),
        ).fetchall()

    return [{"label": r["code"], "count": int(r["n"] or 0)} for r in rows]


def get_common_questions(*, tenant: str, minutes: int = 1440, top: int = 10) -> list[dict[str, Any]]:
    _ensure_ready()
    tenant = _norm_tenant(tenant)
    since = _since(minutes)
    top = max(1, min(_safe_int(top, 10), 50))

    with _conn() as con:
        cols = _table_columns(con, "events")
        if "text" not in cols:
            return []

        rows = con.execute(
            """
            SELECT LOWER(TRIM(COALESCE(text,''))) AS q,
                   COUNT(*) AS n
            FROM events
            WHERE tenant=? AND ts_utc>=?
              AND event_type='msg_in'
              AND TRIM(COALESCE(text,'')) != ''
            GROUP BY q
            ORDER BY n DESC
            LIMIT ?;
            """,
            (tenant, since, top),
        ).fetchall()

    return [{"question": r["q"], "count": int(r["n"] or 0)} for r in rows]


def get_leads(*, tenant: str, limit: int = 50) -> list[dict[str, Any]]:
    _ensure_ready()
    tenant = _norm_tenant(tenant)
    limit = max(1, min(_safe_int(limit, 50), 500))

    with _conn() as con:
        rows = con.execute(
            """
            SELECT lead_id, name, phone, status, tags, updated_utc, last_session_id
            FROM leads
            WHERE tenant=?
            ORDER BY updated_utc DESC
            LIMIT ?;
            """,
            (tenant, limit),
        ).fetchall()

    out: list[dict[str, Any]] = []
    for r in rows:
        raw_tags = r["tags"] or "[]"
        try:
            tags = json.loads(raw_tags)
            if not isinstance(tags, list):
                tags = []
        except Exception:
            tags = []

        out.append(
            {
                "lead_id": r["lead_id"],
                "name": r["name"],
                "phone": r["phone"],
                "status": r["status"] or "Open",
                "tags": tags,
                "updated_utc": r["updated_utc"],
                "last_session_id": r["last_session_id"],
            }
        )

    return out


# ---------------------------------------------------------------------
# "New" reads used by admin_api_routes
# ---------------------------------------------------------------------
def get_channel_breakdown(*, tenant: str, minutes: int = 1440) -> dict[str, dict[str, int]]:
    """
    ✅ outbound excludes fallbacks
    ✅ fallbacks are counted separately

    This is what makes your Channels chart do:
      Outbound = real replies (4)
      Fallbacks = fallback replies (2)
    """
    _ensure_ready()
    tenant = _norm_tenant(tenant)
    since = _since(minutes)

    base: dict[str, dict[str, int]] = {
        "web": {"inbound": 0, "outbound": 0, "fallbacks": 0},
        "whatsapp": {"inbound": 0, "outbound": 0, "fallbacks": 0},
    }

    with _conn() as con:
        rows = con.execute(
            """
            SELECT
              channel,
              SUM(CASE WHEN event_type='msg_in' THEN 1 ELSE 0 END) AS inbound,

              SUM(CASE
                    WHEN event_type='msg_out'
                     AND COALESCE(json_extract(meta_json,'$.fallback'),0) = 0
                    THEN 1 ELSE 0 END
              ) AS outbound,

              SUM(CASE
                    WHEN event_type='msg_out'
                     AND COALESCE(json_extract(meta_json,'$.fallback'),0) = 1
                    THEN 1 ELSE 0 END
              ) AS fallbacks
            FROM events
            WHERE tenant=? AND ts_utc>=?
              AND event_type IN ('msg_in','msg_out')
            GROUP BY channel;
            """,
            (tenant, since),
        ).fetchall()

    for r in rows:
        ch = (r["channel"] or "web").strip().lower() or "web"
        if ch not in base:
            base[ch] = {"inbound": 0, "outbound": 0, "fallbacks": 0}
        base[ch]["inbound"] = int(r["inbound"] or 0)
        base[ch]["outbound"] = int(r["outbound"] or 0)
        base[ch]["fallbacks"] = int(r["fallbacks"] or 0)

    return base


def get_whatsapp_store_share(*, tenant: str, minutes: int = 1440, limit: int = 12) -> list[dict[str, Any]]:
    _ensure_ready()
    tenant = _norm_tenant(tenant)
    since = _since(minutes)
    limit = max(1, min(_safe_int(limit, 12), 50))

    with _conn() as con:
        rows = con.execute(
            """
            SELECT
              COALESCE(NULLIF(json_extract(meta_json,'$.store'),''), 'international') AS store,
              COUNT(*) AS n
            FROM events
            WHERE tenant=? AND ts_utc>=?
              AND channel='whatsapp'
              AND event_type='msg_in'
            GROUP BY store
            ORDER BY n DESC
            LIMIT ?;
            """,
            (tenant, since, limit),
        ).fetchall()

    return [{"store": r["store"], "count": int(r["n"] or 0)} for r in rows]
