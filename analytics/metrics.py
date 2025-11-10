"""
Analytics metrics — compute KPIs, rollups, and summaries.

Event Contract (emitted by services/analytics_service.py):
{
  "timestamp": "2025-11-09T12:34:56Z",
  "tenant": "EXAMPLE",
  "session_id": "asa_...",
  "channel": "web" | "wa",
  "intent": "faq.hours" | "delivery.lookup" | "catalog.search" | "sales.offer" | ...,
  "resolved": true|false,
  "confidence": 0.0..1.0,
  "clarifier": true|false,
  "deflected": true|false,               # handled by assistant, no human
  "offer_shown": true|false,
  "offer_clicked": true|false,
  "value_estimate": 0.0,                 # optional £
  "latency_ms": 0..N
}

KPIs:
- deflection_rate          = deflected / total
- offer_ctr                = offer_clicked / offer_shown
- avg_latency_ms
- first_response_p50_ms    (approx)
- resolution_rate          = resolved / total
- intent_top_n             (counts)
- item_search_top_n        (from intent="catalog.search" + extracted item/tag if present)

Rollups:
- by day/hour/channel/tenant with the same KPIs.

Notes:
- Pure functions (no I/O), safe for unit tests.
- Time parsing via datetime.fromisoformat fallback helper.
"""

from __future__ import annotations
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import median
from typing import Any, Dict, Iterable, List, Tuple


ISO_FMT = "%Y-%m-%dT%H:%M:%S"


def _parse_ts(ts: str) -> datetime:
    # Accept Z or offsetless ISO; fallback to fromisoformat
    try:
        if ts.endswith("Z"):
            return datetime.fromisoformat(ts[:-1]).replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(ts)
    except Exception:
        # last resort: strip microseconds if present
        t = ts.split(".")[0].replace("Z", "")
        return datetime.strptime(t, ISO_FMT).replace(tzinfo=timezone.utc)


def _safe_bool(v: Any) -> bool:
    return bool(v) is True


def compute_kpis(events: Iterable[Dict[str, Any]], top_n: int = 10) -> Dict[str, Any]:
    events = list(events)
    total = len(events)
    if total == 0:
        return {
            "total": 0,
            "deflection_rate": 0.0,
            "offer_ctr": 0.0,
            "avg_latency_ms": 0.0,
            "p50_latency_ms": 0.0,
            "resolution_rate": 0.0,
            "top_intents": [],
            "top_channels": [],
            "time_range": None,
        }

    deflected = sum(1 for e in events if _safe_bool(e.get("deflected")))
    offer_shown = sum(1 for e in events if _safe_bool(e.get("offer_shown")))
    offer_clicked = sum(1 for e in events if _safe_bool(e.get("offer_clicked")))
    resolved = sum(1 for e in events if _safe_bool(e.get("resolved")))
    latencies = [float(e.get("latency_ms", 0.0)) for e in events if e.get("latency_ms") is not None]

    intents = Counter(str(e.get("intent", "unknown")) for e in events)
    channels = Counter(str(e.get("channel", "unknown")) for e in events)

    # Time bounds
    times = sorted(_parse_ts(str(e.get("timestamp"))) for e in events if e.get("timestamp"))
    t0, t1 = (times[0], times[-1]) if times else (None, None)

    kpis = {
        "total": total,
        "deflection_rate": round(deflected / total, 4),
        "offer_ctr": round((offer_clicked / offer_shown), 4) if offer_shown else 0.0,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
        "p50_latency_ms": round(median(latencies), 2) if latencies else 0.0,
        "resolution_rate": round(resolved / total, 4),
        "top_intents": intents.most_common(top_n),
        "top_channels": channels.most_common(top_n),
        "time_range": {
            "start": t0.isoformat() if t0 else None,
            "end": t1.isoformat() if t1 else None,
            "days": (t1 - t0).days + 1 if t0 and t1 else 0,
        },
    }
    return kpis


def _bucket_key(dt: datetime, by: str) -> str:
    if by == "hour":
        return dt.strftime("%Y-%m-%d %H:00")
    if by == "day":
        return dt.strftime("%Y-%m-%d")
    if by == "week":
        # ISO week
        iso = dt.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    return "all"


def compute_rollups(events: Iterable[Dict[str, Any]], by: str = "day") -> Dict[str, Any]:
    """
    Roll up KPIs by time bucket and by channel.
    Returns:
    {
      "by_time": { "2025-11-09": {kpis}, ... },
      "by_channel": { "web": {kpis}, "wa": {kpis} }
    }
    """
    buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    channels: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for e in events:
        ts = e.get("timestamp")
        dt = _parse_ts(str(ts)) if ts else None
        key = _bucket_key(dt, by) if dt else "unknown"
        buckets[key].append(e)
        channels[str(e.get("channel", "unknown"))].append(e)

    by_time = {k: compute_kpis(v) for k, v in sorted(buckets.items())}
    by_channel = {k: compute_kpis(v) for k, v in channels.items()}
    return {"by_time": by_time, "by_channel": by_channel}


def summarize_tenant(events: Iterable[Dict[str, Any]], tenant: str) -> Dict[str, Any]:
    """
    Filter events by tenant and compute a compact dashboard summary.
    """
    ev = [e for e in events if str(e.get("tenant")) == tenant]
    kpis = compute_kpis(ev)
    roll = compute_rollups(ev, by="day")
    return {
        "tenant": tenant,
        "kpis": kpis,
        "rollups": roll,
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }
