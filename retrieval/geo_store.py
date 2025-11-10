"""
GeoStore
- Loads branches (id, name, lat, lon, postcode, phone, hours, holidays)
- Provides nearest(lat, lon) and nearest_for_postcode(postcode, geocode_fallback)
- Exposes delivery postcode prefixes (from delivery.json) for router clarifiers
- Basic UK-style postcode normalization + outward-prefix extraction

Optional geocoding:
- You may pass a callable geocoder(postcode) -> (lat, lon) which can be provided
  by connectors.maps (with caching). If not provided, we try to infer nearest by
  comparing outward prefixes to branch postcodes; if still ambiguous, return first.

Branches schema is validated via schemas/branches.schema.json in Storage.
"""

from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from retrieval.storage import Storage

GeoPoint = Tuple[float, float]
Geocoder = Callable[[str], Optional[GeoPoint]]


def _norm_postcode(pc: str) -> str:
    return (pc or "").upper().replace(" ", "").strip()


def _outward(pc: str) -> str:
    pc = _norm_postcode(pc)
    return pc[:-3] if len(pc) > 3 else pc


def _haversine_km(a: GeoPoint, b: GeoPoint) -> float:
    R = 6371.0
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    s = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(s))
    return R * c


@dataclass
class GeoStore:
    storage: Storage

    def __post_init__(self):
        self._branches: List[Dict[str, Any]] = self._load_branches()
        self._delivery = self._load_delivery()
        # Quick indices
        self._branch_by_id: Dict[str, Dict[str, Any]] = { str(b.get("id")): b for b in self._branches }
        self._outward_map: Dict[str, List[Dict[str, Any]]] = {}
        for b in self._branches:
            out = _outward(str(b.get("postcode", "")))
            if out:
                self._outward_map.setdefault(out, []).append(b)

    # -------- loads --------

    def _load_branches(self) -> List[Dict[str, Any]]:
        try:
            data = self.storage.read_json(self.storage.tenant_key, "branches.json")
            if not isinstance(data, list):
                raise ValueError("branches.json must be an array")
            return data
        except FileNotFoundError:
            return []

    def _load_delivery(self) -> Dict[str, Any]:
        try:
            data = self.storage.read_json(self.storage.tenant_key, "delivery.json")
            if not isinstance(data, dict):
                return {}
            return data
        except FileNotFoundError:
            return {}

    # -------- public API --------

    def branches(self) -> List[Dict[str, Any]]:
        return list(self._branches)

    def branch_by_id(self, branch_id: str) -> Optional[Dict[str, Any]]:
        return self._branch_by_id.get(str(branch_id))

    def coverage_prefixes(self) -> List[str]:
        """List of deliverable postcode prefixes from delivery.json"""
        areas = self._delivery.get("areas") or []
        out = []
        for a in areas:
            p = _outward(str(a.get("postcode_prefix") or ""))
            if p:
                out.append(p)
        return sorted(set(out))

    # -------- nearest calculations --------

    def nearest(self, lat: float, lon: float) -> Optional[Dict[str, Any]]:
        if not self._branches:
            return None
        best = None
        best_dist = float("inf")
        for b in self._branches:
            try:
                d = _haversine_km((lat, lon), (float(b.get("lat")), float(b.get("lon"))))
            except Exception:
                continue
            if d < best_dist:
                best_dist = d
                best = b
        if best is None:
            return None
        return {**best, "_distance_km": round(best_dist, 3)}

    def nearest_for_postcode(self, postcode: str, geocoder: Optional[Geocoder] = None) -> Optional[Dict[str, Any]]:
        """
        If geocoder is provided, use lat/lon lookup and then nearest().
        Otherwise, try outward prefix match against branch postcodes; if multiple,
        pick the one with lexicographically smallest id as stable tie-break.
        """
        pc = _norm_postcode(postcode)
        if not pc or not self._branches:
            return None

        if geocoder:
            try:
                pt = geocoder(pc)
                if pt:
                    return self.nearest(pt[0], pt[1])
            except Exception:
                pass

        out = _outward(pc)
        candidates = self._outward_map.get(out, [])
        if candidates:
            candidates.sort(key=lambda b: str(b.get("id")))
            return candidates[0]

        # fallback: first branch (stable order), better than nothing
        b = sorted(self._branches, key=lambda x: str(x.get("id")))[0]
        return b

    # -------- helpers --------

    def distance_between(self, a: GeoPoint, b: GeoPoint) -> float:
        return _haversine_km(a, b)
