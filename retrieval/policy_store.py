# retrieval/policy_store.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from retrieval.storage import Storage
from service.validators import normalize_postcode


def _prefix(pc: str) -> str:
    n = (normalize_postcode(pc) or "").replace(" ", "")
    return n[:-3] if len(n) > 3 else n


def _parse_time_range(rng: str) -> Optional[tuple[int, int]]:
    if not rng:
        return None
    s = str(rng).strip()
    # normalize en-dash / em-dash to hyphen
    s = s.replace("–", "-").replace("—", "-")
    if "-" not in s:
        return None
    start_s, end_s = s.split("-", 1)
    start_s = start_s.strip()
    end_s = end_s.strip()

    def to_hhmm(x: str) -> Optional[int]:
        x = x.strip().replace(":", "")
        if len(x) < 3:
            return None
        try:
            return int(x[:4])
        except Exception:
            return None

    a = to_hhmm(start_s)
    b = to_hhmm(end_s)
    if a is None or b is None:
        return None
    return a, b


def _weekday_key(dt: datetime) -> str:
    return ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][dt.weekday()]


def _hours_for_day(hours: Dict[str, Any], wd: str) -> Optional[str]:
    """
    Supports:
      - exact day keys: mon/tue/...
      - ranges: "mon-sat", "mon-fri"
      - "daily"
      - weekend keys
    """
    if not isinstance(hours, dict):
        return None

    # direct match
    if hours.get(wd):
        return str(hours[wd])

    # range match (mon-sat)
    day_order = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    idx = {d: i for i, d in enumerate(day_order)}
    wdi = idx.get(wd, -1)

    for k, v in hours.items():
        key = str(k).strip().lower().replace(" ", "")
        if "-" in key and len(key.split("-", 1)) == 2:
            a, b = key.split("-", 1)
            if a in idx and b in idx:
                if idx[a] <= wdi <= idx[b]:
                    return str(v)

    if hours.get("daily"):
        return str(hours["daily"])

    return None


@dataclass
class PolicyStore:
    storage: Storage

    def __post_init__(self):
        self._delivery = self._load("delivery.json") or {}
        self._branches: List[Dict[str, Any]] = self._load("branches.json") or []

    def _load(self, filename: str):
        try:
            return self.storage.read_json(self.storage.tenant_key, filename)
        except FileNotFoundError:
            return None

    # -------- delivery --------
    def delivery_rule_for(self, postcode: str) -> Optional[Dict[str, Any]]:
        pc_norm = normalize_postcode(postcode)
        if not pc_norm:
            return None

        pc = pc_norm.replace(" ", "")

        # 1) exact exceptions
        for ex in (self._delivery.get("exceptions") or []):
            ex_pc = (normalize_postcode(str(ex.get("postcode") or "")) or "").replace(" ", "")
            if ex_pc and ex_pc == pc:
                rule = {k: v for k, v in ex.items() if k in {"fee", "min_order", "eta_min"}}
                rule["source"] = "exception"
                return rule

        # 2) prefix areas
        pref = _prefix(pc_norm)
        for ar in (self._delivery.get("areas") or []):
            ar_pref = _prefix(str(ar.get("postcode_prefix") or ""))
            if ar_pref and ar_pref == pref:
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
            parts.append(f"£{float(rule['fee']):.2f} fee")
        if "min_order" in rule:
            parts.append(f"min £{float(rule['min_order']):.2f}")
        if "eta_min" in rule:
            parts.append(f"~{int(rule['eta_min'])} mins")
        return ", ".join(parts) if parts else None

    def click_and_collect(self) -> bool:
        v = self._delivery.get("click_and_collect")
        return bool(v) if v is not None else True

    def delivery_notes(self) -> Optional[str]:
        n = self._delivery.get("notes")
        return str(n) if n else None

    # -------- hours / open-closed --------
    def is_open(self, branch_id: str, at: Optional[datetime] = None) -> Optional[bool]:
        br = next((b for b in self._branches if str(b.get("id")) == str(branch_id)), None)
        if not br:
            return None

        hours = br.get("hours") or {}
        if not isinstance(hours, dict):
            return None

        dt = at or datetime.now()
        wd = _weekday_key(dt)

        rng = _hours_for_day(hours, wd)
        if not rng:
            return False

        parsed = _parse_time_range(rng)
        if not parsed:
            return None

        start_hhmm, end_hhmm = parsed
        cur = int(dt.strftime("%H%M"))
        return start_hhmm <= cur <= end_hhmm

    def open_range_today(self, branch_id: str, at: Optional[datetime] = None) -> Optional[str]:
        br = next((b for b in self._branches if str(b.get("id")) == str(branch_id)), None)
        if not br:
            return None

        hours = br.get("hours") or {}
        if not isinstance(hours, dict):
            return None

        dt = at or datetime.now()
        wd = _weekday_key(dt)

        rng = _hours_for_day(hours, wd)
        return str(rng) if rng else None
