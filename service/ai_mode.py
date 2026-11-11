"""The response strategy a tenant runs: ``v5``, ``v6`` or ``v7`` (default).

The only source of truth is ``overrides.json`` -> ``ai.mode`` for that tenant,
written by ``POST /admin/api/mode``. The historical ``MODE`` environment
variable no longer selects anything.
"""
from __future__ import annotations

from typing import Any

DEFAULT_MODE = "v7"
_LEGACY = {"v5", "v6"}


def normalise(value: Any) -> str:
    mode = str(value or "").strip().lower()
    return mode if mode in _LEGACY else DEFAULT_MODE


def tenant_mode(overrides: Any) -> str:
    """Accept an OverridesStore or a raw overrides.json document."""
    if hasattr(overrides, "get") and not isinstance(overrides, dict):
        return normalise(overrides.get("ai.mode"))
    ai = overrides.get("ai") if isinstance(overrides, dict) else None
    return normalise(ai.get("mode") if isinstance(ai, dict) else None)
