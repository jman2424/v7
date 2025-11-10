"""
PolicyStore
- Loads delivery rules from business/{TENANT}/delivery.json
- Provides postcode-based fee/min_order/eta lookup with exception override
- Formats human-readable delivery summaries
- Loads branch hours/holidays (from branches.json) for open/closed checks

Notes:
- We keep hours in branches.json (per-branch). PolicyStore reads it to compute open/closed.
- Postcode normalization is shared with GeoStore logic (simple UK-style: strip spaces, take outward code prefix).

delivery.json:
{
  "areas": [
    {"postcode_prefix": "E6", "fee": 2.5, "min_order": 15, "eta_min": 40}
  ],
  "click_and_collect": true,
  "exceptions": [
    {"postcode": "E6 1AA", "fee": 4.0, "eta_min": 60}
  ],
  "notes": "Free over £50"
}
"""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from retrieval.storage import Storage


def _norm_postcode(pc: str) -> str:
    return (pc or "").upper().replace(" ", "").strip()


def _prefix(pc: str) -> str:
    # simple outward code prefix heuristics: letters+digits until next digit group changes
    pc = _norm_postcode(pc)
    # for UK-like codes, outward is 2-4 chars; we take first letter+digit cluster
    # fallback: first 2 chars
    if not pc:
        return ""
    # take leading letters+digits until we hit final 3 chars (inward)
    return pc[:-3] if len(pc) > 3 else pc


@dataclass
class PolicyStore:
    storage: Storage

    def __post_init__(self):
        self._delivery = self._load("delivery.json") or {}
        self._branches: List[Dict[str, Any]] = self._load("branches.json") or []

    # -------- internal --------

    def _load(self, filename: str):
        try:
            return self.storage.read_json(self.storage.tenant_key, filename)
        except FileNotFoundError:
            return None

    # -------- delivery --------

    def delivery_rule_for(self, postcode: str) -> Optional[Dict[str, Any]]:
        """
        Return effective delivery rule dict for a postcode:
        { fee?, min_order?, eta_min?, source: 'exception'|'prefix' }
        """
        pc = _norm_postcode(postcode)
        if not pc:
            return None

        # 1) exact exception match
        for ex in (self._delivery.get("exceptions") or []):
            ex_pc = _norm_postcode(str(ex.get("postcode") or ""))
            if ex_pc and ex_pc == pc:
                rule = {k: v for k, v in ex.items() if k in {"fee", "min_order", "eta_min"}}
                rule["source"] = "exception"
                return rule

        # 2) prefix match
        pref = _prefix(pc)
        for ar in (self._delivery.get("areas") or []):
            if _norm_postcode(str(ar.get("postcode_prefix") or "")) == pref:
                rule = {k: v for k, v in ar.items() if k in {"fee", "min_order", "eta_min"}}
                rule["source"] = "prefix"
                return rule

        return None

    def delivery_summary(self, postcode: str) -> Optional[str]:
        rule = self.delivery_rule_for(postcode)
        if not rule:
            return None
        parts = []
        if "fee" in rule:
            parts.append(f"£{rule['fee']:.2f} fee")
        if "min_order" in rule:
            parts.append(f"min £{rule['min_order']:.2f}")
        if "eta_min" in rule:
            parts.append(f"~{int(rule['eta_min'])} mins")
        return ", ".join(parts) if parts else None

    def click_and_collect(self) -> bool:
        v = self._delivery.get("click_and_collect")
        return bool(v) if v is not None else True

    def delivery_notes(self) -> Optional[str]:
        return self._delivery.get("notes")

    # -------- hours / open-closed --------

    def is_open(self, branch_id: str, at: Optional[datetime] = None) -> Optional[bool]:
        br = next((b for b in self._branches if str(b.get("id")) == str(branch_id)), None)
        if not br:
            return None
        hrs = br.get("hours") or {}
        if not isinstance(hrs, dict):
            return None
        dt = at or datetime.now()
        wd = ["mon","tue","wed","thu","fri","sat","sun"][dt.weekday()]
        rng = hrs.get(wd)
        if not rng:
            return False
        # handle "09:00-18:00" style
        try:
            start_s, end_s = str(rng).split("-", 1)
            t_start = int(start_s.replace(":", "")[:4])
            t_end = int(end_s.replace(":", "")[:4])
            cur = int(dt.strftime("%H%M"))
            return t_start <= cur <= t_end
        except Exception:
            return None

    def open_range_today(self, branch_id: str, at: Optional[datetime] = None) -> Optional[str]:
        br = next((b for b in self._branches if str(b.get("id")) == str(branch_id)), None)
        if not br:
            return None
        hrs = br.get("hours") or {}
        dt = at or datetime.now()
        wd = ["mon","tue","wed","thu","fri","sat","sun"][dt.weekday()]
        rng = hrs.get(wd)
        if not rng:
            return None
        return str(rng)
