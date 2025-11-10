"""
Cache adapters for retrieval/services.

- InProcCache: simple process-local TTL cache (thread-safe enough for Flask WSGI)
- RedisCache: optional adapter if redis-py is installed and REDIS_URL provided

Interface (Cache):
    get(key) -> Any | None
    set(key, value, ttl_seconds: int | None = None) -> None
    delete(key) -> None
    clear() -> None
"""

from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

try:
    import redis  # type: ignore
    _HAS_REDIS = True
except Exception:
    _HAS_REDIS = False


class Cache:
    def get(self, key: str) -> Any:  # pragma: no cover - interface
        raise NotImplementedError

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:  # pragma: no cover
        raise NotImplementedError

    def delete(self, key: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def clear(self) -> None:  # pragma: no cover
        raise NotImplementedError


class InProcCache(Cache):
    """
    Simple dict-backed cache with per-key TTL.
    Not shared across processes; good enough for single-instance dev or low scale.
    """

    def __init__(self) -> None:
        self._store: Dict[str, Any] = {}
        self._exp: Dict[str, float] = {}

    def _expired(self, key: str) -> bool:
        exp = self._exp.get(key)
        return exp is not None and time.time() > exp

    def get(self, key: str) -> Any:
        if key in self._store and not self._expired(key):
            return self._store[key]
        if key in self._store:
            # expired
            self.delete(key)
        return None

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        self._store[key] = value
        if ttl_seconds:
            self._exp[key] = time.time() + ttl_seconds
        elif key in self._exp:
            del self._exp[key]

    def delete(self, key: str) -> None:
        self._store.pop(key, None)
        self._exp.pop(key, None)

    def clear(self) -> None:
        self._store.clear()
        self._exp.clear()


@dataclass
class RedisCache(Cache):
    """
    Thin wrapper over redis-py for cross-process caching.
    Requires redis package and a valid connection URL.
    """

    url: str
    prefix: str = "asa:"
    _client: Any = None

    def __post_init__(self):
        if not _HAS_REDIS:
            raise RuntimeError("redis package not available; install redis to use RedisCache")
        self._client = redis.Redis.from_url(self.url, decode_responses=True)

    def _k(self, key: str) -> str:
        return f"{self.prefix}{key}"

    def get(self, key: str) -> Any:
        val = self._client.get(self._k(key))
        if val is None:
            return None
        try:
            # store strings; callers can json.dumps/loads as needed
            return val
        except Exception:
            return val

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        if ttl_seconds:
            self._client.setex(self._k(key), ttl_seconds, value)
        else:
            self._client.set(self._k(key), value)

    def delete(self, key: str) -> None:
        self._client.delete(self._k(key))

    def clear(self) -> None:
        # WARNING: This scans and deletes keys with the prefix; safe but O(n)
        cursor = 0
        pattern = f"{self.prefix}*"
        while True:
            cursor, keys = self._client.scan(cursor=cursor, match=pattern, count=500)
            if keys:
                self._client.delete(*keys)
            if cursor == 0:
                break
