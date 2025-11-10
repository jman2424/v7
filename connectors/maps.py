"""
Maps/Geocoding connector.

Goals:
- Provide an optional postcode -> (lat, lon) lookup for GeoStore.nearest_for_postcode().
- Cache results to avoid repeated external calls.
- Keep backend pluggable (HTTP API, local table, etc.).

Env (optional):
  MAPS_API_URL, MAPS_API_KEY
If not configured, the client will return None (no geocode), and GeoStore will
fallback to outward-prefix branch matching.
"""

from __future__ import annotations
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import urlencode
import urllib.request

GeoPoint = Tuple[float, float]
Backend = Callable[[str], Optional[GeoPoint]]


def _norm_postcode(pc: str) -> str:
    return (pc or "").upper().replace(" ", "").strip()


@dataclass
class _TTLCache:
    ttl: int
    data: Dict[str, Any] = field(default_factory=dict)
    exp: Dict[str, float] = field(default_factory=dict)

    def get(self, k: str) -> Any:
        now = time.time()
        if k in self.data and self.exp.get(k, 0) > now:
            return self.data[k]
        self.data.pop(k, None)
        self.exp.pop(k, None)
        return None

    def set(self, k: str, v: Any) -> None:
        self.data[k] = v
        self.exp[k] = time.time() + self.ttl


@dataclass
class MapsClient:
    backend: Optional[Backend] = None
    cache_ttl_seconds: int = 86_400
    _cache: _TTLCache = field(default_factory=lambda: _TTLCache(ttl=86_400))

    # -------- construction --------

    @classmethod
    def from_env(cls, *, cache_ttl_seconds: int = 86_400) -> "MapsClient":
        url = os.getenv("MAPS_API_URL")
        key = os.getenv("MAPS_API_KEY")
        backend = None
        if url:
            backend = cls._make_http_backend(url, key)
        return cls(backend=backend, cache_ttl_seconds=cache_ttl_seconds, _cache=_TTLCache(cache_ttl_seconds))

    @staticmethod
    def _make_http_backend(base_url: str, api_key: Optional[str]) -> Backend:
        """
        Generic HTTP backend; expects JSON {lat: float, lon: float} or {latitude, longitude}
        GET {base_url}?q={postcode}&key={api_key}
        """
        def _call(postcode: str) -> Optional[GeoPoint]:
            q = _norm_postcode(postcode)
            if not q:
                return None
            params = {"q": q}
            if api_key:
                params["key"] = api_key
            url = f"{base_url}?{urlencode(params)}"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=6) as resp:
                if 200 <= resp.status < 300:
                    data = json.loads(resp.read().decode("utf-8"))
                    lat = data.get("lat") or data.get("latitude")
                    lon = data.get("lon") or data.get("longitude")
                    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                        return (float(lat), float(lon))
            return None
        return _call

    # -------- public API --------

    def geocode(self, postcode: str) -> Optional[GeoPoint]:
        """
        Return (lat, lon) or None.
        Uses in-proc TTL cache; delegates to backend if present, otherwise None.
        """
        pc = _norm_postcode(postcode)
        if not pc:
            return None

        cached = self._cache.get(pc)
        if cached is not None:
            return cached

        result = None
        if self.backend:
            try:
                result = self.backend(pc)
            except Exception:
                result = None

        if result is not None:
            self._cache.set(pc, result)
        return result

    def warm_cache(self, postcode: str, lat: float, lon: float) -> None:
        """Optionally preload a known geocode."""
        pc = _norm_postcode(postcode)
        if pc:
            self._cache.set(pc, (float(lat), float(lon)))
