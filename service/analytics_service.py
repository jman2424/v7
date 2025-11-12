"""
Analytics service

Responsibilities:
- Ingest per-turn events (chat turns, errors, conversions)
- Maintain lightweight counters in-memory per-tenant
- Build chart payloads for /analytics routes
- Optionally mirror events to Google Sheets via connectors.sheets.SheetsClient

Design:
- No long-term DB required; JSON exports handled by routes/analytics_routes.py
- Thread-safe via simple per-tenant locks (GIL is enough for CPython; keep ops tiny)
"""

from __future__ import annotations
import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    # Optional import (adapter is present in your repo)
    from connectors.sheets import SheetsClient  # type: ignore
except Exception:  # pragma: no cover
    SheetsClient = None  # type: ignore


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class _TenantStats:
    totals: Dict[str, int] = field(default_factory=dict)
    # rolling buckets for simple charts (epoch minute -> count)
    bucket_chat: Dict[int, int] = field(default_factory=dict)
    intents: Dict[str, int] = field(default_factory=dict)
    items: Dict[str, int] = field(default_factory=dict)
    errors: int = 0


@dataclass
class AnalyticsService:
    sheets: Optional[Any] = None  # SheetsClient-like
    # in-proc store: tenant -> stats
    _stats: Dict[str, _TenantStats] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # ------------- ingest -------------

    def log_event(self, tenant: str, event: Dict[str, Any]) -> None:
        """
        event = {
          "type": "chat_turn" | "conversion" | "error",
          "intent": "search_product",
          "session_id": "...",
          "mode": "AIV7",
          "ok": True,
          "latency_ms": 123,
          "channel": "web"
        }
        """
        if not tenant:
            return
        t = int(time.time())
        minute = t // 60

        with self._lock:
            st = self._stats.setdefault(tenant, _TenantStats())
            # common totals
            st.totals["events"] = st.totals.get("events", 0) + 1
            if event.get("type") == "chat_turn":
                st.totals["chat_turns"] = st.totals.get("chat_turns", 0) + 1
                st.bucket_chat[minute] = st.bucket_chat.get(minute, 0) + 1
                intent = event.get("intent") or "unknown"
                st.intents[intent] = st.intents.get(intent, 0) + 1
            elif event.get("type") == "conversion":
                st.totals["conversions"] = st.totals.get("conversions", 0) + 1
            elif event.get("type") == "error":
                st.errors += 1
                st.totals["errors"] = st.totals.get("errors", 0) + 1

        # Optional: mirror to Sheets
        if self.sheets:
            try:
                self.sheets.append_event(tenant, {"ts": _now_iso(), **event})
            except Exception:
                # do not raise on analytics path
                pass

    def kpi_increment(self, tenant: str, key: str, n: int = 1) -> None:
        if not tenant or not key:
            return
        with self._lock:
            st = self._stats.setdefault(tenant, _TenantStats())
            st.totals[key] = st.totals.get(key, 0) + int(n)

    # ------------- charts / summaries -------------

    def summary(self, tenant: str, period_minutes: int = 60 * 24) -> Dict[str, Any]:
        now_min = int(time.time() // 60)
        start_min = now_min - period_minutes
        with self._lock:
            st = self._stats.get(tenant) or _TenantStats()
            volume = sum(v for m, v in st.bucket_chat.items() if m >= start_min)
            return {
                "tenant": tenant,
                "period_minutes": period_minutes,
                "totals": dict(st.totals),
                "volume_last_period": volume,
                "errors": st.errors,
                "top_intents": self._top_k(st.intents, k=10),
                "top_items": self._top_k(st.items, k=10),
            }

    def chart_timeseries(self, tenant: str, period_minutes: int = 60 * 24) -> Dict[str, Any]:
        now_min = int(time.time() // 60)
        start_min = now_min - period_minutes
        with self._lock:
            st = self._stats.get(tenant) or _TenantStats()
            series = [
                {"minute": m, "count": c}
                for m, c in sorted(st.bucket_chat.items())
                if m >= start_min
            ]
        return {"tenant": tenant, "series": series, "generated_at": _now_iso()}

    # ------------- helpers -------------

    @staticmethod
    def _top_k(d: Dict[str, int], k: int = 5) -> List[Dict[str, Any]]:
        return [{"key": k0, "count": d[k0]} for k0 in sorted(d, key=d.get, reverse=True)[:k]]
