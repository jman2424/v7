# retrieval/policy_store.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import re

from retrieval.storage import Storage
from service.validators import normalize_postcode


_OUTWARD_RE = re.compile(r"^([A-Z]{1,2})(\d{1,2})([A-Z]?)$")


def _outward(pc: str) -> str:
    """
    "E7 9QS" -> "E7"
    "SW1A 1AA" -> "SW1A"
    "E7" -> "E7"
    """
    n = (normalize_postcode(pc) or "").replace(" ", "")
    return n[:-3] if len(n) > 3 else n


def _prefix(pc: str) -> str:
    # Backwards compat alias (kept because older code uses _prefix)
    return _outward(pc)


def _parse_time_range(rng: str) -> Optional[Tuple[int, int]]:
    if not rng:
        return None
    s = str(rng).strip()
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
    if not isinstance(hours, dict):
        return None

    if hours.get(wd):
        return str(hours[wd])

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


def _split_area_tokens(area: str) -> List[str]:
    """
    Supports:
      - "E1-E4"
      - "E7"
      - "E1,E2,E3"
      - "E1 E2 E3"
      - "E1|E2"
    """
    if not area:
        return []
    a = str(area).upper().strip()
    a = a.replace("–", "-").replace("—", "-")
    # normalize separators to commas, then split
    a = a.replace("|", ",").replace(" ", ",")
    parts = [p.strip() for p in a.split(",") if p.strip()]
    return parts


def _parse_outward_code(code: str) -> Optional[Tuple[str, int, str]]:
    """
    "E7" -> ("E", 7, "")
    "SW1A" -> ("SW", 1, "A")
    """
    m = _OUTWARD_RE.match(code.upper().strip())
    if not m:
        return None
    letters = m.group(1)
    num = int(m.group(2))
    suffix = m.group(3) or ""
    return letters, num, suffix


def _outward_in_range(out: str, start: str, end: str) -> bool:
    """
    Range checks like "E1-E4" (same letter group).
    If suffix letters exist (SW1A), we only allow exact match style, not numeric range.
    """
    o = _parse_outward_code(out)
    a = _parse_outward_code(start)
    b = _parse_outward_code(end)
    if not o or not a or not b:
        return False

    o_letters, o_num, o_suffix = o
    a_letters, a_num, a_suffix = a
    b_letters, b_num, b_suffix = b

    # Only support numeric ranges when letter groups match and there are no suffix letters
    if o_letters != a_letters or o_letters != b_letters:
        return False
    if o_suffix or a_suffix or b_suffix:
        return False

    lo = min(a_num, b_num)
    hi = max(a_num, b_num)
    return lo <= o_num <= hi


def _area_matches_outward(area: str, outward: str) -> bool:
    """
    area examples: "E1-E4", "E7"
    outward example: "E7"
    """
    tokens = _split_area_tokens(area)
    if not tokens:
        return False

    out = outward.upper().strip()

    for tok in tokens:
        if "-" in tok:
            s, e = tok.split("-", 1)
            s = s.strip()
            e = e.strip()
            if s and e and _outward_in_range(out, s, e):
                return True
        else:
            if tok == out:
                return True

    return False


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

        pc_full = pc_norm.replace(" ", "")
        out = _outward(pc_norm)

        # 1) exact exceptions (only if they look like dicts with a postcode)
        for ex in (self._delivery.get("exceptions") or []):
            if not isinstance(ex, dict):
                continue
            ex_pc = (normalize_postcode(str(ex.get("postcode") or "")) or "").replace(" ", "")
            if ex_pc and ex_pc == pc_full:
                rule = {k: v for k, v in ex.items() if k in {"fee", "min_order", "eta_min"}}
                # tolerate legacy keys
                if "min_order" not in rule and "min" in ex:
                    rule["min_order"] = ex.get("min")
                if "eta_min" not in rule and "eta" in ex:
                    rule["eta_min"] = ex.get("eta")
                rule["source"] = "exception"
                return rule

        # 2) NEW schema: zones[] with keys: area, fee, min, eta
        zones = self._delivery.get("zones") or []
        if isinstance(zones, list) and zones:
            for z in zones:
                if not isinstance(z, dict):
                    continue
                area = str(z.get("area") or "")
                if not area:
                    continue
                if _area_matches_outward(area, out):
                    return {
                        "fee": z.get("fee"),
                        "min_order": z.get("min"),
                        "eta_min": z.get("eta"),
                        "source": "zone",
                        "zone": z.get("code") or None,
                        "area": area,
                    }

        # 3) OLD schema: areas[] with keys: postcode_prefix, fee, min_order, eta_min
        for ar in (self._delivery.get("areas") or []):
            if not isinstance(ar, dict):
                continue
            ar_pref = _prefix(str(ar.get("postcode_prefix") or ""))
            if ar_pref and ar_pref == out:
                rule = {k: v for k, v in ar.items() if k in {"fee", "min_order", "eta_min"}}
                rule["source"] = "prefix"
                return rule

        return None

    def delivery_summary(self, postcode: str) -> Optional[str]:
        rule = self.delivery_rule_for(postcode)
        if not rule:
            return None

        parts: List[str] = []
        fee = rule.get("fee")
        min_order = rule.get("min_order")
        eta_min = rule.get("eta_min")

        if isinstance(fee, (int, float)) or (isinstance(fee, str) and fee.strip().replace(".", "", 1).isdigit()):
            parts.append(f"£{float(fee):.2f} fee")
        if isinstance(min_order, (int, float)) or (isinstance(min_order, str) and min_order.strip().replace(".", "", 1).isdigit()):
            parts.append(f"min £{float(min_order):.2f}")
        if isinstance(eta_min, (int, float)) or (isinstance(eta_min, str) and str(eta_min).strip().isdigit()):
            parts.append(f"~{int(float(eta_min))} mins")

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
