#!/usr/bin/env python3
"""
Periodic heartbeat to check service health.

Usage:
  python monitoring/heartbeat.py --http http://localhost:5000 --interval 30 --retries 2
  python monitoring/heartbeat.py                             --interval 30 --retries 2  (in-process)

Behavior:
- Pings GET /health and /ready (best-effort) at a fixed interval.
- Logs failures and exit non-zero if consecutive failures exceed --retries.
- Optional webhook notify via stdout (you can extend to Slack/Email easily).

Connects:
- routes/health_routes.py (expects /health, /ready).
- logs/* (stdout can be captured by your process manager).
"""

from __future__ import annotations
import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from urllib.parse import urljoin
from urllib.request import Request, urlopen

@dataclass
class PingResult:
    ok: bool
    status: int
    body: str

class Transport:
    def get(self, path: str) -> PingResult:
        raise NotImplementedError

class HttpTransport(Transport):
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/") + "/"

    def get(self, path: str) -> PingResult:
        url = urljoin(self.base, path.lstrip("/"))
        req = Request(url, method="GET")
        try:
            with urlopen(req, timeout=10) as resp:
                body = resp.read().decode("utf-8", "replace")
                return PingResult(True, resp.status, body)
        except Exception as e:
            return PingResult(False, 0, f"{type(e).__name__}: {e}")

class InProcessTransport(Transport):
    def __init__(self):
        from app import create_app  # lazy import
        self.app = create_app()
        self.client = self.app.test_client()

    def get(self, path: str) -> PingResult:
        try:
            r = self.client.get(path)
            body = r.get_data(as_text=True)
            return PingResult(r.status_code == 200, r.status_code, body)
        except Exception as e:
            return PingResult(False, 0, f"{type(e).__name__}: {e}")

class Heartbeat:
    def __init__(self, transport: Transport, interval: int = 30, retries: int = 2):
        self.t = transport
        self.interval = max(5, int(interval))
        self.retries = max(0, int(retries))

    def ping_once(self) -> bool:
        ok1 = self._check("/health", "health")
        ok2 = self._check("/ready", "ready")  # may not exist; best-effort
        return ok1 and (ok2 or True)

    def _check(self, path: str, name: str) -> bool:
        res = self.t.get(path)
        status = "OK" if res.ok else "FAIL"
        print(f"[{status}] {name} {path} status={res.status} body={res.body[:180]}", flush=True)
        return res.ok

    def run(self):
        fails = 0
        while True:
            ok = self.ping_once()
            if not ok:
                fails += 1
                if fails > self.retries:
                    print(f"[ALERT] Heartbeat consecutive failures > {self.retries}. Exiting 1.", flush=True)
                    sys.exit(1)
            else:
                fails = 0
            time.sleep(self.interval)

def main():
    ap = argparse.ArgumentParser(description="Heartbeat pinger")
    ap.add_argument("--http", default=None, help="Base URL. If omitted, runs in-process.")
    ap.add_argument("--interval", type=int, default=30, help="Seconds between checks (min 5).")
    ap.add_argument("--retries", type=int, default=2, help="Consecutive failures before exit 1.")
    args = ap.parse_args()

    t = HttpTransport(args.http) if args.http else InProcessTransport()
    Heartbeat(t, interval=args.interval, retries=args.retries).run()

if __name__ == "__main__":
    main()
