"""
V5 Legacy Mode — fully deterministic.

Behavior:
- No model/tool calls from this layer.
- Returns the deterministic draft (light polish only).
- planning() returns an empty/no-op plan (for observability).

This aligns with the philosophy: determinism first, AI optional.
"""

from __future__ import annotations
from typing import Any, Dict

from .contracts import ModeStrategy, Plan, safe_minimal_rewrite


class V5Legacy(ModeStrategy):
    def name(self) -> str:
        return "V5"

    # In V5, the router + retrieval already did the heavy lifting.
    # We still return a structural plan for debugging dashboards.
    def plan(self, user_text: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
        # ctx can include: tenant, channel, session, intent/entities (if services pass them through)
        intent = (ctx.get("intent") or "").strip()
        return Plan(
            goal=f"Answer the user's request deterministically (intent='{intent}')",
            tools=[],  # V5 does not plan tool use here; retrieval already happened upstream
            constraints={"no_fabrication": True, "grounding": "deterministic-only"},
        ).to_dict()

    # Rewrite does NOT change facts; it only trims whitespace and capitalizes.
    def rewrite(self, draft: str, ctx: Dict[str, Any]) -> str:
        return safe_minimal_rewrite(draft)
