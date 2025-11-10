"""
Synthetic probes — simulate real chat flows and verify responses.

Purpose:
- Run sample chat sessions automatically (FAQ, postcode lookup, bundle offer, etc.).
- Compare actual responses from /chat_api to acceptance packs in tests/acceptance/.
- Detect regressions in intent handling or grounding before deployment.

Connections:
- Reads probe scenarios from tests/acceptance/*.json
- Sends messages via /chat_api (routes/webchat_routes.py)
- Logs results in logs/analytics.log or errors.log

Run:
    python -m monitoring.probes
"""

import json
import logging
import requests
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

logger = logging.getLogger("Probes")

CHAT_API_URL = "http://localhost:10000/chat_api"
TIMEOUT = 10.0
ACCEPTANCE_DIR = Path("tests/acceptance")

def _load_acceptance_packs() -> List[Path]:
    """Return all JSON files in tests/acceptance/ for probes."""
    return sorted(p for p in ACCEPTANCE_DIR.glob("*.json") if p.is_file())

def _send_message(msg: str) -> Dict[str, Any]:
    """POST message to /chat_api and return JSON response."""
    payload = {"message": msg}
    try:
        resp = requests.post(CHAT_API_URL, json=payload, timeout=TIMEOUT)
        data = resp.json() if resp.headers.get("Content-Type", "").startswith("application/json") else {"reply": resp.text}
        return {"ok": resp.status_code == 200, "data": data, "status": resp.status_code}
    except Exception as e:
        return {"ok": False, "error": str(e), "status": None}

def _compare(expected_keywords: List[str], reply_text: str) -> bool:
    """Simple keyword match to confirm expected intent coverage."""
    return all(k.lower() in reply_text.lower() for k in expected_keywords)

def run_probe_file(path: Path) -> Dict[str, Any]:
    """Run synthetic probes for one acceptance pack."""
    logger.info(f"Running probe pack: {path.name}")
    with path.open(encoding="utf-8") as f:
        data = json.load(f)

    results = []
    for item in data:
        message = item.get("input") or ""
        expect = item.get("expect_keywords") or []
        sent = datetime.utcnow().isoformat()
        response = _send_message(message)
        reply = response.get("data", {}).get("reply", "")
        passed = _compare(expect, reply) if expect else response.get("ok", False)
        results.append({
            "input": message,
            "expect": expect,
            "reply": reply,
            "passed": passed,
            "status": response.get("status"),
            "timestamp": sent,
        })
        state = "✅ PASS" if passed else "❌ FAIL"
        logger.info(f"[PROBE] {state} | input={message[:30]} | reply={reply[:60]}")

    summary = {
        "pack": path.name,
        "total": len(results),
        "passed": sum(r["passed"] for r in results),
        "failed": sum(not r["passed"] for r in results),
        "timestamp": datetime.utcnow().isoformat(),
    }
    logger.info(f"[SUMMARY] {summary}")
    return summary

def run_probes() -> List[Dict[str, Any]]:
    """Run all probe packs sequentially and log summaries."""
    packs = _load_acceptance_packs()
    summaries = []
    for pack in packs:
        summaries.append(run_probe_file(pack))
    return summaries

if __name__ == "__main__":
    out = run_probes()
    print(json.dumps(out, indent=2))
