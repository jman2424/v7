"""
Contracts & data classes for AI modes.

The services layer only needs ModeStrategy(name/plan/rewrite), but richer
planning data structures are provided for V7.

Keep this file dependency-light (stdlib only) to avoid circular imports.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol


# ---- Public protocol used by services.message_handler ----

class ModeStrategy(Protocol):
    def name(self) -> str: ...
    def plan(self, user_text: str, ctx: Dict[str, Any]) -> Dict[str, Any]: ...
    def rewrite(self, draft: str, ctx: Dict[str, Any]) -> str: ...


# ---- Optional richer structures for AIV7 ----

@dataclass
class ToolCall:
    """A single tool call the planner wants to execute."""
    name: str                        # e.g., "catalog.search", "geo.nearest"
    args: Dict[str, Any] = field(default_factory=dict)
    required: bool = True            # if True and it fails → fallback/clarify


@dataclass
class Plan:
    """
    High-level plan for producing a reply:
      - tools: ordered tool calls to gather/verify facts
      - constraints: grounding rules and guardrails
      - goal: short description of the user's need
    """
    goal: str
    tools: List[ToolCall] = field(default_factory=list)
    constraints: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "tools": [dict(name=t.name, args=t.args, required=t.required) for t in self.tools],
            "constraints": dict(self.constraints),
        }


# ---- Common helper: minimal, safe rewrite policy (non-AI) ----

def safe_minimal_rewrite(text: str) -> str:
    """
    A compact normalization pass used by V5 or as fallback by other modes.
    - Trim whitespace
    - Collapse multiple spaces
    - Ensure first letter capitalized
    - Keep punctuation as-is (no hallucinations)
    """
    import re

    t = (text or "").strip()
    t = re.sub(r"\s+", " ", t)
    if not t:
        return ""
    if not t[0].isupper():
        t = t[0].upper() + t[1:]
    return t
