"""Bound repeated sign-in attempts without persisting account identifiers."""

from __future__ import annotations

import hashlib
import threading
import time
from collections import deque


class LoginAttemptLimiter:
    """Small in-process limiter for the authentication boundary.

    The key combines the client address with a one-way representation of the
    tenant and identifier. It is intentionally not written to operational logs.
    """

    def __init__(self, *, max_attempts: int, window_seconds: int) -> None:
        self.max_attempts = max(1, int(max_attempts))
        self.window_seconds = max(1, int(window_seconds))
        self._attempts: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def key(*, client_address: str, tenant: str, identifier: str) -> str:
        subject = f"{tenant.strip().upper()}\x00{identifier.strip().lower()}"
        digest = hashlib.sha256(subject.encode("utf-8")).hexdigest()
        return f"{client_address.strip() or 'unknown'}:{digest}"

    def retry_after(self, key: str) -> int:
        now = time.monotonic()
        with self._lock:
            attempts = self._prune(key, now)
            if len(attempts) < self.max_attempts:
                return 0
            return max(1, int(self.window_seconds - (now - attempts[0])) + 1)

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            attempts = self._prune(key, now)
            attempts.append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)

    def _prune(self, key: str, now: float) -> deque[float]:
        attempts = self._attempts.setdefault(key, deque())
        cutoff = now - self.window_seconds
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()
        if not attempts:
            self._attempts.pop(key, None)
            return self._attempts.setdefault(key, deque())
        return attempts
