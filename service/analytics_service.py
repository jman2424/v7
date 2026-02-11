# service/analytics_service.py
from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

SettingsLike = Any


# ---------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------
def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _utc_now_iso() -> str:
    return _utc_iso(datetime.now(timezone.utc))


def _since_iso(minutes: int) -> str:
    m = int(minutes or 1440)
    if m < 1:
        m = 1
    return _utc_iso(datetime.now(timezone.utc) - timedelta(minutes=m))


def _clamp_int(v: Any, default: int, lo: int, hi: int) -> int:
    try:
        x = int(v)
    except Exception:
        return default
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


# ---------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------
@dataclass
class AnalyticsService:
    settings: SettingsLike

    def __post_init__(self) -> None:
        self.db_path = os.getenv("ANALYTICS_DB_PATH", "/app/logs/analytics.db")
        self.ensure_ready()

    # -----------------------
    # SQLite
    # -----------------------
    def _conn(self) -> sqlite3.Connection:
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        con = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA journal_mode=WAL;")
            con.execute("PRAGMA synchronous=NORMAL;")
            con.execute("PRAGMA foreign_keys=ON;")
            con.execute("PRAGMA busy_timeout=30000;")
        except Exception:
            pass
        return con

    def _table_columns(self, con: sqlite3.Connection, table: str) -> set[str]:
        rows = con.execute(f"PRAGMA table_info({table})").fetchall()
        return {r["name"] for r in rows}

    def _ensure_column(self, con: sqlite3.Connection, table: str, col: str, ddl: str) -> None:
        cols = self._table_columns(con, table)
        if col not in cols:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")

    # -----------------------
    # Schema / migrations
    # -----------------------
    def ensure_ready(self) -> None:
        """
        Migration-safe schema.

        IMPORTANT: leads must be UNIQUE(tenant, lead_id) not lead_id PRIMARY KEY,
        otherwise multiple businesses collide.
        """
        with self._conn() as con:
            # EVENTS
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
                  error_code TEXT,
                  error_type TEXT,
                  meta_json TEXT
                );
                """
            )

            # LEADS (multi-tenant safe)
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

            # indexes
            con.execute("CREATE INDEX IF NOT EXISTS idx_events_tenant_ts ON events(tenant, ts_utc);")
            con.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);")
            con.execute("CREATE INDEX IF NOT EXISTS idx_events_channel ON events(channel);")
            con.execute("CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);")
            con.execute("CREATE INDEX IF NOT EXISTS idx_events_lead ON events(lead_id);")
            con.execute("CREATE INDEX IF NOT EXISTS idx_leads_tenant_updated ON leads(tenant, updated_utc);")

    # -----------------------
    # Lead APIs (SIGNATURE FIX)
    # -----------------------
    def upsert_lead(
        self,
        *,
        tenant: str,
        lead_id: str,
        phone: Optional[str] = None,
        name: Optional[str] = None,
    ) -> None:
        """
        Signature matches MessageHandler / routes.
        """
        tenant = (tenant or "default").strip() or "default"
        lead_id = (lead_id or "unknown").strip() or "unknown"
        now = _utc_now_iso()

        try:
            with self._conn() as con:
                con.execute(
                    """
                    INSERT INTO leads (tenant, lead_id, name, phone, status, tags, updated_utc)
                    VALUES (?, ?, ?, ?, 'Open', '[]', ?)
                    ON CONFLICT(tenant, lead_id) DO UPDATE SET
                      name=COALESCE(excluded.name, leads.name),
                      phone=COALESCE(excluded.phone, leads.phone),
                      updated_utc=excluded.updated_utc;
                    """,
                    (tenant, lead_id, name, phone, now),
                )
        except Exception:
            return

    def set_lead_session(
        self,
        *,
        tenant: str,
        lead_id: str,
        session_id: str,
    ) -> None:
        """
        ✅ FIX: must accept tenant (MessageHandler calls with tenant=...).
        """
        tenant = (tenant or "default").strip() or "default"
        lead_id = (lead_id or "unknown").strip() or "unknown"
        session_id = (session_id or "unknown").strip() or "unknown"
        now = _utc_now_iso()

        try:
            with self._conn() as con:
                # ensure lead exists
                con.execute(
                    """
                    INSERT INTO leads (tenant, lead_id, updated_utc)
                    VALUES (?, ?, ?)
                    ON CONFLICT(tenant, lead_id) DO UPDATE SET
                      updated_utc=excluded.updated_utc;
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
        except Exception:
            return

    # -----------------------
    # Event / message logging
    # -----------------------
    def log_message(
        self,
        *,
        tenant: str,
        channel: str,  # web|whatsapp
        direction: str,  # inbound|outbound
        session_id: str,
        text: str = "",
        intent: str = "unknown",
        lead_id: Optional[str] = None,
        store: Optional[str] = None,
        products: Optional[List[str]] = None,
        is_fallback: bool = False,
        is_error: bool = False,  # legacy flag (we still store it)
        error_code: str = "",
        error_type: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Stores:
          msg_in / msg_out rows in events
        Fallback is ONLY a flag on msg_out meta_json.
        """
        tenant = (tenant or "default").strip() or "default"
        ch = (channel or "web").strip().lower() or "web"
        if ch not in ("web", "whatsapp"):
            ch = "web"

        sid = (session_id or "unknown").strip() or "unknown"
        direction = (direction or "inbound").strip().lower()
        event_type = "msg_in" if direction == "inbound" else "msg_out"

        meta: Dict[str, Any] = {
            "store": store,
            "products": products or [],
            "fallback": bool(is_fallback),
            "error": bool(is_error),  # kept for backwards compat; not used as KPI error
        }
        if extra and isinstance(extra, dict):
            meta["extra"] = extra

        try:
            with self._conn() as con:
                con.execute(
                    """
                    INSERT INTO events(ts_utc, tenant, channel, session_id, event_type, intent, text, lead_id, error_code, error_type, meta_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        _utc_now_iso(),
                        tenant,
                        ch,
                        sid,
                        event_type,
                        (intent or "unknown").strip(),
                        text or "",
                        (lead_id or "").strip(),
                        error_code or "",
                        error_type or "",
                        json.dumps(meta, ensure_ascii=False),
                    ),
                )
        except Exception:
            return

    def log_error(
        self,
        *,
        tenant: str,
        channel: str,
        session_id: str,
        lead_id: Optional[str] = None,
        error_code: str = "",
        error_type: str = "",
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Errors are their own rows:
          event_type='error'
        So they DON'T inflate outbound counts.
        """
        tenant = (tenant or "default").strip() or "default"
        ch = (channel or "web").strip().lower() or "web"
        if ch not in ("web", "whatsapp"):
            ch = "web"
        sid = (session_id or "unknown").strip() or "unknown"

        m = dict(meta or {})
        m["error"] = True

        try:
            with self._conn() as con:
                con.execute(
                    """
                    INSERT INTO events(ts_utc, tenant, channel, session_id, event_type, intent, lead_id, error_code, error_type, meta_json)
                    VALUES (?, ?, ?, ?, 'error', 'system_error', ?, ?, ?, ?);
                    """,
                    (
                        _utc_now_iso(),
                        tenant,
                        ch,
                        sid,
                        (lead_id or "").strip(),
                        error_code or "",
                        error_type or "",
                        json.dumps(m, ensure_ascii=False),
                    ),
                )
        except Exception:
            return

    # Back-compat
    def log_event(self, *args: Any, **kwargs: Any) -> None:
        # older code may call log_event; just route it
        # (but keep it minimal)
        try:
            # best effort: if it looks like message payload, store as meta_json
            tenant = kwargs.get("tenant") or (args[0] if args else "default")
            channel = kwargs.get("channel") or (args[1] if len(args) > 1 else "web")
            session_id = kwargs.get("session_id") or (args[2] if len(args) > 2 else "unknown")
            event_type = kwargs.get("event_type") or (args[3] if len(args) > 3 else "event")
            lead_id = kwargs.get("lead_id") or (args[4] if len(args) > 4 else None)
            meta_json = kwargs.get("meta_json") or (args[5] if len(args) > 5 else None)

            with self._conn() as con:
                con.execute(
                    """
                    INSERT INTO events(ts_utc, tenant, channel, session_id, event_type, lead_id, meta_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    (_utc_now_iso(), str(tenant), str(channel), str(session_id), str(event_type), str(lead_id or ""), str(meta_json or "")),
                )
        except Exception:
            return

    # -----------------------
    # Reads (dashboard)
    # -----------------------
    def get_kpis(self, *, tenant: str, minutes: int = 1440) -> Dict[str, Any]:
        tenant = (tenant or "default").strip() or "default"
        since = _since_iso(minutes)

        try:
            with self._conn() as con:
                row = con.execute(
                    """
                    SELECT
                      SUM(CASE WHEN event_type='msg_in'  THEN 1 ELSE 0 END) AS inbound,
                      SUM(CASE WHEN event_type='msg_out' THEN 1 ELSE 0 END) AS outbound,
                      COUNT(DISTINCT CASE WHEN event_type IN ('msg_in','msg_out') THEN session_id END) AS sessions,
                      SUM(CASE WHEN event_type='msg_out' AND json_extract(meta_json,'$.fallback') = 1 THEN 1 ELSE 0 END) AS fallbacks,
                      SUM(CASE WHEN event_type='error' THEN 1 ELSE 0 END) AS errors
                    FROM events
                    WHERE tenant=? AND ts_utc>=?;
                    """,
                    (tenant, since),
                ).fetchone()

                leads_row = con.execute(
                    "SELECT COUNT(*) AS n FROM leads WHERE tenant=? AND updated_utc>=?;",
                    (tenant, since),
                ).fetchone()

            inbound = int(row["inbound"] or 0)
            outbound = int(row["outbound"] or 0)
            fallbacks = int(row["fallbacks"] or 0)
            errors = int(row["errors"] or 0)

            # ✅ what you asked:
            # "make the errors minus from the outbound aswell as the errors"
            # Interpreting as: net_outbound excludes fallback replies and error replies.
            outbound_net = max(0, outbound - fallbacks - errors)

            return {
                "tenant": tenant,
                "window_minutes": int(minutes),
                "inbound": inbound,
                "outbound": outbound,
                "outbound_net": outbound_net,
                "total": inbound + outbound,
                "sessions": int(row["sessions"] or 0),
                "leads": int((leads_row["n"] if leads_row else 0) or 0),
                "fallbacks": fallbacks,
                "errors": errors,
            }
        except Exception:
            return {
                "tenant": tenant,
                "window_minutes": int(minutes),
                "inbound": 0,
                "outbound": 0,
                "outbound_net": 0,
                "total": 0,
                "sessions": 0,
                "leads": 0,
                "fallbacks": 0,
                "errors": 0,
            }

    def get_timeseries(self, *, tenant: str, minutes: int = 1440, bucket_minutes: int = 60) -> List[Dict[str, Any]]:
        """
        Hourly series: inbound/outbound.
        """
        tenant = (tenant or "default").strip() or "default"
        since = _since_iso(minutes)

        # bucket_minutes kept for API compatibility; we bucket by hour for now.
        try:
            with self._conn() as con:
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
                    (tenant, since),
                ).fetchall()

            return [{"t": r["t"], "inbound": int(r["inbound"] or 0), "outbound": int(r["outbound"] or 0)} for r in rows]
        except Exception:
            return []

    def get_sessions_timeseries(self, *, tenant: str, minutes: int = 1440, bucket_minutes: int = 60) -> List[Dict[str, Any]]:
        tenant = (tenant or "default").strip() or "default"
        since = _since_iso(minutes)

        try:
            with self._conn() as con:
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
        except Exception:
            return []

    def get_channels_split(self, *, tenant: str, minutes: int = 1440) -> Dict[str, Any]:
        tenant = (tenant or "default").strip() or "default"
        since = _since_iso(minutes)

        try:
            with self._conn() as con:
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
                    (tenant, since),
                ).fetchall()

            out: Dict[str, Any] = {}
            for r in rows:
                ch = (r["channel"] or "unknown").strip().lower() or "unknown"
                inbound = int(r["inbound"] or 0)
                outbound = int(r["outbound"] or 0)
                out[ch] = {"inbound": inbound, "outbound": outbound, "total": inbound + outbound}
            return out
        except Exception:
            return {}

    def get_top_intents(self, *, tenant: str, minutes: int = 1440, top: int = 10) -> List[Dict[str, Any]]:
        tenant = (tenant or "default").strip() or "default"
        since = _since_iso(minutes)
        top = max(1, min(_clamp_int(top, 10, 1, 50), 50))

        try:
            with self._conn() as con:
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
                    (tenant, since, top),
                ).fetchall()
            return [{"label": r["intent"], "count": int(r["n"] or 0)} for r in rows]
        except Exception:
            return []

    def get_fallbacks(self, *, tenant: str, minutes: int = 1440, top: int = 10) -> List[Dict[str, Any]]:
        tenant = (tenant or "default").strip() or "default"
        since = _since_iso(minutes)
        top = max(1, min(_clamp_int(top, 10, 1, 50), 50))

        try:
            with self._conn() as con:
                rows = con.execute(
                    """
                    SELECT COALESCE(NULLIF(intent,''),'fallback') AS intent,
                           COUNT(*) AS n
                    FROM events
                    WHERE tenant=? AND ts_utc>=?
                      AND event_type='msg_out'
                      AND json_extract(meta_json,'$.fallback') = 1
                    GROUP BY intent
                    ORDER BY n DESC
                    LIMIT ?;
                    """,
                    (tenant, since, top),
                ).fetchall()
            return [{"label": r["intent"], "count": int(r["n"] or 0)} for r in rows]
        except Exception:
            return []

    def get_errors(self, *, tenant: str, minutes: int = 1440, top: int = 10) -> List[Dict[str, Any]]:
        tenant = (tenant or "default").strip() or "default"
        since = _since_iso(minutes)
        top = max(1, min(_clamp_int(top, 10, 1, 50), 50))

        try:
            with self._conn() as con:
                rows = con.execute(
                    """
                    SELECT COALESCE(NULLIF(error_code,''),'error') AS code,
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
        except Exception:
            return []

    def get_common_questions(self, *, tenant: str, minutes: int = 1440, top: int = 10) -> List[Dict[str, Any]]:
        tenant = (tenant or "default").strip() or "default"
        since = _since_iso(minutes)
        top = max(1, min(_clamp_int(top, 10, 1, 50), 50))

        try:
            with self._conn() as con:
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
        except Exception:
            return []

    def get_leads(self, *, tenant: str, limit: int = 50) -> List[Dict[str, Any]]:
        tenant = (tenant or "default").strip() or "default"
        limit = max(1, min(_clamp_int(limit, 50, 1, 500), 500))

        try:
            with self._conn() as con:
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

            out: List[Dict[str, Any]] = []
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
        except Exception:
            return []

    # -----------------------
    # Daily overview series (for your new overview chart)
    # -----------------------
    def get_overview_daily(self, *, tenant: str, days: int = 14) -> List[Dict[str, Any]]:
        """
        Returns per-day totals:
          inbound, outbound, fallbacks, errors, outbound_net
        """
        tenant = (tenant or "default").strip() or "default"
        days = _clamp_int(days, 14, 1, 180)
        since = _utc_iso(datetime.now(timezone.utc) - timedelta(days=days))

        try:
            with self._conn() as con:
                rows = con.execute(
                    """
                    SELECT
                      substr(ts_utc,1,10) AS d,
                      SUM(CASE WHEN event_type='msg_in'  THEN 1 ELSE 0 END) AS inbound,
                      SUM(CASE WHEN event_type='msg_out' THEN 1 ELSE 0 END) AS outbound,
                      SUM(CASE WHEN event_type='msg_out' AND json_extract(meta_json,'$.fallback') = 1 THEN 1 ELSE 0 END) AS fallbacks,
                      SUM(CASE WHEN event_type='error' THEN 1 ELSE 0 END) AS errors
                    FROM events
                    WHERE tenant=? AND ts_utc>=?
                    GROUP BY d
                    ORDER BY d;
                    """,
                    (tenant, since),
                ).fetchall()

            out: List[Dict[str, Any]] = []
            for r in rows:
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
        except Exception:
            return []

    # -----------------------
    # CSV export helper
    # -----------------------
    def leads_csv(self, *, tenant: str) -> str:
        tenant = (tenant or "default").strip() or "default"
        try:
            rows = self.get_leads(tenant=tenant, limit=500)
            out = io.StringIO()
            w = csv.writer(out)
            w.writerow(["updated_utc", "name", "phone", "status", "tags", "last_session_id", "lead_id"])
            for r in rows:
                w.writerow(
                    [
                        r.get("updated_utc", ""),
                        r.get("name", ""),
                        r.get("phone", ""),
                        r.get("status", ""),
                        json.dumps(r.get("tags", []), ensure_ascii=False),
                        r.get("last_session_id", ""),
                        r.get("lead_id", ""),
                    ]
                )
            return out.getvalue()
        except Exception:
            return ""
