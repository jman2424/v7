"""
ai_modes package exports.

Factories:
- make_v5()        -> V5Legacy
- make_v6(deps)    -> AIV6Hybrid (defined in v6_hybrid.py)
- make_v7(deps)    -> AIV7Flagship (defined in v7_flagship.py)

Container code can import these to construct the active strategy
based on MODE (V5 / AIV6 / AIV7).
"""

from __future__ import annotations
from typing import Any, Dict

from .contracts import ModeStrategy
from .v5_legacy import V5Legacy


def make_v5() -> ModeStrategy:
    """Pure deterministic mode — no LLM, no tool calls from here."""
    return V5Legacy()


def make_v6(**deps: Dict[str, Any]) -> ModeStrategy:
    """
    Hybrid mode (deterministic + LLM rewrite/clarify).
    Lazily import to avoid import cost if unused.
    Expected deps (optional):
      - prompts (dict) for clarifiers/offers
    """
    from .v6_hybrid import AIV6Hybrid  # type: ignore
    return AIV6Hybrid(**deps)


def make_v7(**deps: Dict[str, Any]) -> ModeStrategy:
    """
    Flagship mode with tool-use planner and strict grounding.
    Expected deps:
      - catalog, policy, geo, faq, crm, overrides (stores/services)
      - guardrails (dict or loader), prompts (dict)
    """
    from .v7_flagship import AIV7Flagship  # type: ignore
    return AIV7Flagship(**deps)
