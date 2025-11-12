"""
Tone-controlled NLG rewriter.

Design:
- Never invent facts. Input must already be grounded (deterministic or retrieved).
- Applies concise, sales-focused tone rules (policies/style.md).
- Safe fallback: deterministic cleanups only (no AI calls here).
- If you later wire an LLM, do it in ai_modes/v6_hybrid.py or v7_flagship.py
  and still pass through this rewriter for final polish.

API:
    Rewriter().rewrite("draft text", style="sales")

Styles:
- "sales": concise + CTA if appropriate
- "safe": minimal edits, preserve wording
"""

from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Optional

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WS = re.compile(r"\s+")


def _clean(text: str) -> str:
    text = (text or "").replace("\x00", " ").strip()
    text = _WS.sub(" ", text)
    return text


def _limit_sentences(text: str, n: int = 2) -> str:
    parts = _SENT_SPLIT.split(text)
    return " ".join(parts[:n]).strip()


def _cta(line: str) -> str:
    # Add a restrained CTA if not a question and not already ending with CTA.
    if line.endswith("?"):
        return line
    if any(line.lower().endswith(suf) for suf in ("more options.", "more options", "anything else.")):
        return line
    return f"{line} Anything else you’d like to check?"


@dataclass
class Rewriter:
    concise: bool = True

    def rewrite(self, text: str, *, style: Optional[str] = None) -> str:
        style = (style or "sales").lower()
        t = _clean(text)
        if not t:
            return ""

        if style == "safe":
            # Only normalize whitespace and mild trims.
            return _limit_sentences(t, 3) if self.concise else t

        # "sales" default:
        t = self._normalize_phrasing(t)
        t = _limit_sentences(t, 2) if self.concise else t
        if len(t) <= 300:
            t = _cta(t)
        return t

    # ---- internal ----

    def _normalize_phrasing(self, s: str) -> str:
        # Replace negative contractions minimally and avoid fluff
        s = s.replace("don’t", "do not").replace("can't", "cannot")
        # Remove filler
        s = re.sub(r"\b(just|basically|kind of|sort of)\b", "", s, flags=re.I)
        s = re.sub(r"\s{2,}", " ", s).strip()
        # Capitalization pass
        if s and not s[0].isupper():
            s = s[0].upper() + s[1:]
        return s
