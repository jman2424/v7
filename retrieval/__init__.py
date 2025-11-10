"""
Retrieval package exports.

Provides:
- Storage: versioned JSON I/O with schema validation and daily snapshots.
- Cache: simple in-proc TTL cache with optional Redis adapter.

Other stores (catalog/policy/geo/faq/synonyms/overrides) live in sibling modules.
"""

from .storage import Storage
from .cache import Cache, InProcCache, RedisCache

__all__ = [
    "Storage",
    "Cache",
    "InProcCache",
    "RedisCache",
]
