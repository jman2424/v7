# service/analytics_service.py
from __future__ import annotations

import os
import csv
import io
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Union


SettingsLike = Any


def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _utc_now_iso() -> str:
    return _utc_iso(datetime.now(timezone.utc))


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
            con.execute("""
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
            """)
            con.execute("CREATE INDEX IF NOT EXISTS idx_events_tenant_ts ON events(tenant, ts_utc);")
            con.execute("CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);")
            con.execute("CREATE INDEX IF NOT EXISTS idx_events_lead ON events(lead_id);")
            con.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);")
            con.execute("CREATE INDEX IF NOT EXISTS idx_events_channel ON events(channel);")

            con.execute("""
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
            """)
            con.execute("CREATE INDEX IF NOT EXISTS idx_leads_tenant_updated ON leads(tenant, updated_utc);")

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
        try:
            with self._conn() as con:
                con.execute("""
                INSERT INTO leads (lead_id, tenant, phone, name, updated_utc)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(lead_id) DO UPDATE SET
                  tenant=excluded.tenant,
                  phone=COALESCE(excluded.phone, leads.phone),
                  name=COALESCE(excluded.name, leads.name),
                  updated_utc=excluded.updated_utc;
                """, (lead_id, tenant, phone, name, now))
        except Exception:
            return

    def set_lead_session(self, lead_id: str, session_id: str) -> None:
        now = _utc_now_iso()
        try:
            with self._conn() as con:
                con.execute("""
                UPDATE leads
                SET last_session_id=?, updated_utc=?
                WHERE lead_id=?;
                """, (session_id, now, lead_id))
        except Exception:
            return

    def log_event(
        self,
        tenant: str,
        channel: Union[str, Dict[str, Any]],
        session_id: Optional[str] = None,
        event_type: Optional[str] = None,
        lead_id: Optional[str] = None,
        meta_json: Optional[str] = None,
    ) -> None:
        """
        Supports:
          log_event(tenant, channel, session_id, event_type, lead_id=None, meta_json=None)

        Backward compatible with older bugged call:
          log_event(tenant, {dict_payload})
        """
        try:
            if isinstance(channel, dict) and session_id is None and event_type is None:
                payload = channel
                ch = str(payload.get("channel") or payload.get("source") or "web")
                sid = str(payload.get("session_id") or payload.get("session") or "unknown")
                et = str(payload.get("event_type") or payload.get("type") or "event")
                meta_json = json.dumps(payload, ensure_ascii=False)
                channel = ch
                session_id = sid
                event_type = et

            if not isinstance(channel, str):
                channel = "web"

            channel = (channel or "web").strip().lower()
            if channel not in ("web", "whatsapp"):
                channel = channel or "web"

            session_id = str(session_id or "unknown")
            event_type = str(event_type or "event")

            with self._conn() as con:
                con.execute("""
                INSERT INTO events(ts_utc, tenant, channel, session_id, lead_id, event_type, meta_json)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """, (_utc_now_iso(), tenant, channel, session_id, lead_id, event_type, meta_json))
        except Exception:
            return

    def log_message(
        self,
        tenant: str,
        channel: str,                 # "web" | "whatsapp"
        direction: str,               # "inbound" | "outbound"
        session_id: str,
        text: str = "",
        intent: str = "unknown",
        lead_id: Optional[str] = None,
        store: Optional[str] = None,
        products: Optional[List[str]] = None,
        is_fallback: bool = False,
        is_error: bool = False,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Structured event logger that makes charts reliable.
        Stores details in meta_json with consistent keys.
        """
        try:
            ch = (channel or "web").strip().lower()
            direction = (direction or "").strip().lower()

            if direction not in ("inbound", "outbound"):
                direction = "inbound"

            et = "msg_in" if direction == "inbound" else "msg_out"

            payload: Dict[str, Any] = {
                "direction": direction,
                "text": text or "",
                "intent": (intent or "unknown").strip().lower() or "unknown",
                "store": store,
                "products": products or [],
                "fallback": bool(is_fallback),
                "error": bool(is_error),
            }
            if extra and isinstance(extra, dict):
                payload["extra"] = extra

            self.log_event(
                tenant=tenant,
                channel=ch,
                session_id=session_id,
                event_type=et,
                lead_id=lead_id,
                meta_json=json.dumps(payload, ensure_ascii=False),
            )
        except Exception:
            return

    # -----------------------
    # Read APIs (used by routes/dashboard)
    # -----------------------
    def get_kpis(self, tenant: str, minutes: int = 1440) -> Dict[str, Any]:
        since = _utc_iso(datetime.now(timezone.utc) - timedelta(minutes=minutes))
        try:
            with self._conn() as con:
                row = con.execute("""
                  SELECT
                    SUM(CASE WHEN event_type='msg_in'  THEN 1 ELSE 0 END) AS inbound,
                    SUM(CASE WHEN event_type='msg_out' THEN 1 ELSE 0 END) AS outbound,
                    COUNT(DISTINCT session_id) AS sessions,
                    COUNT(DISTINCT lead_id) AS leads,
                    SUM(CASE WHEN json_extract(meta_json,'$.error')    = 1 THEN 1 ELSE 0 END) AS errors,
                    SUM(CASE WHEN json_extract(meta_json,'$.fallback') = 1 THEN 1 ELSE 0 END) AS fallbacks
                  FROM events
                  WHERE tenant=? AND ts_utc >= ?;
                """, (tenant, since)).fetchone()

            inbound = int(row["inbound"] or 0)
            outbound = int(row["outbound"] or 0)

            return {
                "tenant": tenant,
                "minutes": int(minutes),
                "inbound": inbound,
                "outbound": outbound,
                "sessions": int(row["sessions"] or 0),
                "leads": int(row["leads"] or 0),
                "errors": int(row["errors"] or 0),
                "fallbacks": int(row["fallbacks"] or 0),
                # ✅ dedicated pie payload for direction
                "direction_share": [
                    {"name": "Inbound", "value": inbound},
                    {"name": "Outbound", "value": outbound},
                ],
            }
        except Exception:
            return {
                "tenant": tenant,
                "minutes": int(minutes),
                "inbound": 0,
                "outbound": 0,
                "sessions": 0,
                "leads": 0,
                "errors": 0,
                "fallbacks": 0,
                "direction_share": [
                    {"name": "Inbound", "value": 0},
                    {"name": "Outbound", "value": 0},
                ],
            }

    def get_timeseries(self, tenant: str, minutes: int = 1440) -> Dict[str, Any]:
        """
        Inbound/outbound per hour (chart-friendly array).
        """
        since = _utc_iso(datetime.now(timezone.utc) - timedelta(minutes=minutes))
        try:
            with self._conn() as con:
                rows = con.execute("""
                  SELECT
                    substr(ts_utc, 1, 13) AS hour_bucket, -- YYYY-MM-DDTHH
                    SUM(CASE WHEN event_type='msg_in'  THEN 1 ELSE 0 END) AS inbound,
                    SUM(CASE WHEN event_type='msg_out' THEN 1 ELSE 0 END) AS outbound
                  FROM events
                  WHERE tenant=? AND ts_utc >= ?
                  GROUP BY hour_bucket
                  ORDER BY hour_bucket ASC;
                """, (tenant, since)).fetchall()

            points = [
                {
                    "bucket": r["hour_bucket"],     # ✅ consistent key name
                    "inbound": int(r["inbound"] or 0),
                    "outbound": int(r["outbound"] or 0),
                }
                for r in rows
            ]

            return {
                "tenant": tenant,
                "minutes": int(minutes),
                "bucket_minutes": 60,
                "points": points,
            }
        except Exception:
            return {"tenant": tenant, "minutes": int(minutes), "bucket_minutes": 60, "points": []}

    def get_volume_by_channel(self, tenant: str, minutes: int = 1440) -> Dict[str, Any]:
        """
        Inbound/outbound split by channel, plus errors/fallbacks.
        """
        since = _utc_iso(datetime.now(timezone.utc) - timedelta(minutes=minutes))
        try:
            with self._conn() as con:
                rows = con.execute("""
                  SELECT
                    substr(ts_utc, 1, 13) AS hour_bucket,
                    SUM(CASE WHEN event_type='msg_in'  AND channel='web'      THEN 1 ELSE 0 END) AS in_web,
                    SUM(CASE WHEN event_type='msg_in'  AND channel='whatsapp' THEN 1 ELSE 0 END) AS in_whatsapp,
                    SUM(CASE WHEN event_type='msg_out' AND channel='web'      THEN 1 ELSE 0 END) AS out_web,
                    SUM(CASE WHEN event_type='msg_out' AND channel='whatsapp' THEN 1 ELSE 0 END) AS out_whatsapp,
                    SUM(CASE WHEN json_extract(meta_json,'$.fallback') = 1 THEN 1 ELSE 0 END) AS fallbacks,
                    SUM(CASE WHEN json_extract(meta_json,'$.error')    = 1 THEN 1 ELSE 0 END) AS errors
                  FROM events
                  WHERE tenant=? AND ts_utc >= ?
                  GROUP BY hour_bucket
                  ORDER BY hour_bucket ASC;
                """, (tenant, since)).fetchall()

            return {
                "tenant": tenant,
                "minutes": int(minutes),
                "bucket_minutes": 60,
                "points": [dict(r) for r in rows],
            }
        except Exception:
            return {"tenant": tenant, "minutes": int(minutes), "bucket_minutes": 60, "points": []}

    # -----------------------
    # FIXED: SQLite alias-in-WHERE bugs
    # -----------------------
    def get_common_questions(self, tenant: str, minutes: int = 10080, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Most common inbound user messages (normalized).
        """
        since = _utc_iso(datetime.now(timezone.utc) - timedelta(minutes=minutes))
        limit = min(max(int(limit), 1), 100)

        expr = "LOWER(TRIM(json_extract(meta_json,'$.text')))"
        try:
            with self._conn() as con:
                rows = con.execute(f"""
                  SELECT
                    {expr} AS q,
                    COUNT(*) AS count
                  FROM events
                  WHERE tenant=? AND ts_utc >= ?
                    AND event_type='msg_in'
                    AND {expr} IS NOT NULL
                    AND {expr} != ''
                  GROUP BY q
                  ORDER BY count DESC
                  LIMIT ?;
                """, (tenant, since, limit)).fetchall()

            return [{"q": r["q"], "count": int(r["count"])} for r in rows]
        except Exception:
            return []

    def get_top_products(self, tenant: str, minutes: int = 43200, limit: int = 15) -> List[Dict[str, Any]]:
        """
        Top products (from meta_json.products array).
        """
        since = _utc_iso(datetime.now(timezone.utc) - timedelta(minutes=minutes))
        limit = min(max(int(limit), 1), 50)

        try:
            with self._conn() as con:
                rows = con.execute("""
                  SELECT
                    value AS product_name,
                    COUNT(*) AS count
                  FROM events, json_each(json_extract(meta_json,'$.products'))
                  WHERE tenant=? AND ts_utc >= ?
                    AND event_type='msg_in'
                    AND value IS NOT NULL
                    AND value != ''
                  GROUP BY product_name
                  ORDER BY count DESC
                  LIMIT ?;
                """, (tenant, since, limit)).fetchall()

            return [{"name": r["product_name"], "count": int(r["count"])} for r in rows]
        except Exception:
            return []

    def get_store_activity(self, tenant: str, minutes: int = 43200) -> List[Dict[str, Any]]:
        """
        Pie chart: activity by store (meta_json.store).
        """
        since = _utc_iso(datetime.now(timezone.utc) - timedelta(minutes=minutes))
        try:
            with self._conn() as con:
                rows = con.execute("""
                  SELECT
                    COALESCE(json_extract(meta_json,'$.store'),'unknown') AS store,
                    COUNT(*) AS count
                  FROM events
                  WHERE tenant=? AND ts_utc >= ?
                    AND event_type='msg_in'
                  GROUP BY store
                  ORDER BY count DESC;
                """, (tenant, since)).fetchall()

            return [{"store": r["store"], "count": int(r["count"])} for r in rows]
        except Exception:
            return []

    def get_top_intents(self, tenant: str, minutes: int = 43200, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Top intents from meta_json.intent.
        """
        since = _utc_iso(datetime.now(timezone.utc) - timedelta(minutes=minutes))
        limit = min(max(int(limit), 1), 50)

        try:
            with self._conn() as con:
                rows = con.execute("""
                  SELECT
                    COALESCE(json_extract(meta_json,'$.intent'),'unknown') AS intent,
                    COUNT(*) AS count
                  FROM events
                  WHERE tenant=? AND ts_utc >= ?
                    AND event_type='msg_in'
                  GROUP BY intent
                  ORDER BY count DESC
                  LIMIT ?;
                """, (tenant, since, limit)).fetchall()

            return [{"intent": r["intent"], "count": int(r["count"])} for r in rows]
        except Exception:
            return []

    def list_leads(self, tenant: str, limit: int = 50) -> List[Dict[str, Any]]:
        limit = min(max(int(limit), 1), 200)
        try:
            with self._conn() as con:
                rows = con.execute("""
                  SELECT lead_id, name, phone, status, tags, last_session_id, updated_utc
                  FROM leads
                  WHERE tenant=?
                  ORDER BY updated_utc DESC
                  LIMIT ?;
                """, (tenant, limit)).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def leads_csv(self, tenant: str) -> str:
        try:
            with self._conn() as con:
                rows = con.execute("""
                  SELECT updated_utc, name, phone, status, tags, last_session_id, lead_id
                  FROM leads
                  WHERE tenant=?
                  ORDER BY updated_utc DESC;
                """, (tenant,)).fetchall()

            out = io.StringIO()
            w = csv.writer(out)
            w.writerow(["updated_utc", "name", "phone", "status", "tags", "session_id", "lead_id"])
            for r in rows:
                w.writerow([
                    r["updated_utc"], r["name"], r["phone"], r["status"],
                    r["tags"], r["last_session_id"], r["lead_id"]
                ])
            return out.getvalue()
        except Exception:
            return ""

    # -----------------------
    # ✅ These are the missing methods your routes/dashboard expect
    # -----------------------
    def summary(self, tenant: str, minutes: int = 1440) -> Dict[str, Any]:
        """
        Single payload used by dashboards for KPIs + pies + tables.
        """
        minutes = _clamp_int(minutes, 1440, 1, 60 * 24 * 365)

        kpis = self.get_kpis(tenant, minutes=minutes)

        # Optional extras (safe defaults)
        channel_share = self._channel_share(tenant, minutes=minutes)
        store_activity = self.get_store_activity(tenant, minutes=minutes)
        top_intents = self.get_top_intents(tenant, minutes=minutes, limit=10)
        common_questions = self.get_common_questions(tenant, minutes=minutes, limit=20)

        return {
            **kpis,
            # ✅ keep channel pie separate from direction pie
            "channel_share": channel_share,
            "store_activity": store_activity,
            "top_intents": top_intents,
            "common_questions": common_questions,
        }

    def rollups(self, tenant: str, by: str = "day", minutes: int = 1440) -> Dict[str, Any]:
        """
        Rollups for charts.
        - For your bottom-left "Message Volume" chart you want hourly buckets.
        """
        minutes = _clamp_int(minutes, 1440, 1, 60 * 24 * 365)
        by = (by or "day").strip().lower()

        # Most dashboards use hourly buckets for "last 24h/7d"
        # You can add day/week/month later; for now keep it stable.
        ts = self.get_timeseries(tenant, minutes=minutes)
        return {
            "tenant": tenant,
            "minutes": minutes,
            "by": by,
            "message_volume": ts["points"],  # ✅ chart-ready array
        }

    def fetch_raw(self, tenant: str, minutes: int = 1440, limit: int = 5000) -> List[Dict[str, Any]]:
        """
        Raw rows for CSV export and debugging.
        """
        minutes = _clamp_int(minutes, 1440, 1, 60 * 24 * 365)
        limit = _clamp_int(limit, 5000, 1, 50_000)
        since = _utc_iso(datetime.now(timezone.utc) - timedelta(minutes=minutes))

        try:
            with self._conn() as con:
                rows = con.execute("""
                  SELECT ts_utc, tenant, channel, session_id, lead_id, event_type, meta_json
                  FROM events
                  WHERE tenant=? AND ts_utc >= ?
                  ORDER BY ts_utc DESC
                  LIMIT ?;
                """, (tenant, since, limit)).fetchall()

            out: List[Dict[str, Any]] = []
            for r in rows:
                item = dict(r)
                # Try decode meta_json into useful flat fields (safe)
                mj = item.get("meta_json")
                if mj:
                    try:
                        meta = json.loads(mj)
                        if isinstance(meta, dict):
                            # expose common keys for CSV readability
                            item["direction"] = meta.get("direction")
                            item["text"] = meta.get("text")
                            item["intent"] = meta.get("intent")
                            item["store"] = meta.get("store")
                    except Exception:
                        pass
                out.append(item)
            return out
        except Exception:
            return []

    def _channel_share(self, tenant: str, minutes: int = 1440) -> List[Dict[str, Any]]:
        """
        Pie: total messages by channel (web vs whatsapp).
        """
        since = _utc_iso(datetime.now(timezone.utc) - timedelta(minutes=minutes))
        try:
            with self._conn() as con:
                rows = con.execute("""
                  SELECT channel, COUNT(*) AS count
                  FROM events
                  WHERE tenant=? AND ts_utc >= ?
                    AND event_type IN ('msg_in','msg_out')
                  GROUP BY channel
                  ORDER BY count DESC;
                """, (tenant, since)).fetchall()
            return [{"name": r["channel"], "value": int(r["count"])} for r in rows]
        except Exception:
            return []

         def channel_breakdown(self, tenant: str, minutes: int = 1440) -> Dict[str, Dict[str, int]]:
        """
        For stacked bar: Web vs WhatsApp, each split by inbound/outbound/fallbacks.
        """
        minutes = _clamp_int(minutes, 1440, 1, 60 * 24 * 365)
        since = _utc_iso(datetime.now(timezone.utc) - timedelta(minutes=minutes))

        base = {
            "web": {"inbound": 0, "outbound": 0, "fallbacks": 0},
            "whatsapp": {"inbound": 0, "outbound": 0, "fallbacks": 0},
        }

        try:
            with self._conn() as con:
                rows = con.execute("""
                  SELECT
                    channel,
                    SUM(CASE WHEN event_type='msg_in'  THEN 1 ELSE 0 END) AS inbound,
                    SUM(CASE WHEN event_type='msg_out' THEN 1 ELSE 0 END) AS outbound,
                    SUM(CASE WHEN json_extract(meta_json,'$.fallback') = 1 THEN 1 ELSE 0 END) AS fallbacks
                  FROM events
                  WHERE tenant=? AND ts_utc >= ?
                    AND event_type IN ('msg_in','msg_out')
                  GROUP BY channel
                  ORDER BY channel;
                """, (tenant, since)).fetchall()

            for r in rows:
                ch = str(r["channel"] or "web").strip().lower()
                if ch not in base:
                    base[ch] = {"inbound": 0, "outbound": 0, "fallbacks": 0}
                base[ch] = {
                    "inbound": int(r["inbound"] or 0),
                    "outbound": int(r["outbound"] or 0),
                    "fallbacks": int(r["fallbacks"] or 0),
                }

            return base
        except Exception:
            return base

    def whatsapp_store_share(self, tenant: str, minutes: int = 1440, limit: int = 12) -> List[Dict[str, Any]]:
        """
        Pie: WhatsApp inbound grouped by store/location.
        If store is missing, it will appear as 'international'.
        """
        minutes = _clamp_int(minutes, 1440, 1, 60 * 24 * 365)
        limit = _clamp_int(limit, 12, 1, 50)
        since = _utc_iso(datetime.now(timezone.utc) - timedelta(minutes=minutes))

        try:
            with self._conn() as con:
                rows = con.execute("""
                  SELECT
                    COALESCE(NULLIF(json_extract(meta_json,'$.store'),''), 'international') AS store,
                    COUNT(*) AS count
                  FROM events
                  WHERE tenant=? AND ts_utc >= ?
                    AND channel='whatsapp'
                    AND event_type='msg_in'
                  GROUP BY store
                  ORDER BY count DESC
                  LIMIT ?;
                """, (tenant, since, limit)).fetchall()

            return [{"store": r["store"], "count": int(r["count"] or 0)} for r in rows]
        except Exception:
            return []

