# retrieval/geo_store.py
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from retrieval.storage import Storage
from service.validators import normalize_postcode  # reuse your validator

GeoPoint = Tuple[float, float]
Geocoder = Callable[[str], Optional[GeoPoint]]


def _outward(pc: str) -> str:
    # normalize_postcode can return outward-only already (like "E1") OR full "E1 6AN"
    n = normalize_postcode(pc) or ""
    n = n.replace(" ", "")
    return n[:-3] if len(n) > 3 else n


def _haversine_km(a: GeoPoint, b: GeoPoint) -> float:
    R = 6371.0
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    s = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(s))
    return R * c


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return _haversine_km((lat1, lon1), (lat2, lon2))


@dataclass(init=False)
class GeoStore:
    storage: Optional[Storage]

    def __init__(
        self,
        storage: Optional[Storage | List[Dict[str, Any]]] = None,
        *,
        branches: Optional[List[Dict[str, Any]]] = None,
        data: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        if isinstance(storage, list) and branches is None and data is None:
            branches = storage
            storage = None

        self.storage = storage if isinstance(storage, Storage) else None
        self._branches: List[Dict[str, Any]] = branches or data or self._load_branches()
        self._delivery: Dict[str, Any] = self._load_delivery()

        self._branch_by_id: Dict[str, Dict[str, Any]] = {str(b.get("id")): b for b in self._branches}

        self._outward_map: Dict[str, List[Dict[str, Any]]] = {}
        for b in self._branches:
            out = _outward(str(b.get("postcode", "")))
            if out:
                self._outward_map.setdefault(out, []).append(b)

    def _load_branches(self) -> List[Dict[str, Any]]:
        if self.storage is None:
            return []
        try:
            data = self.storage.read_json(self.storage.tenant_key, "branches.json")
            if not isinstance(data, list):
                raise ValueError("branches.json must be an array")
            return data
        except FileNotFoundError:
            return []

    def _load_delivery(self) -> Dict[str, Any]:
        if self.storage is None:
            return {}
        try:
            data = self.storage.read_json(self.storage.tenant_key, "delivery.json")
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}

    # -------- public API --------
    def branches(self) -> List[Dict[str, Any]]:
        return list(self._branches)

    def branch_by_id(self, branch_id: str) -> Optional[Dict[str, Any]]:
        return self._branch_by_id.get(str(branch_id))

    def coverage_prefixes(self) -> List[str]:
        areas = self._delivery.get("areas") or []
        out: List[str] = []
        for a in areas:
            p = _outward(str(a.get("postcode_prefix") or ""))
            if p:
                out.append(p)
        if not out:
            out = [_outward(str(b.get("postcode", ""))) for b in self._branches]
        return sorted(set(out))

    def covered_prefixes(self, prefix: str = "") -> List[str]:
        pref = str(prefix or "").upper().strip()
        values = self.coverage_prefixes()
        return [p for p in values if not pref or p.startswith(pref)]

    # -------- nearest calculations --------
    def nearest(self, lat: float, lon: float, radius_km: Optional[float] = None) -> Optional[Dict[str, Any]]:
        if not self._branches:
            return None

        best: Optional[Dict[str, Any]] = None
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

        if radius_km is not None and best_dist > float(radius_km):
            return None

        dist = round(best_dist, 3)
        return {**best, "_distance_km": dist, "distance_km": dist}

    def nearest_for_postcode(self, postcode: str, geocoder: Optional[Geocoder] = None) -> Optional[Dict[str, Any]]:
        pc = normalize_postcode(postcode)
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
        candidates = list(self._outward_map.get(out, []))
        if candidates:
            candidates.sort(key=lambda b: str(b.get("id")))
            return candidates[0]

        # stable fallback
        return sorted(self._branches, key=lambda x: str(x.get("id")))[0]

    def distance_between(self, a: GeoPoint, b: GeoPoint) -> float:
        return _haversine_km(a, b)

    def to_geojson(self) -> Dict[str, Any]:
        features: List[Dict[str, Any]] = []
        for branch in self._branches:
            try:
                lat = float(branch.get("lat"))
                lon = float(branch.get("lon"))
            except Exception:
                continue
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                    "properties": {k: v for k, v in branch.items() if k not in {"lat", "lon"}},
                }
            )
        return {"type": "FeatureCollection", "features": features}
