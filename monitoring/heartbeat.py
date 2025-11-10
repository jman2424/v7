"""
Heartbeat monitor — periodic health pings and alert logging.

Purpose:
- Hit /health or /ready endpoints every N minutes.
- Detect downtime or high latency.
- Append results to logs/analytics.log or send webhook alert.

Connections:
- Uses requests (or httpx) to query /health.
- Writes to logs/chatbot.log or analytics.log.
- Optional integration: Ops dashboard webhook (Slack, Discord, etc.).
"""

import time
import logging
import requests
from datetime import datetime

logger = logging.getLogger("Heartbeat")

HEALTH_URL = "http://localhost:10000/health"  # overridden by env if needed
INTERVAL_SECONDS = 300                        # default: every 5 minutes
TIMEOUT = 5.0

def ping_once(url: str = HEALTH_URL) -> dict:
    """Ping /health endpoint and return structured result."""
    start = time.time()
    try:
        resp = requests.get(url, timeout=TIMEOUT)
        latency = round((time.time() - start) * 1000, 2)
        status = resp.status_code
        ok = status == 200 and "ok" in resp.text.lower()
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "url": url,
            "status": status,
            "latency_ms": latency,
            "ok": ok,
        }
    except Exception as e:
        latency = round((time.time() - start) * 1000, 2)
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "url": url,
            "status": None,
            "latency_ms": latency,
            "ok": False,
            "error": str(e),
        }

def log_result(result: dict) -> None:
    """Write structured heartbeat result to logs."""
    status = "UP" if result.get("ok") else "DOWN"
    msg = f"[HEARTBEAT] {status} | {result.get('status')} | {result.get('latency_ms')} ms | {result.get('url')}"
    if not result.get("ok"):
        logger.error(msg)
    else:
        logger.info(msg)

def run_heartbeat(interval: int = INTERVAL_SECONDS) -> None:
    """Run continuous heartbeat loop."""
    logger.info(f"Starting heartbeat monitor every {interval}s → {HEALTH_URL}")
    while True:
        res = ping_once()
        log_result(res)
        time.sleep(interval)
