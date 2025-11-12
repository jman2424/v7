"""
Ephemeral session memory with TTL.

Stores:
- user_name
- postcode
- nearest_branch_id
- cart (opaque dict/list)
- last_category
- last_sku
- channel

Notes:
- In-proc only. For multi-instance, back with Redis by swapping _Store.
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class _Entry:
    value: Any
    exp: float


@dataclass
class _Store:
    data: Dict[str, Dict[str, _Entry]] = field(default_factory=dict)

    def get(self, sid: str, key: str) -> Any:
        bucket = self.data.get(sid)
        if not bucket:
            return None
        e = bucket.get(key)
        if not e:
            return None
        if e.exp and e.exp < time.time():
            bucket.pop(key, None)
            return None
        return e.value

    def set(self, sid: str, key: str, value: Any, ttl: Optional[int]) -> None:
        bucket = self.data.setdefault(sid, {})
        exp = time.time() + ttl if ttl else 0
        bucket[key] = _Entry(value=value, exp=exp)

    def clear(self, sid: str) -> None:
        self.data.pop(sid, None)


@dataclass
class Memory:
    store: _Store = field(default_factory=_Store)

    def get(self, session_id: str, key: str, default=None):
        v = self.store.get(session_id, key)
        return default if v is None else v

    def set(self, session_id: str, key: str, value: Any, ttl: Optional[int] = None) -> None:
        self.store.set(session_id, key, value, ttl)

    def clear(self, session_id: str) -> None:
        self.store.clear(session_id)
