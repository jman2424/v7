# service/rewriter.py
"""
Tone-controlled NLG rewriter.

Goals:
- Rewrite ONLY (no new facts).
- If OpenAI is not configured or fails, fall back to deterministic cleanups.
- Must NOT invent or add products/prices/postcodes/phones that aren't already present.

Notes:
- This module is dependency-light. If OpenAI SDK isn't installed, it still works.
- Safety: any rewrite introducing NEW price/phone/postcode/branch/address tokens is rejected.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Set

try:
    # OpenAI SDK v1.x
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore


_WS = re.compile(r"\s+")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")

# Avoid CTA when these are present (store ops / delivery / contact usually ends with next step already)
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

# Guard patterns (do not allow introducing NEW versions not in the input)
_RE_UK_POSTCODE = re.compile(r"\b([A-Z]{1,2}\d{1,2}[A-Z]?)\s*(\d[A-Z]{2})\b", re.I)
_RE_PHONE = re.compile(r"\b(?:\+?\d[\d\s\-()]{7,}\d)\b")
_RE_PRICE = re.compile(r"(?:£\s?\d+(?:\.\d{1,2})?)", re.I)

# Extra grounding tokens to prevent “helpful” invention
_RE_BRANCH_LABEL = re.compile(r"\b(nearest branch|branch:|store:)\b", re.I)
_RE_ADDRESS_HINT = re.compile(r"\b(road|rd|street|st|avenue|ave|lane|ln|close|crescent|cr)\b", re.I)


def _clean(text: str) -> str:
    t = (text or "").replace("\x00", " ").strip()
    return _WS.sub(" ", t)


def _limit_sentences(text: str, n: int = 2) -> str:
    parts = [p.strip() for p in _SENT_SPLIT.split(text or "") if p.strip()]
    return " ".join(parts[:n]).strip()


def _should_add_cta(line: str) -> bool:
    if not line:
        return False
    if line.endswith("?"):
        return False
    low = line.lower()
    if any(h in low for h in _NO_CTA_HINTS):
        return False
    # avoid double-CTAs
    if any(low.endswith(suf) for suf in ("more options.", "more options", "anything else.", "anything else?")):
        return False
    return True


def _cta(line: str) -> str:
    return f"{line} Anything else you’d like to check?"


def _norm_money_token(m: str) -> str:
    return (m or "").replace(" ", "").strip()


def _norm_phone_token(p: str) -> str:
    return re.sub(r"\s+", "", (p or "").strip())


def _norm_pc_token(a: str, b: str) -> str:
    return f"{(a or '').upper()} {(b or '').upper()}".strip()


def _extract_guard_tokens(text: str) -> Set[str]:
    """
    Extract “sensitive” tokens from original draft that rewrites are allowed to contain.
    If rewritten introduces NEW tokens, we reject it.

    Includes:
    - Prices (£x.xx)
    - Phones
    - Postcodes
    - Branch/address markers (coarse, but helps prevent adding new branch lines)
    """
    t = text or ""
    tokens: Set[str] = set()

    # prices
    for m in _RE_PRICE.findall(t):
        tokens.add(_norm_money_token(m))

    # phones
    for m in _RE_PHONE.findall(t):
        tokens.add(_norm_phone_token(m))

    # postcodes
    for m in _RE_UK_POSTCODE.finditer(t):
        tokens.add(_norm_pc_token(m.group(1), m.group(2)))

    # coarse location hints (optional): if original has branch/address markers,
    # rewritten is not allowed to add new ones.
    if _RE_BRANCH_LABEL.search(t):
        tokens.add("__HAS_BRANCH_LABEL__")
    if _RE_ADDRESS_HINT.search(t):
        tokens.add("__HAS_ADDRESS_HINT__")

    return tokens


def _rewrite_is_safe(original: str, rewritten: str) -> bool:
    """
    Safety rules:
    - rewritten may reorder/shorten, but must not introduce NEW prices/postcodes/phones.
    - if original has no prices/phones/postcodes, rewritten must not add any.
    - if original has no branch/address markers, rewritten must not introduce them.
    """
    allow = _extract_guard_tokens(original)
    rew = _extract_guard_tokens(rewritten)

    # If original has none of the sensitive tokens, rewritten must have none
    if not allow:
        has_new = bool(_RE_PRICE.search(rewritten) or _RE_PHONE.search(rewritten) or _RE_UK_POSTCODE.search(rewritten))
        # also block new branch/address markers
        has_branchish = bool(_RE_BRANCH_LABEL.search(rewritten) or _RE_ADDRESS_HINT.search(rewritten))
        return not (has_new or has_branchish)

    # Normalize for comparison
    norm_allow = set(x.replace(" ", "") for x in allow)
    norm_rew = set(x.replace(" ", "") for x in rew)

    # Special marker checks
    if "__HAS_BRANCH_LABEL__" not in allow and "__HAS_BRANCH_LABEL__" in rew:
        return False
    if "__HAS_ADDRESS_HINT__" not in allow and "__HAS_ADDRESS_HINT__" in rew:
        return False

    # For the rest, subset check
    norm_allow.discard("__HAS_BRANCH_LABEL__")
    norm_allow.discard("__HAS_ADDRESS_HINT__")
    norm_rew.discard("__HAS_BRANCH_LABEL__")
    norm_rew.discard("__HAS_ADDRESS_HINT__")

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
    max_chars: int = 800  # hard cap to keep outputs sane

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

        # deterministic safe mode
        if style == "safe":
            out = _limit_sentences(original, 3) if self.concise else original
            return out[: self.max_chars].strip()

        # AI attempt (if configured)
        ai = self._rewrite_ai(original, style=style, facts=facts)
        if ai:
            ai = _clean(ai)
            ai = ai[: self.max_chars].strip()

            if self.concise:
                ai = _limit_sentences(ai, 2)

            if len(ai) <= 320 and _should_add_cta(ai):
                ai = _cta(ai)

            if _rewrite_is_safe(original, ai):
                return ai

        # fallback deterministic rewrite
        out = self._normalize_phrasing(original)
        out = out[: self.max_chars].strip()

        if self.concise:
            out = _limit_sentences(out, 2)

        if len(out) <= 320 and _should_add_cta(out):
            out = _cta(out)

        return out

    def _rewrite_ai(self, text: str, *, style: str, facts: Optional[Dict[str, Any]]) -> Optional[str]:
        if not self._client:
            return None

        model = os.getenv("OPENAI_MODEL") or "gpt-4.1-mini"

        # Keep facts compact; grounding only
        facts_str = ""
        try:
            if isinstance(facts, dict) and facts:
                facts_str = json.dumps(facts, ensure_ascii=False)[:1800]
        except Exception:
            facts_str = ""

        system = (
            "You rewrite assistant messages for a halal butcher shop chatbot.\n"
            "STRICT RULES:\n"
            "- Rewrite only; DO NOT add new facts.\n"
            "- Do NOT add or change prices, phone numbers, postcodes, branch names, addresses.\n"
            "- Do NOT add products that are not already in the draft.\n"
            "- Do NOT add new calls-to-action unless the draft already implies it.\n"
            "- Keep it clear, short, and friendly.\n"
        )

        user = (
            f"Style: {style}\n"
            "Rewrite this message with better tone and clarity, without adding any new information.\n\n"
            f"DRAFT:\n{text}\n\n"
        )
        if facts_str:
            user += f"FACTS (grounding only):\n{facts_str}\n"

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

        # remove filler
        s = re.sub(r"\b(just|basically|kind of|sort of)\b", "", s, flags=re.I)
        s = re.sub(r"\s{2,}", " ", s).strip()

        # capitalization pass
        if s and not s[0].isupper():
            s = s[0].upper() + s[1:]
        return s
        
