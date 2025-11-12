"""
Token-bucket rate limiter (in-proc).

Scopes:
- per IP
- per session
- per endpoint (path or logical key)

Usage:
    rl = RateLimiter(capacity=30, refill_per_sec=0.5)  # 30 tokens, 1 token every 2s
    if not rl.allow(key=f"ip:{ip}:/chat_api"):
        return {"status": "error", "message": "rate_limited"}, 429
"""

from __future__ import annotations
import threading
import time
from dataclasses import dataclass, field
from typing import Dict


@dataclass
class _Bucket:
    tokens: float
    last: float


@dataclass
class RateLimiter:
    capacity: int = 30
    refill_per_sec: float = 0.5  # tokens/second
    _buckets: Dict[str, _Bucket] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def allow(self, key: str, cost: float = 1.0) -> bool:
        """
        Returns True if the action is allowed and deducts `cost` tokens.
        """
        now = time.time()
        with self._lock:
            b = self._buckets.get(key)
            if b is None:
                b = _Bucket(tokens=self.capacity, last=now)
                self._buckets[key] = b

            # refill
            elapsed = max(0.0, now - b.last)
            b.tokens = min(self.capacity, b.tokens + elapsed * self.refill_per_sec)
            b.last = now

            if b.tokens >= cost:
                b.tokens -= cost
                return True
            return False

    def remaining(self, key: str) -> float:
        with self._lock:
            b = self._buckets.get(key)
            if not b:
                return float(self.capacity)
            # approximate current without mutating
            elapsed = max(0.0, time.time() - b.last)
            tokens = min(self.capacity, b.tokens + elapsed * self.refill_per_sec)
            return max(0.0, tokens)

    def reset(self, key: str) -> None:
        with self._lock:
            self._buckets.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._buckets.clear()
