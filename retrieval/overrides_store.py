"""
OverridesStore
- Loads per-tenant overrides from business/{TENANT}/overrides.json
- Provides simple dotted-key get() and type helpers
- Common fields:
  {
    "tone": { "concise": true },
    "flags": { "rewriter_enabled": true, "tool_use_enabled": false, "analytics_to_sheets": false },
    "thresholds": { "intent_confidence": 0.72 }
  }
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Optional

from retrieval.storage import Storage


@dataclass
class OverridesStore:
    storage: Storage

    def __post_init__(self):
        self._data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        try:
            data = self.storage.read_json(self.storage.tenant_key, "overrides.json")
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}

    # -------- public API --------

    def get(self, dotted_key: str, default: Any = None) -> Any:
        """
        Fetch value by dotted path, e.g., 'flags.rewriter_enabled'.
        """
        node: Any = self._data
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def get_bool(self, dotted_key: str, default: bool = False) -> bool:
        v = self.get(dotted_key, default)
        try:
            return bool(v)
        except Exception:
            return default

    def get_float(self, dotted_key: str, default: float = 0.0) -> float:
        v = self.get(dotted_key, default)
        try:
            return float(v)
        except Exception:
            return default

    def get_int(self, dotted_key: str, default: int = 0) -> int:
        v = self.get(dotted_key, default)
        try:
            return int(v)
        except Exception:
            return default

    def raw(self) -> Dict[str, Any]:
        return dict(self._data)
