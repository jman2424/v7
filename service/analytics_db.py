# service/analytics_db.py
from __future__ import annotations

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


def _norm_tenant(t: Optional[str]) -> str:
    t = (t or "default").strip() or "default"
    return t.upper()


def _norm_channel(ch: Optional[str]) -> str:
    ch = (ch or "web").strip().lower() or "web"
    return ch if ch in ("web", "whatsapp") else "web"


def _safe_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except Exception:
        return default


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


def _table_columns(con: sqlite3.Connection, table: str) -> set[str]:
    try:
        rows = con.execute(f"PRAGMA table_info({table})").fetchall()
        return {r["name"] for r in rows}
    except Exception:
        return set()


def _ensure_columns(con: sqlite3.Connection, table: str, wanted: dict[str, str]) -> None:
    existing = _table_columns(con, table)
    for col, ddl in wanted.items():
        if col not in existing:
            try:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
            except Exception:
                pass


# ---------------------------------------------------------------------
# Boot / Schema (migration-safe superset)
# ---------------------------------------------------------------------
def init_db() -> None:
    with _conn() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_utc TEXT NOT NULL,
                tenant TEXT NOT NULL,
                channel TEXT NOT NULL,
                session_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                intent TEXT,
                text TEXT,
                lead_id TEXT,
                message_id TEXT,
                error_code TEXT,
                error_type TEXT,
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
                last_session_id TEXT,
                updated_utc TEXT NOT NULL,
                UNIQUE(tenant, lead_id)
            );
            """
        )

        # Migration-safe columns
        _ensure_columns(
            con,
            "events",
            {
                "intent": "intent TEXT",
                "text": "text TEXT",
                "lead_id": "lead_id TEXT",
                "message_id": "message_id TEXT",
                "error_code": "error_code TEXT",
                "error_type": "error_type TEXT",
                "meta_json": "meta_json TEXT",
            },
        )
        _ensure_columns(
            con,
            "leads",
            {
                "tenant": "tenant TEXT",
                "lead_id": "lead_id TEXT",
                "name": "name TEXT",
                "phone": "phone TEXT",
                "status": "status TEXT",
                "tags": "tags TEXT",
                "last_session_id": "last_session_id TEXT",
                "updated_utc": "updated_utc TEXT",
            },
        )

        try:
            con.execute("CREATE INDEX IF NOT EXISTS idx_events_tenant_ts ON events(tenant, ts_utc)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_events_channel ON events(channel)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_events_lead_id ON events(lead_id)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_events_msgid ON events(message_id)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_leads_tenant_updated ON leads(tenant, updated_utc)")
        except Exception:
            pass

        # ✅ DEDUPE: only when message_id is present
        # One message_id should only produce ONE msg_in / msg_out / error row.
        try:
            con.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uniq_events_dedupe
                ON events(tenant, event_type, message_id)
                WHERE message_id IS NOT NULL AND message_id != '';
                """
            )
        except Exception:
            pass


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
    tenant_n = _norm_tenant(tenant)
    lead_id_n = (lead_id or "unknown").strip() or "unknown"
    now = _utc_now()

    with _conn() as con:
        cols = _table_columns(con, "leads")
        if "tenant" in cols:
            con.execute(
                """
                INSERT INTO leads (tenant, lead_id, name, phone, status, tags, updated_utc)
                VALUES (?, ?, ?, ?, 'Open', '[]', ?)
                ON CONFLICT(tenant, lead_id) DO UPDATE SET
                  name = COALESCE(excluded.name, leads.name),
                  phone = COALESCE(excluded.phone, leads.phone),
                  updated_utc = excluded.updated_utc;
                """,
                (tenant_n, lead_id_n, name, phone, now),
            )
        else:
            con.execute(
                "INSERT OR REPLACE INTO leads (lead_id, name, phone, updated_utc) VALUES (?, ?, ?, ?);",
                (lead_id_n, name, phone, now),
            )


def set_lead_session(*, tenant: str, lead_id: str, session_id: str) -> None:
    _ensure_ready()
    tenant_n = _norm_tenant(tenant)
    lead_id_n = (lead_id or "unknown").strip() or "unknown"
    session_id_n = (session_id or "unknown").strip() or "unknown"
    now = _utc_now()

    with _conn() as con:
        cols = _table_columns(con, "leads")
        if "tenant" in cols:
            con.execute(
                """
                INSERT INTO leads (tenant, lead_id, updated_utc)
                VALUES (?, ?, ?)
                ON CONFLICT(tenant, lead_id) DO UPDATE SET
                  updated_utc = excluded.updated_utc;
                """,
                (tenant_n, lead_id_n, now),
            )
            if "last_session_id" in cols:
                con.execute(
                    """
                    UPDATE leads
                    SET last_session_id=?, updated_utc=?
                    WHERE tenant=? AND lead_id=?;
                    """,
                    (session_id_n, now, tenant_n, lead_id_n),
                )


def update_lead_status(*, tenant: str, lead_id: str, status: str) -> bool:
    """Update one tenant-owned lead without exposing cross-tenant records."""
    _ensure_ready()
    tenant_n = _norm_tenant(tenant)
    lead_id_n = (lead_id or "").strip()
    status_n = (status or "").strip()
    if not lead_id_n or not status_n:
        return False

    with _conn() as con:
        result = con.execute(
            """
            UPDATE leads
            SET status=?, updated_utc=?
            WHERE tenant=? AND lead_id=?;
            """,
            (status_n, _utc_now(), tenant_n, lead_id_n),
        )
    return result.rowcount == 1


# ---------------------------------------------------------------------
# Core writer (single truth)
# ---------------------------------------------------------------------
def _insert_event(
    *,
    tenant: str,
    channel: str,
    session_id: str,
    event_type: str,
    intent: str = "",
    text: str = "",
    lead_id: str = "",
    message_id: str = "",
    error_code: str = "",
    error_type: str = "",
    meta_json: str = "",
) -> None:
    _ensure_ready()

    tenant_n = _norm_tenant(tenant)
    ch = _norm_channel(channel)
    sid = (session_id or "unknown").strip() or "unknown"
    et = (event_type or "event").strip() or "event"

    msgid = (message_id or "").strip()

    with _conn() as con:
        cols = _table_columns(con, "events")

        fields = ["ts_utc", "tenant", "channel", "session_id", "event_type"]
        vals: list[Any] = [_utc_now(), tenant_n, ch, sid, et]

        if "intent" in cols:
            fields.append("intent")
            vals.append((intent or "").strip().lower())

        if "text" in cols:
            fields.append("text")
            vals.append(text or "")

        if "lead_id" in cols:
            fields.append("lead_id")
            vals.append((lead_id or "").strip())

        if "message_id" in cols:
            fields.append("message_id")
            vals.append(msgid)

        if "error_code" in cols:
            fields.append("error_code")
            vals.append(error_code or "")

        if "error_type" in cols:
            fields.append("error_type")
            vals.append(error_type or "")

        if "meta_json" in cols:
            fields.append("meta_json")
            vals.append(meta_json or "")

        sql = f"INSERT INTO events ({','.join(fields)}) VALUES ({','.join(['?'] * len(fields))})"

        try:
            con.execute(sql, tuple(vals))
        except sqlite3.IntegrityError:
            # ✅ Dedup hit (same tenant/event_type/message_id) -> ignore
            return


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
    error: bool = False,  # legacy flag stored in meta_json
    error_code: str = "",
    error_type: str = "",
    message_id: str = "",
) -> None:
    """
    Transport-boundary messages only:
      event_type = msg_in / msg_out

    message_id enables dedupe (critical for web retries)
    """
    event_type = "msg_in" if (direction or "inbound").strip().lower() == "inbound" else "msg_out"
    meta = {"store": store, "fallback": bool(fallback), "error": bool(error)}
    _insert_event(
        tenant=tenant,
        channel=channel,
        session_id=session_id,
        event_type=event_type,
        intent=intent or "unknown",
        text=text or "",
        lead_id=(lead_id or ""),
        message_id=message_id or "",
        error_code=error_code or "",
        error_type=error_type or "",
        meta_json=json.dumps(meta, ensure_ascii=False),
    )


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
    Transport-boundary errors only:
      event_type = error
    """
    m = dict(meta or {})
    m["error"] = True
    _insert_event(
        tenant=tenant,
        channel=channel,
        session_id=session_id,
        event_type="error",
        intent="system_error",
        lead_id=(lead_id or ""),
        message_id=message_id or "",
        error_code=error_code or "",
        error_type=error_type or "",
        meta_json=json.dumps(m, ensure_ascii=False),
    )


def log_event(*args: Any, **kwargs: Any) -> None:
    """
    Accept multiple signatures used across the repo.

    1) log_event(tenant=..., channel=..., session_id=..., event_type=..., intent=..., text=..., lead_id=..., meta_json=..., message_id=...)
    2) log_event(tenant, {"type": "...", "channel": "...", "session_id": "...", ...})
    """
    try:
        # Signature (tenant, dict)
        if len(args) >= 2 and isinstance(args[1], dict):
            tenant = args[0]
            payload = args[1] or {}
            event_type = payload.get("type") or payload.get("event_type") or "event"
            channel = payload.get("channel") or "web"
            session_id = payload.get("session_id") or payload.get("sid") or "unknown"
            intent = payload.get("intent") or ""
            text = payload.get("text") or ""
            lead_id = payload.get("lead_id") or ""
            message_id = payload.get("message_id") or ""
            meta = payload.get("meta") or {}
            meta_json = payload.get("meta_json") or json.dumps(meta, ensure_ascii=False)
            error_code = payload.get("error_code") or ""
            error_type = payload.get("error_type") or ""

            if event_type == "error":
                log_error(
                    tenant=str(tenant),
                    channel=str(channel),
                    session_id=str(session_id),
                    lead_id=str(lead_id) if lead_id else None,
                    error_code=str(error_code),
                    error_type=str(error_type),
                    meta=meta if isinstance(meta, dict) else None,
                    message_id=str(message_id),
                )
                return

            _insert_event(
                tenant=str(tenant),
                channel=str(channel),
                session_id=str(session_id),
                event_type=str(event_type),
                intent=str(intent),
                text=str(text),
                lead_id=str(lead_id),
                message_id=str(message_id),
                error_code=str(error_code),
                error_type=str(error_type),
                meta_json=str(meta_json),
            )
            return

        # Signature (kwargs)
        tenant = kwargs.get("tenant") or (args[0] if args else "default")
        channel = kwargs.get("channel") or kwargs.get("ch") or (args[1] if len(args) > 1 else "web")
        session_id = kwargs.get("session_id") or kwargs.get("sid") or (args[2] if len(args) > 2 else "unknown")
        event_type = kwargs.get("event_type") or kwargs.get("type") or (args[3] if len(args) > 3 else "event")
        intent = kwargs.get("intent") or ""
        text = kwargs.get("text") or ""
        lead_id = kwargs.get("lead_id") or ""
        message_id = kwargs.get("message_id") or ""
        meta_json = kwargs.get("meta_json") or ""
        error_code = kwargs.get("error_code") or ""
        error_type = kwargs.get("error_type") or ""

        if event_type == "error":
            log_error(
                tenant=str(tenant),
                channel=str(channel),
                session_id=str(session_id),
                lead_id=str(lead_id) if lead_id else None,
                error_code=str(error_code),
                error_type=str(error_type),
                meta=None,
                message_id=str(message_id),
            )
            return

        _insert_event(
            tenant=str(tenant),
            channel=str(channel),
            session_id=str(session_id),
            event_type=str(event_type),
            intent=str(intent),
            text=str(text),
            lead_id=str(lead_id),
            message_id=str(message_id),
            error_code=str(error_code),
            error_type=str(error_type),
            meta_json=str(meta_json),
        )
    except Exception:
        return


# ---------------------------------------------------------------------
# Reads (Dashboard API)
# ---------------------------------------------------------------------
def get_kpis(*, tenant: str, minutes: int = 1440) -> dict[str, Any]:
    _ensure_ready()
    tenant_n = _norm_tenant(tenant)
    since = _since(minutes)

    with _conn() as con:
        row = con.execute(
            """
            SELECT
              SUM(CASE WHEN event_type='msg_in'  THEN 1 ELSE 0 END) AS inbound,
              SUM(CASE WHEN event_type='msg_out' THEN 1 ELSE 0 END) AS outbound,
              COUNT(DISTINCT CASE WHEN event_type IN ('msg_in','msg_out') THEN session_id END) AS sessions,
              SUM(CASE WHEN event_type='msg_out' AND json_extract(COALESCE(meta_json,'{}'),'$.fallback') = 1 THEN 1 ELSE 0 END) AS fallbacks,
              SUM(CASE WHEN event_type='error' THEN 1 ELSE 0 END) AS errors
            FROM events
            WHERE tenant=? AND ts_utc>=?;
            """,
            (tenant_n, since),
        ).fetchone()

        leads_cols = _table_columns(con, "leads")
        if "tenant" in leads_cols:
            leads = con.execute(
                "SELECT COUNT(*) AS n FROM leads WHERE tenant=? AND updated_utc>=?;",
                (tenant_n, since),
            ).fetchone()["n"]
        else:
            leads = con.execute("SELECT COUNT(*) AS n FROM leads WHERE updated_utc>=?;", (since,)).fetchone()["n"]

    inbound = int(row["inbound"] or 0)
    outbound = int(row["outbound"] or 0)
    fallbacks = int(row["fallbacks"] or 0)
    errors = int(row["errors"] or 0)
    outbound_net = max(0, outbound - fallbacks - errors)

    return {
        "tenant": tenant_n,
        "minutes": int(minutes),
        "inbound": inbound,
        "outbound": outbound,
        "outbound_net": outbound_net,
        "total": inbound + outbound,
        "sessions": int(row["sessions"] or 0),
        "leads": int(leads or 0),
        "fallbacks": fallbacks,
        "errors": errors,
    }


def get_sales_funnel(*, tenant: str, minutes: int = 1440) -> dict[str, int]:
    """Return tenant-owned lead stages plus recent human-handoff demand.

    Pipeline stages are current records and therefore intentionally not limited
    to the activity window. Handoff counts are event-based and use the supplied
    window, which makes them useful for prioritising today's follow-up work.
    """
    _ensure_ready()
    tenant_n = _norm_tenant(tenant)
    since = _since(minutes)
    stages = {"Open": 0, "Contacted": 0, "Qualified": 0, "Won": 0, "Lost": 0}

    with _conn() as con:
        lead_rows = con.execute(
            """
            SELECT COALESCE(NULLIF(status, ''), 'Open') AS status, COUNT(*) AS n
            FROM leads
            WHERE tenant=?
            GROUP BY COALESCE(NULLIF(status, ''), 'Open');
            """,
            (tenant_n,),
        ).fetchall()
        handoff_row = con.execute(
            """
            SELECT COUNT(DISTINCT session_id) AS n
            FROM events
            WHERE tenant=? AND ts_utc>=? AND event_type='msg_out'
              AND intent='human_handoff';
            """,
            (tenant_n, since),
        ).fetchone()
        contact_row = con.execute(
            """
            SELECT COUNT(DISTINCT lead_id) AS n
            FROM events
            WHERE tenant=? AND ts_utc>=? AND event_type='msg_out'
              AND intent='handoff_contact_captured' AND COALESCE(lead_id, '') != '';
            """,
            (tenant_n, since),
        ).fetchone()

    other = 0
    for row in lead_rows:
        status = str(row["status"] or "Open")
        count = int(row["n"] or 0)
        if status in stages:
            stages[status] = count
        else:
            other += count

    return {
        "total": sum(stages.values()) + other,
        "active": stages["Open"] + stages["Contacted"] + stages["Qualified"],
        "open": stages["Open"],
        "contacted": stages["Contacted"],
        "qualified": stages["Qualified"],
        "won": stages["Won"],
        "lost": stages["Lost"],
        "other": other,
        "handoffs": int(handoff_row["n"] or 0),
        "contacts_captured": int(contact_row["n"] or 0),
    }


def get_timeseries(*, tenant: str, minutes: int = 1440, bucket_minutes: int = 60) -> list[dict[str, Any]]:
    _ensure_ready()
    tenant_n = _norm_tenant(tenant)
    since = _since(minutes)

    with _conn() as con:
        rows = con.execute(
            """
            SELECT substr(ts_utc,1,13) AS t,
                   SUM(CASE WHEN event_type='msg_in'  THEN 1 ELSE 0 END) AS inbound,
                   SUM(CASE WHEN event_type='msg_out' THEN 1 ELSE 0 END) AS outbound
            FROM events
            WHERE tenant=? AND ts_utc>=?
              AND event_type IN ('msg_in','msg_out')
            GROUP BY t
            ORDER BY t;
            """,
            (tenant_n, since),
        ).fetchall()

    return [{"t": r["t"], "inbound": int(r["inbound"] or 0), "outbound": int(r["outbound"] or 0)} for r in rows]


def get_sessions_timeseries(*, tenant: str, minutes: int = 1440, bucket_minutes: int = 60) -> list[dict[str, Any]]:
    _ensure_ready()
    tenant_n = _norm_tenant(tenant)
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
            (tenant_n, since),
        ).fetchall()

    return [{"t": r["t"], "sessions": int(r["sessions"] or 0)} for r in rows]


def get_channels_split(*, tenant: str, minutes: int = 1440) -> dict[str, Any]:
    _ensure_ready()
    tenant_n = _norm_tenant(tenant)
    since = _since(minutes)

    with _conn() as con:
        rows = con.execute(
            """
            SELECT channel,
                   SUM(CASE WHEN event_type='msg_in'  THEN 1 ELSE 0 END) AS inbound,
                   SUM(CASE WHEN event_type='msg_out' THEN 1 ELSE 0 END) AS outbound
            FROM events
            WHERE tenant=? AND ts_utc>=?
              AND event_type IN ('msg_in','msg_out')
            GROUP BY channel;
            """,
            (tenant_n, since),
        ).fetchall()

    out: dict[str, Any] = {}
    for r in rows:
        ch = (r["channel"] or "unknown").strip().lower() or "unknown"
        inbound = int(r["inbound"] or 0)
        outbound = int(r["outbound"] or 0)
        out[ch] = {"inbound": inbound, "outbound": outbound, "total": inbound + outbound}
    return out


def get_sessions_by_channel(*, tenant: str, minutes: int = 1440) -> dict[str, int]:
    """
    ✅ NEW: For dashboard "Sessions" split web vs whatsapp.
    Counts distinct session_id per channel, for msg_in/msg_out window.
    """
    _ensure_ready()
    tenant_n = _norm_tenant(tenant)
    since = _since(minutes)

    base = {"web": 0, "whatsapp": 0}

    with _conn() as con:
        rows = con.execute(
            """
            SELECT channel, COUNT(DISTINCT session_id) AS n
            FROM events
            WHERE tenant=? AND ts_utc>=?
              AND event_type IN ('msg_in','msg_out')
            GROUP BY channel;
            """,
            (tenant_n, since),
        ).fetchall()

    for r in rows:
        ch = (r["channel"] or "web").strip().lower() or "web"
        if ch not in base:
            base[ch] = 0
        base[ch] = int(r["n"] or 0)

    return base


def get_top_intents(*, tenant: str, minutes: int = 1440, top: int = 10) -> list[dict[str, Any]]:
    _ensure_ready()
    tenant_n = _norm_tenant(tenant)
    since = _since(minutes)
    top = max(1, min(_safe_int(top, 10), 50))

    with _conn() as con:
        cols = _table_columns(con, "events")
        if "intent" not in cols:
            return []
        rows = con.execute(
            """
            SELECT COALESCE(NULLIF(intent,''),'unknown') AS intent,
                   COUNT(*) AS n
            FROM events
            WHERE tenant=? AND ts_utc>=?
              AND event_type='msg_out'
            GROUP BY intent
            ORDER BY n DESC
            LIMIT ?;
            """,
            (tenant_n, since, top),
        ).fetchall()

    return [{"label": r["intent"], "count": int(r["n"] or 0)} for r in rows]


def get_fallbacks(*, tenant: str, minutes: int = 1440, top: int = 10) -> list[dict[str, Any]]:
    _ensure_ready()
    tenant_n = _norm_tenant(tenant)
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
              AND json_extract(COALESCE(meta_json,'{}'),'$.fallback') = 1
            GROUP BY intent
            ORDER BY n DESC
            LIMIT ?;
            """,
            (tenant_n, since, top),
        ).fetchall()

    return [{"label": r["intent"], "count": int(r["n"] or 0)} for r in rows]


def get_errors(*, tenant: str, minutes: int = 1440, top: int = 10) -> list[dict[str, Any]]:
    _ensure_ready()
    tenant_n = _norm_tenant(tenant)
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
            (tenant_n, since, top),
        ).fetchall()

    return [{"label": r["code"], "count": int(r["n"] or 0)} for r in rows]


def get_common_questions(*, tenant: str, minutes: int = 1440, top: int = 10) -> list[dict[str, Any]]:
    _ensure_ready()
    tenant_n = _norm_tenant(tenant)
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
            (tenant_n, since, top),
        ).fetchall()

    return [{"question": r["q"], "count": int(r["n"] or 0)} for r in rows]


def get_leads(*, tenant: str, limit: int = 50) -> list[dict[str, Any]]:
    _ensure_ready()
    tenant_n = _norm_tenant(tenant)
    limit = max(1, min(_safe_int(limit, 50), 500))

    with _conn() as con:
        cols = _table_columns(con, "leads")
        has_tenant = "tenant" in cols

        if has_tenant:
            rows = con.execute(
                """
                SELECT lead_id, name, phone, status, tags, updated_utc, last_session_id
                FROM leads
                WHERE tenant=?
                ORDER BY updated_utc DESC
                LIMIT ?;
                """,
                (tenant_n, limit),
            ).fetchall()
        else:
            rows = con.execute(
                """
                SELECT lead_id, name, phone, status, tags, updated_utc, last_session_id
                FROM leads
                ORDER BY updated_utc DESC
                LIMIT ?;
                """,
                (limit,),
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


def get_overview_daily(*, tenant: str, minutes: int = 1440, limit_days: int = 45) -> list[dict[str, Any]]:
    _ensure_ready()
    tenant_n = _norm_tenant(tenant)
    since = _since(minutes)
    limit_days = max(1, min(_safe_int(limit_days, 45), 365))

    with _conn() as con:
        rows = con.execute(
            """
            SELECT
              substr(ts_utc,1,10) AS d,
              SUM(CASE WHEN event_type='msg_in'  THEN 1 ELSE 0 END) AS inbound,
              SUM(CASE WHEN event_type='msg_out' THEN 1 ELSE 0 END) AS outbound,
              SUM(CASE WHEN event_type='msg_out' AND json_extract(COALESCE(meta_json,'{}'),'$.fallback') = 1 THEN 1 ELSE 0 END) AS fallbacks,
              SUM(CASE WHEN event_type='error' THEN 1 ELSE 0 END) AS errors
            FROM events
            WHERE tenant=? AND ts_utc>=?
            GROUP BY d
            ORDER BY d DESC
            LIMIT ?;
            """,
            (tenant_n, since, limit_days),
        ).fetchall()

    out: list[dict[str, Any]] = []
    for r in reversed(rows):
        inbound = int(r["inbound"] or 0)
        outbound = int(r["outbound"] or 0)
        fallbacks = int(r["fallbacks"] or 0)
        errors = int(r["errors"] or 0)
        outbound_net = max(0, outbound - fallbacks - errors)
        out.append(
            {
                "d": r["d"],
                "inbound": inbound,
                "outbound": outbound,
                "fallbacks": fallbacks,
                "errors": errors,
                "outbound_net": outbound_net,
            }
        )
    return out


def get_channel_breakdown(*, tenant: str, minutes: int = 1440) -> dict[str, dict[str, int]]:
    _ensure_ready()
    tenant_n = _norm_tenant(tenant)
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
              SUM(CASE WHEN event_type='msg_in'  THEN 1 ELSE 0 END) AS inbound,
              SUM(CASE WHEN event_type='msg_out' THEN 1 ELSE 0 END) AS outbound,
              SUM(CASE WHEN event_type='msg_out' AND json_extract(COALESCE(meta_json,'{}'),'$.fallback') = 1 THEN 1 ELSE 0 END) AS fallbacks
            FROM events
            WHERE tenant=? AND ts_utc>=?
              AND event_type IN ('msg_in','msg_out')
            GROUP BY channel;
            """,
            (tenant_n, since),
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
    tenant_n = _norm_tenant(tenant)
    since = _since(minutes)
    limit = max(1, min(_safe_int(limit, 12), 50))

    with _conn() as con:
        rows = con.execute(
            """
            SELECT
              COALESCE(NULLIF(json_extract(COALESCE(meta_json,'{}'),'$.store'),''), 'international') AS store,
              COUNT(*) AS n
            FROM events
            WHERE tenant=? AND ts_utc>=?
              AND channel='whatsapp'
              AND event_type='msg_in'
            GROUP BY store
            ORDER BY n DESC
            LIMIT ?;
            """,
            (tenant_n, since, limit),
        ).fetchall()

    return [{"store": r["store"], "count": int(r["n"] or 0)} for r in rows]
