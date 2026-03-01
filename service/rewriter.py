# service/rewriter.py
"""
Tone-controlled NLG rewriter.

Goals:
- Rewrite ONLY (no new facts).
- If OpenAI is not configured or fails, fall back to deterministic cleanups.
- Must NOT invent or add products/prices/postcodes/phones that aren't already present.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

try:
    # OpenAI SDK v1.x
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore


_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WS = re.compile(r"\s+")

# Avoid adding CTA automatically when these are present
_NO_CTA_HINTS = (
    "postcode",
    "delivery",
    "deliver",
    "nearest branch",
    "closest branch",
    "nearest store",
    "closest store",
    "call:",
    "call the store",
)

# Guard patterns (do not allow adding new versions not in input)
_RE_UK_POSTCODE = re.compile(r"\b([A-Z]{1,2}\d{1,2}[A-Z]?)\s*(\d[A-Z]{2})\b", re.I)
_RE_PHONE = re.compile(r"\b(?:\+?\d[\d\s\-()]{7,}\d)\b")
_RE_PRICE = re.compile(r"(?:£\s?\d+(?:\.\d{1,2})?)")


def _clean(text: str) -> str:
    text = (text or "").replace("\x00", " ").strip()
    return _WS.sub(" ", text)


def _limit_sentences(text: str, n: int = 2) -> str:
    parts = _SENT_SPLIT.split(text)
    return " ".join([p.strip() for p in parts[:n] if p.strip()]).strip()


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


def _extract_guard_tokens(text: str) -> set[str]:
    """
    Extract sensitive tokens from the original draft that the rewrite is allowed to contain.
    If rewrite introduces NEW tokens (prices/postcodes/phones), we reject it.
    """
    t = text or ""
    tokens: set[str] = set()

    for m in _RE_PRICE.findall(t):
        tokens.add(m.replace(" ", ""))

    for m in _RE_PHONE.findall(t):
        tokens.add(re.sub(r"\s+", "", m))

    for m in _RE_UK_POSTCODE.finditer(t):
        tokens.add(f"{m.group(1).upper()} {m.group(2).upper()}")

    return tokens


def _rewrite_is_safe(original: str, rewritten: str) -> bool:
    """
    Safety rule:
    - rewritten may re-order / shorten, but must not introduce NEW prices/postcodes/phones.
    """
    allow = _extract_guard_tokens(original)
    if not allow:
        # If original has none of these, rewrite must not add any of these either.
        has_new_price = bool(_RE_PRICE.search(rewritten))
        has_new_phone = bool(_RE_PHONE.search(rewritten))
        has_new_pc = bool(_RE_UK_POSTCODE.search(rewritten))
        return not (has_new_price or has_new_phone or has_new_pc)

    # Check any sensitive tokens in rewritten are a subset of allowed ones
    rewritten_tokens = _extract_guard_tokens(rewritten)

    # normalize formatting for comparison
    norm_allow = set(x.replace(" ", "") for x in allow)
    norm_rew = set(x.replace(" ", "") for x in rewritten_tokens)

    return norm_rew.issubset(norm_allow)


@dataclass
class Rewriter:
    """
    If OPENAI_API_KEY is present and OpenAI is installed, we do a real rewrite.
    Otherwise: deterministic cleanup only.

    Env:
      OPENAI_API_KEY
      OPENAI_MODEL (optional) default: "gpt-4.1-mini"
    """
    concise: bool = True

    def __post_init__(self) -> None:
        self._client = None
        if OpenAI is None:
            return

        api_key = os.getenv("OPENAI_API_KEY") or ""
        if not api_key.strip():
            return

        try:
            self._client = OpenAI(api_key=api_key)
        except Exception:
            self._client = None

    def rewrite(
        self,
        text: str,
        *,
        style: Optional[str] = None,
        facts: Optional[Dict[str, Any]] = None,
    ) -> str:
        style = (style or "sales").lower()
        original = _clean(text)
        if not original:
            return ""

        # Deterministic modes
        if style == "safe":
            out = _limit_sentences(original, 3) if self.concise else original
            return out

        # Try AI rewrite first (if configured), then validate with safety guards
        ai = self._rewrite_ai(original, style=style, facts=facts)
        if ai:
            ai = _clean(ai)
            if self.concise:
                ai = _limit_sentences(ai, 2)
            # optional CTA, but only if safe to add
            if len(ai) <= 320 and _should_add_cta(ai):
                ai = _cta(ai)

            # Guard: no new postcodes/prices/phones
            if _rewrite_is_safe(original, ai):
                return ai

        # fallback deterministic rewrite
        out = self._normalize_phrasing(original)
        out = _limit_sentences(out, 2) if self.concise else out
        if len(out) <= 320 and _should_add_cta(out):
            out = _cta(out)
        return out

    def _rewrite_ai(self, text: str, *, style: str, facts: Optional[Dict[str, Any]]) -> Optional[str]:
        if not self._client:
            return None

        model = os.getenv("OPENAI_MODEL") or "gpt-4.1-mini"

        # Keep facts compact; they are for grounding, not for invention
        facts_str = ""
        try:
            if isinstance(facts, dict) and facts:
                facts_str = json.dumps(facts, ensure_ascii=False)[:2000]
        except Exception:
            facts_str = ""

        system = (
            "You rewrite assistant messages for a halal butcher shop chatbot.\n"
            "STRICT RULES:\n"
            "- Rewrite only; DO NOT add new facts.\n"
            "- Do NOT add or change prices, phone numbers, postcodes, branch names, addresses.\n"
            "- Do NOT add products that are not already in the draft.\n"
            "- Keep it clear, short, and friendly.\n"
        )

        user = (
            "Rewrite this message with better tone and clarity, without adding any new information.\n\n"
            f"DRAFT:\n{text}\n\n"
        )
        if facts_str:
            user += f"FACTS (for grounding only, never invent):\n{facts_str}\n"

        try:
            resp = self._client.chat.completions.create(
                model=model,
                temperature=0.2,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            content = (resp.choices[0].message.content or "").strip()
            return content or None
        except Exception:
            return None

    def _normalize_phrasing(self, s: str) -> str:
        # normalize apostrophes
        s = s.replace("’", "'")

        # minimal contraction expansion
        s = re.sub(r"\bdon't\b", "do not", s, flags=re.I)
        s = re.sub(r"\bcan't\b", "cannot", s, flags=re.I)

        # Remove filler
        s = re.sub(r"\b(just|basically|kind of|sort of)\b", "", s, flags=re.I)
        s = re.sub(r"\s{2,}", " ", s).strip()

        # Capitalization pass
        if s and not s[0].isupper():
            s = s[0].upper() + s[1:]
        return s remake this file aswell    
