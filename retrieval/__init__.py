"""
Retrieval package convenience exports.

Provides:
- Storage abstraction
- Cache implementations (in-proc and optional Redis).

This file is defensive: if `cache.py` is missing or Redis extras
aren't available, we still import cleanly and fall back to a no-op cache.
"""

from __future__ import annotations

from typing import Optional, Any

from .storage import Storage  # main persistence / JSON loader

# Try to import cache implementations; fall back gracefully if missing.
try:
    from .cache import Cache, InProcCache, RedisCache
except Exception:
    class Cache:
        """Minimal no-op cache interface."""

        def get(self, key: str) -> Any:
            return None

        def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
            return None

    class InProcCache(Cache):
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            super().__init__()

    class RedisCache(Cache):
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("Redis cache not available in this build")


__all__ = [
    "Storage",
    "Cache",
    "InProcCache",
    "RedisCache",
]
