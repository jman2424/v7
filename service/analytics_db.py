# service/analytics_db.py
from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Optional, Iterable

DB_PATH = os.environ.get("ANALYTICS_DB_PATH") or os.path.join("logs", "analytics.db")


# ----------------------------
# Basics
# ----------------------------
def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso_z(s: str) -> datetime:
    # expects "....Z"
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def _table_columns(con: sqlite3.Connection, table: str) -> set[str]:
    rows = con.execute(f"PRAGMA table_info({table})").fetchall()
    return {r["name"] for r in rows}


def _ensure_columns(con: sqlite3.Connection, table: str, columns_sql: dict[str, str]) -> None:
    existing = _table_columns(con, table)
    for col, ddl in columns_sql.items():
        if col not in existing:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def _json_dumps_safe(obj: Any) -> str:
    if obj is None:
        return ""
    try:
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return json.dumps({"_meta_error": "serialize_failed"}, separators=(",", ":"))


# ----------------------------
# Schema + migration
# ----------------------------
def init_db() -> None:
    """
    Must exist (app_factory imports init_db).
    Creates tables and migrates missing columns safely.
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
              event_type  TEXT NOT NULL,   -- msg_in | msg_out | fallback | error | ...
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

              -- dashboard expects these:
              name            TEXT,
              phone           TEXT,
              status          TEXT,
              tags_json       TEXT,

              UNIQUE(tenant, lead_id)
            );
            """
        )

        # If the table already existed from older versions, make sure required columns exist.
        _ensure_columns(
            con,
            "leads",
            {
                "name": "name TEXT",
                "phone": "phone TEXT",
                "status": "status TEXT",
                "tags_json": "tags_json TEXT",
            },
        )

        # Helpful indexes (fast dashboard)
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_tenant_ts ON events(tenant, ts_utc)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_tenant_type ON events(tenant, event_type)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_tenant_session ON events(tenant, session_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_leads_tenant_updated ON leads(tenant, updated_utc)")


# ----------------------------
# Writes
# ----------------------------
def upsert_lead(*, tenant: str, lead_id: str) -> None:
    tenant = (tenant or "default").strip()
    lead_id = (lead_id or "unknown").strip()
    with _conn() as con:
        con.execute(
            """
            INSERT INTO leads (tenant, lead_id, last_session_id, updated_utc, status, tags_json)
            VALUES (?, ?, '', ?, 'Open', '[]')
            ON CONFLICT(tenant, lead_id) DO UPDATE SET
              updated_utc = excluded.updated_utc;
            """,
            (tenant, lead_id, _utc_now_iso()),
        )


def set_lead_session(*, tenant: str, lead_id: str, session_id: str) -> None:
    tenant = (tenant or "default").strip()
    lead_id = (lead_id or "unknown").strip()
    session_id = (session_id or "unknown").strip()
    with _conn() as con:
        con.execute(
            """
            UPDATE leads
               SET last_session_id = ?,
                   updated_utc = ?
             WHERE tenant = ? AND lead_id = ?
            """,
            (session_id, _utc_now_iso(), tenant, lead_id),
        )


def update_lead(
    *,
    tenant: str,
    lead_id: str,
    name: Optional[str] = None,
    phone: Optional[str] = None,
    status: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> None:
    tenant = (tenant or "default").strip()
    lead_id = (lead_id or "unknown").strip()
    with _conn() as con:
        cols = _table_columns(con, "leads")
        sets = ["updated_utc=?"]
        vals: list[Any] = [_utc_now_iso()]

        if "name" in cols and name is not None:
            sets.append("name=?")
            vals.append(name.strip() if name else "")
        if "phone" in cols and phone is not None:
            sets.append("phone=?")
            vals.append(phone.strip() if phone else "")
        if "status" in cols and status is not None:
            sets.append("status=?")
            vals.append(status.strip() if status else "")
        if "tags_json" in cols and tags is not None:
            sets.append("tags_json=?")
            vals.append(_json_dumps_safe(tags))

        vals.extend([tenant, lead_id])
        con.execute(f"UPDATE leads SET {', '.join(sets)} WHERE tenant=? AND lead_id=?", vals)


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
    **_ignore: Any,  # IMPORTANT: prevents crashes if callers pass extra kwargs
) -> None:
    tenant = (tenant or "default").strip()
    channel = (channel or "unknown").strip()
    session_id = (session_id or "unknown").strip()
    event_type = (event_type or "unknown").strip()

    payload = meta if meta is not None else metadata
    meta_json = _json_dumps_safe(payload)

    with _conn() as con:
        con.execute(
            """
            INSERT INTO events (ts_utc, tenant, channel, session_id, lead_id, event_type,
                                text, intent, error_type, error_code, meta_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _utc_now_iso(),
                tenant,
                channel,
                session_id,
                (lead_id or "").strip(),
                event_type,
                (text or "").strip(),
                (intent or "").strip(),
                (error_type or "").strip(),
                (error_code or "").strip(),
                meta_json,
            ),
        )


# ----------------------------
# Reads for dashboard
# ----------------------------
@dataclass
class Kpis:
    inbound: int
    outbound: int
    total: int
    sessions: int
    fallbacks: int
    errors: int


def _since_utc(minutes: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(minutes=max(1, int(minutes)))
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def get_kpis(*, tenant: str, minutes: int) -> Kpis:
    tenant = (tenant or "default").strip()
    since = _since_utc(minutes)

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
             WHERE tenant=? AND ts_utc>=? AND event_type='msg_in'
            """,
            (tenant, since),
        ).fetchone()["n"]

    total = int(inbound) + int(outbound)
    return Kpis(int(inbound), int(outbound), int(total), int(sessions), int(fallbacks), int(errors))


def get_channels_split(*, tenant: str, minutes: int) -> dict[str, int]:
    """
    Returns keys like:
      web_in, web_out, whatsapp_in, whatsapp_out
    """
    tenant = (tenant or "default").strip()
    since = _since_utc(minutes)

    with _conn() as con:
        rows = con.execute(
            """
            SELECT channel, event_type, COUNT(*) AS n
              FROM events
             WHERE tenant=? AND ts_utc>=?
               AND event_type IN ('msg_in','msg_out')
             GROUP BY channel, event_type
            """,
            (tenant, since),
        ).fetchall()

    out: dict[str, int] = {"web_in": 0, "web_out": 0, "whatsapp_in": 0, "whatsapp_out": 0}
    for r in rows:
        ch = (r["channel"] or "unknown").lower()
        et = r["event_type"]
        key = None
        if ch.startswith("web"):
            key = "web_in" if et == "msg_in" else "web_out"
        elif ch.startswith("whatsapp") or ch.startswith("wa"):
            key = "whatsapp_in" if et == "msg_in" else "whatsapp_out"
        else:
            # bucket unknown into web for now (prevents blank charts)
            key = "web_in" if et == "msg_in" else "web_out"
        out[key] = out.get(key, 0) + int(r["n"])
    return out


def get_timeseries(*, tenant: str, minutes: int, bucket: int) -> list[dict[str, Any]]:
    """
    Returns list of buckets:
      [{ts:'2026-01-26T03:00:00Z', inbound: 2, outbound: 2}, ...]
    """
    tenant = (tenant or "default").strip()
    since = _since_utc(minutes)
    bucket = max(1, int(bucket))  # minutes per bucket

    with _conn() as con:
        rows = con.execute(
            """
            SELECT ts_utc, event_type
              FROM events
             WHERE tenant=? AND ts_utc>=?
               AND event_type IN ('msg_in','msg_out')
             ORDER BY ts_utc ASC
            """,
            (tenant, since),
        ).fetchall()

    # build buckets in python (portable + easy)
    start_dt = _parse_iso_z(since)
    end_dt = datetime.now(timezone.utc).replace(microsecond=0)
    # align start to bucket boundary
    aligned = start_dt.replace(second=0, microsecond=0)
    minute = (aligned.minute // bucket) * bucket
    aligned = aligned.replace(minute=minute)

    buckets: list[dict[str, Any]] = []
    cur = aligned
    while cur <= end_dt:
        buckets.append(
            {
                "ts": cur.isoformat().replace("+00:00", "Z"),
                "inbound": 0,
                "outbound": 0,
            }
        )
        cur = cur + timedelta(minutes=bucket)

    def _bucket_index(ts: datetime) -> int:
        delta = ts - aligned
        return max(0, min(len(buckets) - 1, int(delta.total_seconds() // (bucket * 60))))

    for r in rows:
        ts = _parse_iso_z(r["ts_utc"])
        i = _bucket_index(ts)
        if r["event_type"] == "msg_in":
            buckets[i]["inbound"] += 1
        else:
            buckets[i]["outbound"] += 1

    # trim leading empty buckets to make charts nicer (but keep at least 1)
    while len(buckets) > 1 and buckets[0]["inbound"] == 0 and buckets[0]["outbound"] == 0:
        buckets.pop(0)

    return buckets


def get_top_intents(*, tenant: str, minutes: int, top: int) -> list[dict[str, Any]]:
    tenant = (tenant or "default").strip()
    since = _since_utc(minutes)
    top = max(1, min(50, int(top)))

    with _conn() as con:
        rows = con.execute(
            """
            SELECT COALESCE(NULLIF(intent,''), 'unknown') AS intent, COUNT(*) AS n
              FROM events
             WHERE tenant=? AND ts_utc>=? AND event_type='msg_out'
             GROUP BY intent
             ORDER BY n DESC
             LIMIT ?
            """,
            (tenant, since, top),
        ).fetchall()

    return [{"label": r["intent"], "value": int(r["n"])} for r in rows]


def get_top_questions(*, tenant: str, minutes: int, top: int) -> list[dict[str, Any]]:
    tenant = (tenant or "default").strip()
    since = _since_utc(minutes)
    top = max(1, min(50, int(top)))

    with _conn() as con:
        rows = con.execute(
            """
            SELECT LOWER(TRIM(text)) AS q, COUNT(*) AS n
              FROM events
             WHERE tenant=? AND ts_utc>=? AND event_type='msg_in'
               AND text IS NOT NULL AND TRIM(text) != ''
             GROUP BY q
             ORDER BY n DESC
             LIMIT ?
            """,
            (tenant, since, top),
        ).fetchall()

    return [{"question": r["q"], "count": int(r["n"])} for r in rows]


def get_leads(*, tenant: str, limit: int = 50) -> list[dict[str, Any]]:
    tenant = (tenant or "default").strip()
    limit = max(1, min(200, int(limit)))

    with _conn() as con:
        cols = _table_columns(con, "leads")
        # always select safely even if older DB
        sel = [
            "lead_id",
            "updated_utc",
            "last_session_id",
        ]
        if "name" in cols:
            sel.append("COALESCE(name,'') AS name")
        else:
            sel.append("'' AS name")
        if "phone" in cols:
            sel.append("COALESCE(phone,'') AS phone")
        else:
            sel.append("'' AS phone")
        if "status" in cols:
            sel.append("COALESCE(status,'Open') AS status")
        else:
            sel.append("'Open' AS status")
        if "tags_json" in cols:
            sel.append("COALESCE(tags_json,'[]') AS tags_json")
        else:
            sel.append("'[]' AS tags_json")

        rows = con.execute(
            f"""
            SELECT {", ".join(sel)}
              FROM leads
             WHERE tenant=?
             ORDER BY updated_utc DESC
             LIMIT ?
            """,
            (tenant, limit),
        ).fetchall()

    out: list[dict[str, Any]] = []
    for r in rows:
        try:
            tags = json.loads(r["tags_json"] or "[]")
            if not isinstance(tags, list):
                tags = []
        except Exception:
            tags = []
        out.append(
            {
                "lead_id": r["lead_id"],
                "updated_utc": r["updated_utc"],
                "session_id": r["last_session_id"] or "",
                "name": r["name"] or "",
                "phone": r["phone"] or "",
                "status": r["status"] or "Open",
                "tags": tags,
            }
        )
    return out


def get_fallbacks(*, tenant: str, minutes: int, top: int) -> list[dict[str, Any]]:
    tenant = (tenant or "default").strip()
    since = _since_utc(minutes)
    top = max(1, min(50, int(top)))

    with _conn() as con:
        rows = con.execute(
            """
            SELECT LOWER(TRIM(text)) AS q, COUNT(*) AS n
              FROM events
             WHERE tenant=? AND ts_utc>=? AND event_type='fallback'
               AND text IS NOT NULL AND TRIM(text) != ''
             GROUP BY q
             ORDER BY n DESC
             LIMIT ?
            """,
            (tenant, since, top),
        ).fetchall()

    return [{"label": r["q"], "value": int(r["n"])} for r in rows]


def get_errors(*, tenant: str, minutes: int, top: int) -> list[dict[str, Any]]:
    tenant = (tenant or "default").strip()
    since = _since_utc(minutes)
    top = max(1, min(50, int(top)))

    with _conn() as con:
        rows = con.execute(
            """
            SELECT COALESCE(NULLIF(error_code,''), COALESCE(NULLIF(error_type,''), 'error')) AS label,
                   COUNT(*) AS n
              FROM events
             WHERE tenant=? AND ts_utc>=? AND event_type='error'
             GROUP BY label
             ORDER BY n DESC
             LIMIT ?
            """,
            (tenant, since, top),
        ).fetchall()

    return [{"label": r["label"], "value": int(r["n"])} for r in rows]
