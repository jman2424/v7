#!/usr/bin/env python3
"""
Export analytics summary to CSV from events JSONL.

Usage:
  python scripts/export_analytics_csv.py --tenant EXAMPLE \
    [--events logs/analytics.events.jsonl] [--out exports/analytics.csv]

Behavior:
- Reads JSON lines events with shape similar to AnalyticsService.log_event(...)
- Feeds them into services.analytics_service.AnalyticsService
- Writes a CSV summary via services.exporter.analytics_summary_to_csv_bytes
"""

from __future__ import annotations
import argparse
import json
from pathlib import Path

# Local imports
try:
    from services.analytics_service import AnalyticsService  # type: ignore
    from services.exporter import analytics_summary_to_csv_bytes  # type: ignore
except Exception as e:  # pragma: no cover
    raise SystemExit(f"[ERR] Required services not available: {e}")

def load_events(path: Path):
    if not path.exists():
        return []
    lines = path.read_text("utf-8", errors="ignore").splitlines()
    out = []
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out

def main():
    ap = argparse.ArgumentParser(description="Export analytics to CSV")
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--events", default="logs/analytics.events.jsonl")
    ap.add_argument("--out", default="exports/analytics.csv")
    ap.add_argument("--period-minutes", type=int, default=1440)
    args = ap.parse_args()

    tenant = args.tenant
    events = load_events(Path(args.events))
    svc = AnalyticsService(sheets=None)

    for ev in events:
        # Ensure minimal shape
        typ = ev.get("type") or "chat_turn"
        payload = {
            "type": typ,
            "intent": ev.get("intent"),
            "session_id": ev.get("session_id"),
            "mode": ev.get("mode"),
            "ok": ev.get("ok", True),
            "latency_ms": ev.get("latency_ms", 0),
            "channel": ev.get("channel") or "web",
        }
        svc.log_event(tenant, payload)

    summary = svc.summary(tenant, period_minutes=args.period_minutes)
    csv_bytes = analytics_summary_to_csv_bytes(summary)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(csv_bytes)
    print(f"[OK] Wrote CSV → {out_path}")

if __name__ == "__main__":
    main()
