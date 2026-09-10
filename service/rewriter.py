from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Set

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore


_WS = re.compile(r"\s+")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")

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
    "address:",
    "phone:",
)

_RE_UK_POSTCODE = re.compile(r"\b([A-Z]{1,2}\d{1,2}[A-Z]?)\s*(\d[A-Z]{2})\b", re.I)
_RE_PHONE = re.compile(r"\b(?:\+?\d[\d\s\-()]{7,}\d)\b")
_RE_PRICE = re.compile(r"(?:£\s?\d+(?:\.\d{1,2})?)", re.I)

# Very rough branch/address guards
_RE_BRANCH_LINE = re.compile(r"\b(branch|store)\b", re.I)
_RE_ADDRESS_HINT = re.compile(
    r"\b(road|rd|street|st|avenue|ave|lane|ln|close|crescent|drive|dr|way|broadway|high road|high street)\b",
    re.I,
)


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except Exception:
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except Exception:
        return default


def _clean(text: str) -> str:
    t = (text or "").replace("\x00", " ").strip()
    return _WS.sub(" ", t)


def _limit_sentences(text: str, n: int = 2) -> str:
    parts = [p.strip() for p in _SENT_SPLIT.split(text or "") if p.strip()]
    return " ".join(parts[:n]).strip()


def _should_add_cta(line: str) -> bool:
    if not line:
        return False

    low = line.lower().strip()

    if line.endswith("?"):
        return False

    if any(h in low for h in _NO_CTA_HINTS):
        return False

    if any(
        low.endswith(suf)
        for suf in (
            "anything else?",
            "anything else.",
            "want to look at anything else?",
            "anything else i can help you with?",
            "more options.",
            "more options",
        )
    ):
        return False

    # Keep short direct answers self-contained.
    if len(low) < 60:
        return False

    return True


def _cta(line: str) -> str:
    return f"{line} Anything else you’d like to check?"


def _norm_price_token(x: str) -> str:
    return (x or "").replace(" ", "").strip().lower()


def _norm_phone_token(x: str) -> str:
    return re.sub(r"\s+", "", (x or "").strip())


def _norm_pc_token(a: str, b: str) -> str:
    return f"{(a or '').upper()} {(b or '').upper()}".strip()


def _extract_guard_tokens(text: str) -> Set[str]:
    """
    Extract sensitive tokens from the original draft.
    Rewrites are only allowed to keep these, not invent new ones.
    """
    t = text or ""
    tokens: Set[str] = set()

    for m in _RE_PRICE.findall(t):
        tokens.add(f"PRICE::{_norm_price_token(m)}")

    for m in _RE_PHONE.findall(t):
        tokens.add(f"PHONE::{_norm_phone_token(m)}")

    for m in _RE_UK_POSTCODE.finditer(t):
        tokens.add(f"PC::{_norm_pc_token(m.group(1), m.group(2))}")

    # Coarse branch/address markers
    if _RE_BRANCH_LINE.search(t):
        tokens.add("__HAS_BRANCH_MARKER__")
    if _RE_ADDRESS_HINT.search(t):
        tokens.add("__HAS_ADDRESS_MARKER__")

    return tokens


def _rewrite_is_safe(original: str, rewritten: str) -> bool:
    allow = _extract_guard_tokens(original)
    rew = _extract_guard_tokens(rewritten)

    # Marker rules
    if "__HAS_BRANCH_MARKER__" not in allow and "__HAS_BRANCH_MARKER__" in rew:
        return False
    if "__HAS_ADDRESS_MARKER__" not in allow and "__HAS_ADDRESS_MARKER__" in rew:
        return False

    allow = {x for x in allow if not x.startswith("__HAS_")}
    rew = {x for x in rew if not x.startswith("__HAS_")}

    # If original had no guarded tokens, rewritten must not invent any
    if not allow:
        return len(rew) == 0

    return rew.issubset(allow)


@dataclass
class Rewriter:
    """
    Optional AI-backed rewriter with strict safety checks.

    Env supported:
    - OPENAI_API_KEY
    - OPENAI_MODEL
    - OPENAI_TEMPERATURE
    - OPENAI_TIMEOUT
    """
    concise: bool = True
    max_chars: int = 700

    def __post_init__(self) -> None:
        self._client = None
        self._model = os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
        self._temperature = _env_float("OPENAI_TEMPERATURE", 0.2)
        self._timeout = _env_int("OPENAI_TIMEOUT", 30)

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

        # Safe deterministic mode only
        if style == "safe":
            out = self._normalize_phrasing(original)
            if self.concise:
                out = _limit_sentences(out, 3)
            return out[: self.max_chars].strip()

        # Try AI rewrite first
        ai = self._rewrite_ai(original, style=style, facts=facts)
        if ai:
            ai = _clean(ai)
            ai = ai[: self.max_chars].strip()

            if self.concise:
                ai = _limit_sentences(ai, 2)

            ai = self._normalize_phrasing(ai)

            if len(ai) <= 320 and _should_add_cta(ai):
                ai = _cta(ai)

            if _rewrite_is_safe(original, ai):
                return ai

        # Deterministic fallback
        out = self._normalize_phrasing(original)
        out = out[: self.max_chars].strip()

        if self.concise:
            out = _limit_sentences(out, 2)

        if len(out) <= 320 and _should_add_cta(out):
            out = _cta(out)

        return out

    def _rewrite_ai(
        self,
        text: str,
        *,
        style: str,
        facts: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        if not self._client:
            return None

        facts_str = ""
        try:
            if isinstance(facts, dict) and facts:
                # Keep compact to reduce token waste
                facts_str = json.dumps(facts, ensure_ascii=False)[:1800]
        except Exception:
            facts_str = ""

        system = (
            "You rewrite grounded messages for a business sales assistant.\n"
            "STRICT RULES:\n"
            "- Rewrite only.\n"
            "- Do NOT add any new facts.\n"
            "- Do NOT add or change prices, postcodes, phone numbers, branch names, or addresses.\n"
            "- Do NOT add products not already present in the draft.\n"
            "- Do NOT imply a particular industry, brand, product type, certification, or policy.\n"
            "- Keep the message natural, short, and clear.\n"
            "- Avoid sounding pushy or overly salesy.\n"
            "- Preserve the meaning exactly.\n"
        )

        user = (
            f"Style: {style}\n"
            "Rewrite this message to sound cleaner and more natural, without adding information.\n\n"
            f"DRAFT:\n{text}\n\n"
        )

        if facts_str:
            user += f"FACTS (grounding only, do not expand beyond them):\n{facts_str}\n"

        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                temperature=min(self._temperature, 0.3),
                timeout=self._timeout,
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
        s = (s or "").strip()
        if not s:
            return ""

        # normalize apostrophes
        s = s.replace("’", "'")

        # light contraction cleanup
        s = re.sub(r"\bdon't\b", "do not", s, flags=re.I)
        s = re.sub(r"\bcan't\b", "cannot", s, flags=re.I)

        # remove filler
        s = re.sub(r"\b(just|basically|kind of|sort of)\b", "", s, flags=re.I)

        # tidy spaces
        s = re.sub(r"\s{2,}", " ", s).strip()

        # clean awkward spacing around punctuation
        s = re.sub(r"\s+([,.;:!?])", r"\1", s)
        # Do not insert spaces after periods: that would corrupt email addresses
        # and website domains in grounded business contact details.
        s = re.sub(r"([,;:!?])([A-Za-z])", r"\1 \2", s)

        # capitalization
        if s and not s[0].isupper():
            s = s[0].upper() + s[1:]

        return s
