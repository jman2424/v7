"""
Feature flags (read-only helpers).

Global defaults come from Settings; per-tenant overrides can live in
business/{KEY}/overrides.json under:

{
  "flags": {
    "rewriter_enabled": true,
    "tool_use_enabled": false,
    "analytics_to_sheets": false
  },
  "thresholds": {
    "intent_confidence": 0.72
  }
}
"""

from __future__ import annotations
from typing import Any

from app.config import Settings
from retrieval.overrides_store import OverridesStore


class Flags:
    def __init__(self, settings: Settings, overrides: OverridesStore):
        self.settings = settings
        self.overrides = overrides

    def rewriter_enabled(self) -> bool:
        o = self.overrides.get("flags.rewriter_enabled")
        return bool(o if o is not None else self.settings.FF_REWRITER_ENABLED)

    def tool_use_enabled(self) -> bool:
        o = self.overrides.get("flags.tool_use_enabled")
        return bool(o if o is not None else self.settings.FF_TOOL_USE_ENABLED)

    def analytics_to_sheets(self) -> bool:
        o = self.overrides.get("flags.analytics_to_sheets")
        return bool(o if o is not None else self.settings.FF_ANALYTICS_TO_SHEETS)

    def intent_conf_threshold(self, default: float = 0.7) -> float:
        v = self.overrides.get("thresholds.intent_confidence")
        try:
            return float(v) if v is not None else default
        except Exception:
            return default
