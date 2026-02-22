"""
Tone-controlled NLG rewriter.

- Never invent facts (rewrites only).
- Safe fallback: deterministic cleanups only (no AI calls).
"""

from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Optional

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WS = re.compile(r"\s+")

# If these topics are present, avoid adding CTA automatically
_NO_CTA_HINTS = (
    "postcode",
    "delivery",
    "deliver",
    "nearest branch",
    "closest branch",
    "nearest store",
    "closest store",
    "call the store",
)


def _clean(text: str) -> str:
    text = (text or "").replace("\x00", " ").strip()
    return _WS.sub(" ", text)


def _limit_sentences(text: str, n: int = 2) -> str:
    parts = _SENT_SPLIT.split(text)
    return " ".join(parts[:n]).strip()


def _should_add_cta(line: str) -> bool:
    if not line or line.endswith("?"):
        return False
    low = line.lower()
    if any(h in low for h in _NO_CTA_HINTS):
        return False
    if any(low.endswith(suf) for suf in ("more options.", "more options", "anything else.")):
        return False
    return True


def _cta(line: str) -> str:
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
            return _limit_sentences(t, 3) if self.concise else t

        # "sales" default:
        t = self._normalize_phrasing(t)
        t = _limit_sentences(t, 2) if self.concise else t
        if len(t) <= 300 and _should_add_cta(t):
            t = _cta(t)
        return t

    def _normalize_phrasing(self, s: str) -> str:
        # normalize apostrophes
        s = s.replace("’", "'")

        # minimal contraction expansion
        s = s.replace("don't", "do not").replace("can't", "cannot")

        # Remove filler
        s = re.sub(r"\b(just|basically|kind of|sort of)\b", "", s, flags=re.I)
        s = re.sub(r"\s{2,}", " ", s).strip()

        # Capitalization pass
        if s and not s[0].isupper():
            s = s[0].upper() + s[1:]
        return s
