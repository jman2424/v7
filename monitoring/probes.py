#!/usr/bin/env python3
"""
Synthetic probes runner aligned with tests/acceptance/* packs.

Supports two targets:
  1) In-process (default): import app.create_app() and use Flask test_client()
  2) HTTP: --http http://localhost:8000 (posts to /chat_api on that base URL)

Pack format (see tests/acceptance/*.json):
{
  "name": "...",
  "cases": [
     {
        "id": "unique.id",
        "input": "single-turn text",
        "expect": {
            "intent": "search_product|browse_category",
            "needs_clarification": true,
            "answer_contains": ["..."],
            "answer_contains_any": ["...","..."],
            "clarifier_contains": ["postcode"],
            "cta_contains_any": ["Anything else"],
            "must_not_contain": ["worldwide"],
            "rule": {"min_order": 25.0, "fee_between": [3.0, 4.0]},
            "nearest_branch_contains": ["East"]
        }
     },
     {
        "id": "mem.turns",
        "turns": [
           {"user": "first msg"},
           {"user": "second msg", "expect": {...}}
        ]
     }
  ]
}

Exit code:
- 0 if all cases pass
- 1 if any failure

Usage:
  python monitoring/probes.py --packs tests/acceptance --http http://localhost:5000
  python monitoring/probes.py --packs tests/acceptance               # in-process

"""

from __future__ import annotations
import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin
from urllib.request import Request, urlopen

# -----------------------------
# Transport abstraction
# -----------------------------

class Transport:
    def send(self, message: str, session_id: str, metadata: Optional[dict] = None) -> dict:
        raise NotImplementedError

class HttpTransport(Transport):
    def __init__(self, base_url: str, chat_path: str = "/chat_api"):
        self.base = base_url.rstrip("/") + "/"
        self.chat_path = chat_path.lstrip("/")

    def send(self, message: str, session_id: str, metadata: Optional[dict] = None) -> dict:
        payload = {
            "message": message,
            "session_id": session_id,
            "metadata": metadata or {"channel": "probe"}
        }
        data = json.dumps(payload).encode("utf-8")
        req = Request(
            urljoin(self.base, self.chat_path),
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8", "replace")
            try:
                return json.loads(body)
            except Exception:
                return {"reply": body}

class InProcessTransport(Transport):
    def __init__(self):
        # Import lazily so this module can be used without Flask at runtime if needed.
        from app import create_app  # type: ignore
        self.app = create_app()
        self.client = self.app.test_client()

    def send(self, message: str, session_id: str, metadata: Optional[dict] = None) -> dict:
        payload = {
            "message": message,
            "session_id": session_id,
            "metadata": metadata or {"channel": "probe"}
        }
        r = self.client.post("/chat_api", json=payload)
        try:
            return r.get_json(force=True, silent=True) or {"reply": r.data.decode("utf-8", "replace")}
        except Exception:
            return {"reply": r.data.decode("utf-8", "replace")}

# -----------------------------
# Assertions aligned to pack schema
# -----------------------------

@dataclass
class CaseResult:
    case_id: str
    ok: bool
    details: List[str] = field(default_factory=list)

    def add(self, ok: bool, msg: str):
        self.ok = self.ok and ok
        self.details.append(("[OK] " if ok else "[FAIL] ") + msg)

def norm(s: str) -> str:
    return (s or "").strip()

def lower(s: str) -> str:
    return norm(s).lower()

def contains_all(text: str, needles: List[str]) -> Tuple[bool, List[str]]:
    text_l = lower(text)
    missing = [n for n in needles if lower(n) not in text_l]
    return (len(missing) == 0, missing)

def contains_any(text: str, needles: List[str]) -> bool:
    text_l = lower(text)
    return any(lower(n) in text_l for n in needles)

def absent_all(text: str, needles: List[str]) -> Tuple[bool, List[str]]:
    text_l = lower(text)
    present = [n for n in needles if lower(n) in text_l]
    return (len(present) == 0, present)

def intent_matches(got: Optional[str], spec: Optional[str]) -> bool:
    if not spec:
        return True
    if not got:
        # No intent surfaced by API; treat as soft-pass
        return True
    # Allow pipes (A|B)
    allowed = [lower(x) for x in spec.split("|")]
    return lower(got) in allowed

CURR_NUM_RE = re.compile(r"(£|\bGBP\b)\s*([0-9]+(?:\.[0-9]{1,2})?)")

def parse_first_currency(text: str) -> Optional[float]:
    m = CURR_NUM_RE.search(text)
    if not m:
        # try bare number
        n = re.search(r"\b([0-9]+(?:\.[0-9]{1,2})?)\b", text)
        if not n:
            return None
        try:
            return float(n.group(1))
        except Exception:
            return None
    try:
        return float(m.group(2))
    except Exception:
        return None

# -----------------------------
# Probe Runner
# -----------------------------

class ProbeRunner:
    def __init__(self, transport: Transport, verbose: bool = True):
        self.t = transport
        self.verbose = verbose

    def _run_turn(self, session_id: str, user_msg: str) -> dict:
        return self.t.send(user_msg, session_id, metadata={"channel": "probe", "agent": "monitor"})

    def _eval_expectations(self, result: CaseResult, reply_payload: dict, expect: dict):
        reply = norm(reply_payload.get("reply") or "")
        got_intent = reply_payload.get("intent")

        # intent
        if "intent" in expect:
            ok = intent_matches(got_intent, expect["intent"])
            result.add(ok, f"intent match (got={got_intent!r}, expect={expect['intent']!r})")

        # needs_clarification (if API exposes a flag; else infer from clarifier phrases)
        if expect.get("needs_clarification") is True:
            need_flag = bool(reply_payload.get("needs_clarification"))
            inferred = contains_any(reply, ["postcode", "sku", "which", "how many"])
            ok = need_flag or inferred
            result.add(ok, "needs_clarification asserted/inferred")

        # answer_contains (all)
        if "answer_contains" in expect:
            ok, missing = contains_all(reply, expect["answer_contains"])
            result.add(ok, f"answer contains all {expect['answer_contains']} (missing={missing})")

        # answer_contains_any (any)
        if "answer_contains_any" in expect:
            ok = contains_any(reply, expect["answer_contains_any"])
            result.add(ok, f"answer contains any {expect['answer_contains_any']}")

        # must_not_contain
        if "must_not_contain" in expect:
            ok, present = absent_all(reply, expect["must_not_contain"])
            result.add(ok, f"answer must_not_contain {expect['must_not_contain']} (present={present})")

        # clarifier_contains
        if "clarifier_contains" in expect:
            ok, missing = contains_all(reply, expect["clarifier_contains"])
            result.add(ok, f"clarifier contains {expect['clarifier_contains']} (missing={missing})")

        # cta_contains_any
        if "cta_contains_any" in expect:
            ok = contains_any(reply, expect["cta_contains_any"])
            result.add(ok, f"cta contains any {expect['cta_contains_any']}")

        # rule (geo/delivery) — check JSON fields if present; else heuristics on reply text
        if "rule" in expect:
            exp = expect["rule"] or {}
            rule_json = (reply_payload.get("delivery") or {}).get("rule") or reply_payload.get("rule")
            if isinstance(rule_json, dict):
                if "min_order" in exp:
                    ok = float(rule_json.get("min_order", -1)) == float(exp["min_order"])
                    result.add(ok, f"rule.min_order == {exp['min_order']} (got={rule_json.get('min_order')})")
                if "fee_between" in exp:
                    lo, hi = exp["fee_between"]
                    fee = float(rule_json.get("fee", -999))
                    ok = lo <= fee <= hi
                    result.add(ok, f"rule.fee in [{lo}, {hi}] (got={fee})")
            else:
                # Heuristic from reply text
                if "min_order" in exp:
                    ok = contains_any(reply, [str(int(exp["min_order"])), f"£{int(exp['min_order'])}"])
                    result.add(ok, f"min_order heuristic ({exp['min_order']})")
                if "fee_between" in exp:
                    v = parse_first_currency(reply)
                    if v is None:
                        result.add(False, "fee heuristic: no currency found in reply")
                    else:
                        lo, hi = exp["fee_between"]
                        result.add(lo <= v <= hi, f"fee heuristic in [{lo},{hi}] (got={v})")

        # nearest_branch_contains
        if "nearest_branch_contains" in expect:
            ok = contains_any(reply, expect["nearest_branch_contains"])
            result.add(ok, f"nearest branch mentions any {expect['nearest_branch_contains']}")

    # ---- public run methods ----

    def run_pack(self, pack_path: Path) -> Tuple[bool, List[CaseResult]]:
        pack = json.loads(pack_path.read_text("utf-8"))
        name = pack.get("name") or pack_path.name
        cases = pack.get("cases") or []

        results: List[CaseResult] = []
        for c in cases:
            cid = c.get("id") or f"case_{len(results)+1}"
            result = CaseResult(case_id=cid, ok=True)
            session_id = f"probe_{hash(cid) & 0xfffffff}_{int(time.time()*1000)%100000}"
            try:
                if "turns" in c:  # multi-turn
                    last_payload = {}
                    for idx, turn in enumerate(c["turns"]):
                        user_msg = turn.get("user") or ""
                        last_payload = self._run_turn(session_id, user_msg)
                        if "expect" in turn:
                            self._eval_expectations(result, last_payload, turn["expect"])
                else:  # single turn
                    user_msg = c.get("input", "")
                    payload = self._run_turn(session_id, user_msg)
                    self._eval_expectations(result, payload, c.get("expect", {}))
            except Exception as e:
                result.add(False, f"exception: {e!r}")

            results.append(result)
            if self.verbose:
                status = "PASS" if result.ok else "FAIL"
                print(f"[{status}] {cid}")
                for line in result.details:
                    print("  ", line)

        all_ok = all(r.ok for r in results)
        if self.verbose:
            passed = sum(1 for r in results if r.ok)
            print(f"\n[SUMMARY] {name}: {passed}/{len(results)} passed.")
        return all_ok, results

    def run_dir(self, packs_dir: Path, pattern: str = "*.json") -> Tuple[bool, List[CaseResult]]:
        all_results: List[CaseResult] = []
        all_ok = True
        for p in sorted(packs_dir.glob(pattern)):
            ok, res = self.run_pack(p)
            all_ok = all_ok and ok
            all_results.extend(res)
        return all_ok, all_results

# -----------------------------
# CLI
# -----------------------------

def main():
    ap = argparse.ArgumentParser(description="Run synthetic probes against /chat_api")
    ap.add_argument("--packs", default="tests/acceptance", help="Directory containing *.json packs")
    ap.add_argument("--http", default=None, help="Base URL for HTTP mode (e.g., http://localhost:5000)")
    ap.add_argument("--pattern", default="*.json", help="Glob within packs dir")
    ap.add_argument("--quiet", action="store_true", help="Less verbose output")
    args = ap.parse_args()

    # Choose transport
    if args.http:
        t: Transport = HttpTransport(args.http)
    else:
        t = InProcessTransport()

    runner = ProbeRunner(t, verbose=not args.quiet)
    packs_dir = Path(args.packs)
    ok, _ = runner.run_dir(packs_dir, pattern=args.pattern)
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
