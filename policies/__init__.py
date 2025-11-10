"""
Policy loaders and accessors.

Exposes read-only access to:
- Tone/style rules (style.md)
- Guardrails (guardrails.md)
- Prompt templates (clarifiers.md, offers.md, errors.md)

Contracts:
- get_style() -> str
- get_guardrails() -> str
- get_prompts() -> dict[str, str]    # {"clarifiers": "...", "offers": "...", "errors": "..."}

Usage:
from policies import get_style, get_guardrails, get_prompts
style_md = get_style()
prompts = get_prompts()
"""

from __future__ import annotations
from pathlib import Path
from typing import Dict

_BASE = Path(__file__).resolve().parent

def _read_text(relpath: str) -> str:
    p = _BASE / relpath
    return p.read_text(encoding="utf-8")

def get_style() -> str:
    """Return the raw markdown content of style.md."""
    return _read_text("style.md")

def get_guardrails() -> str:
    """Return the raw markdown content of guardrails.md."""
    return _read_text("guardrails.md")

def get_prompts() -> Dict[str, str]:
    """
    Return raw markdown contents for prompt packs.
    Keys: clarifiers, offers, errors
    """
    return {
        "clarifiers": _read_text("prompts/clarifiers.md"),
        "offers": _read_text("prompts/offers.md"),
        "errors": _read_text("prompts/errors.md"),
    }
