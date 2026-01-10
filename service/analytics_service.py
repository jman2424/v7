# service/analytics_service.py
from __future__ import annotations

import os
import csv
import io
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


# Container passes Settings into this service.
SettingsLike = Any


def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _utc_now_iso() -> str:
    return _utc_iso(datetime.now(timezone.utc))


@dataclass
class AnalyticsService:
    settings: SettingsLike

    def __post_init__(self) -> None:
        # Prefer env override; otherwise store inside /app/logs for Render disk
        self.db_path = os.getenv("ANALYTICS_DB_PATH", "/app/logs/analytics.db")
        self.ensure_ready()

    def _conn(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
        return con

    # -----------------------
    # Boot / schema
    # -----------------------
    def ensure_ready(self) -> None:
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with self._conn() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  ts_utc TEXT NOT NULL,
                  tenant TEXT NOT NULL,
                  channel TEXT NOT NULL,
                  session_id TEXT NOT NULL,
                  lead_id TEXT,
                  event_type TEXT NOT NULL,
                  meta_json TEXT
                );
                """
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_tenant_ts ON events(tenant, ts_utc);"
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);"
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_lead ON events(lead_id);"
            )

            con.execute(
                """
                CREATE TABLE IF NOT EXISTS leads (
                  lead_id TEXT PRIMARY KEY,
                  tenant TEXT NOT NULL,
                  name TEXT,
                  phone TEXT,
                  status TEXT DEFAULT 'Open',
                  tags TEXT DEFAULT '',
                  last_session_id TEXT,
                  updated_utc TEXT NOT NULL
                );
                """
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_leads_tenant_updated ON leads(tenant, updated_utc);"
            )

    # -----------------------
    # Write APIs (called by chat routes)
    # -----------------------
    def upsert_lead(
        self,
        tenant: str,
        lead_id: str,
        phone: Optional[str] = None,
        name: Optional[str] = None,
    ) -> None:
        now = _utc_now_iso()
        with self._conn() as con:
            con.execute(
                """
                INSERT INTO leads (lead_id, tenant, phone, name, updated_utc)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(lead_id) DO UPDATE SET
                  tenant=excluded.tenant,
                  phone=COALESCE(excluded.phone, leads.phone),
                  name=COALESCE(excluded.name, leads.name),
                  updated_utc=excluded.updated_utc;
                """,
                (lead_id, tenant, phone, name, now),
            )

    def set_lead_session(self, lead_id: str, session_id: str) -> None:
        now = _utc_now_iso()
        with self._conn() as con:
            con.execute(
                """
                UPDATE leads
                SET last_session_id=?, updated_utc=?
                WHERE lead_id=?;
                """,
                (session_id, now, lead_id),
            )

    # -----------------------
    # IMPORTANT: Backwards-compatible logger
    # -----------------------
    def log_event(self, *args, **kwargs) -> None:
        """
        Backwards-compatible analytics logger.
        This must NEVER crash the bot.

        Supported call styles:
          NEW:
            log_event(tenant, channel, session_id, event_type, lead_id=None, meta_json=None)

          KW:
            log_event(tenant=..., channel=..., session_id=..., event_type=..., lead_id=..., meta_json=...)

          OLD/common:
            log_event(ctx, event_type, meta_json=...)      # ctx has tenant/channel/session_id (dict or attrs)
            log_event(tenant, session_id, event_type)      # channel inferred
        """
        tenant = kwargs.pop("tenant", None)
        channel = kwargs.pop("channel", None)
        session_id = kwargs.pop("session_id", None)
        event_type = kwargs.pop("event_type", None)
        lead_id = kwargs.pop("lead_id", None)
        meta_json = kwargs.pop("meta_json", None)

        # allow meta=... too
        if meta_json is None and "meta" in kwargs:
            meta_json = kwargs.pop("meta")

        # 1) (tenant, channel, session_id, event_type, ...)
        if len(args) >= 4 and all(isinstance(x, str) for x in args[:4]):
            tenant = tenant or args[0]
            channel = channel or args[1]
            session_id = session_id or args[2]
            event_type = event_type or args[3]
            if len(args) >= 5:
                lead_id = lead_id or args[4]
            if len(args) >= 6 and meta_json is None:
                meta_json = args[5]

        # 2) (tenant, session_id, event_type)
        elif len(args) == 3 and all(isinstance(x, str) for x in args):
            tenant = tenant or args[0]
            session_id = session_id or args[1]
            event_type = event_type or args[2]
            channel = channel or "unknown"

        # 3) (ctx, event_type, meta_json?)
        elif len(args) >= 2:
            ctx = args[0]
            event_type = event_type or args[1]

            def _get(obj, key, default=None):
                if isinstance(obj, dict):
                    return obj.get(key, default)
                return getattr(obj, key, default)

            tenant = tenant or _get(ctx, "tenant")
            channel = channel or _get(ctx, "channel", "unknown")
            session_id = session_id or _get(ctx, "session_id")
            lead_id = lead_id or _get(ctx, "lead_id")

            if meta_json is None and len(args) >= 3:
                meta_json = args[2]

        # FINAL: never break the bot for analytics
        if not tenant or not session_id or not event_type:
            # skip silently (or log warning if you want)
            return

        channel = channel or "unknown"

        try:
            with self._conn() as con:
                con.execute(
                    """
                    INSERT INTO events(ts_utc, tenant, channel, session_id, lead_id, event_type, meta_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    (_utc_now_iso(), tenant, channel, session_id, lead_id, event_type, meta_json),
                )
        except Exception:
            # again: analytics must not crash production chat
            return

    # -----------------------
    # Read APIs (dashboard)
    # -----------------------
    def get_kpis(self, tenant: str, minutes: int = 1440) -> Dict[str, Any]:
        since = _utc_iso(datetime.now(timezone.utc) - timedelta(minutes=int(minutes)))
        with self._conn() as con:
            row = con.execute(
                """
                SELECT
                  SUM(CASE WHEN event_type='msg_in'  THEN 1 ELSE 0 END) AS inbound,
                  SUM(CASE WHEN event_type='msg_out' THEN 1 ELSE 0 END) AS outbound,
                  COUNT(DISTINCT session_id) AS sessions,
                  COUNT(DISTINCT lead_id) AS leads
                FROM events
                WHERE tenant=? AND ts_utc >= ?;
                """,
                (tenant, since),
            ).fetchone()

        return {
            "tenant": tenant,
            "minutes": int(minutes),
            "inbound": int(row["inbound"] or 0),
            "outbound": int(row["outbound"] or 0),
            "sessions": int(row["sessions"] or 0),
            "leads": int(row["leads"] or 0),
        }

    def get_timeseries(self, tenant: str, minutes: int = 1440) -> Dict[str, Any]:
        since = _utc_iso(datetime.now(timezone.utc) - timedelta(minutes=int(minutes)))

        # group by hour: YYYY-MM-DDTHH
        with self._conn() as con:
            rows = con.execute(
                """
                SELECT
                  substr(ts_utc, 1, 13) AS t,
                  SUM(CASE WHEN event_type='msg_in'  THEN 1 ELSE 0 END) AS inbound,
                  SUM(CASE WHEN event_type='msg_out' THEN 1 ELSE 0 END) AS outbound
                FROM events
                WHERE tenant=? AND ts_utc >= ?
                GROUP BY t
                ORDER BY t ASC;
                """,
                (tenant, since),
            ).fetchall()

        return {
            "tenant": tenant,
            "minutes": int(minutes),
            "bucket_minutes": 60,
            "points": [
                {
                    "t": r["t"],
                    "inbound": int(r["inbound"] or 0),
                    "outbound": int(r["outbound"] or 0),
                }
                for r in rows
            ],
        }

    def list_leads(self, tenant: str, limit: int = 50) -> List[Dict[str, Any]]:
        limit = min(max(int(limit), 1), 200)
        with self._conn() as con:
            rows = con.execute(
                """
                SELECT lead_id, name, phone, status, tags, last_session_id, updated_utc
                FROM leads
                WHERE tenant=?
                ORDER BY updated_utc DESC
                LIMIT ?;
                """,
                (tenant, limit),
            ).fetchall()

        # normalize tags to list if you want (optional)
        out: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            # keep tags as string for now (your dashboard can render either)
            out.append(d)
        return out

    def leads_csv(self, tenant: str) -> str:
        with self._conn() as con:
            rows = con.execute(
                """
                SELECT updated_utc, name, phone, status, tags, last_session_id, lead_id
                FROM leads
                WHERE tenant=?
                ORDER BY updated_utc DESC;
                """,
                (tenant,),
            ).fetchall()

        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["updated_utc", "name", "phone", "status", "tags", "session_id", "lead_id"])
        for r in rows:
            w.writerow(
                [
                    r["updated_utc"],
                    r["name"],
                    r["phone"],
                    r["status"],
                    r["tags"],
                    r["last_session_id"],
                    r["lead_id"],
                ]
            )
        return out.getvalue()
