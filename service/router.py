"""
Router: intent detection, entity extraction, clarifiers, and deterministic fallbacks.

Intents:
- check_delivery (needs postcode if missing)
- search_product (free text / tags)
- browse_category (category-only)
- price_check (explicit SKU)
- faq (generic question matched later)
- unknown

Entities:
- postcode (UK-ish normalization)
- sku
- category
- tags (canonical via synonyms store)
- phone (optional)
"""

from __future__ import annotations
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d{1,2}[A-Z]?)\s?(\d[A-Z]{2})\b", re.I)
SKU_RE = re.compile(r"\b([A-Z0-9_]{3,})\b")
PHONE_RE = re.compile(r"\+?\d{7,15}")

STOPWORDS = set("""
a an the i we you to for and or of with on at in near around show find tell need want
""".split())

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())

def _tokens(s: str) -> List[str]:
    return [t for t in re.findall(r"[a-z0-9'_]+", _norm(s)) if t not in STOPWORDS]

@dataclass
class Router:
    synonyms: Any  # SynonymsStoreLike
    geo_prefixes: List[str]  # cached coverage prefixes (e.g., ["E1","E2"])

    def route(self, text: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
        t0 = time.time()
        text = text or ""
        norm = _norm(text)
        toks = _tokens(text)

        entities: Dict[str, Any] = {}
        utterance = text

        # Extract entities
        pc = self._extract_postcode(norm)
        if pc:
            entities["postcode"] = pc

        phone = self._extract_phone(norm)
        if phone:
            entities["phone"] = phone

        sku = self._extract_sku(text)
        if sku:
            entities["sku"] = sku

        # Canonical tags via synonyms
        tags = self._guess_tags(toks)
        if tags:
            entities["tags"] = tags

        # Category guess (first canonical tag if plausible)
        if tags:
            entities["category"] = tags[0]

        # Intent heuristics
        intent = self._infer_intent(norm, toks, entities)

        # Clarifiers
        needs_clarification, clarifier = self._maybe_clarify(intent, entities, ctx)

        return {
            "intent": intent,
            "entities": entities,
            "needs_clarification": needs_clarification,
            "clarifier": clarifier,
            "utterance": utterance,
            "_latency_ms": int((time.time() - t0) * 1000),
        }

    # ---- extractors ----

    def _extract_postcode(self, norm: str) -> Optional[str]:
        m = POSTCODE_RE.search(norm.upper())
        if not m:
            # Accept outward prefixes if match coverage (E1, E2, SW11, etc.)
            m2 = re.search(r"\b([A-Z]{1,2}\d{1,2}[A-Z]?)\b", norm.upper())
            if m2:
                return m2.group(1)
            return None
        return f"{m.group(1)} {m.group(2)}".strip()

    def _extract_sku(self, text: str) -> Optional[str]:
        # SKU uppercase with underscores or digits; avoid false positives by checking length
        cands = [m.group(1) for m in SKU_RE.finditer(text.upper())]
        for c in cands:
            if len(c) >= 4 and any(ch.isdigit() for ch in c):
                return c
        return None

    def _extract_phone(self, norm: str) -> Optional[str]:
        m = PHONE_RE.search(norm)
        return m.group(0) if m else None

    def _guess_tags(self, toks: List[str]) -> List[str]:
        # map each token to canonical, drop duplicates
        canon = [self.synonyms.canonical(t) for t in toks]
        seen, out = set(), []
        for c in canon:
            if c and c not in seen:
                seen.add(c)
                out.append(c)
        return out[:5]

    # ---- intent ----

    def _infer_intent(self, norm: str, toks: List[str], ent: Dict[str, Any]) -> str:
        if any(k in norm for k in ["deliver", "delivery", "ship", "postcode", "post code"]):
            return "check_delivery"
        if "price" in toks or "cost" in toks or "how much" in norm:
            if ent.get("sku"):
                return "price_check"
            return "search_product"
        if any(k in toks for k in ["open", "hours", "time", "when"]):
            return "faq"
        if ent.get("sku"):
            return "price_check"
        if ent.get("tags"):
            return "search_product"
        # generic question?
        if norm.endswith("?") or any(k in toks for k in ["do", "can", "is", "are"]):
            return "faq"
        return "unknown"

    # ---- clarifiers ----

    def _maybe_clarify(self, intent: str, ent: Dict[str, Any], ctx: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        if intent == "check_delivery":
            pc = ent.get("postcode") or ctx.get("session", {}).get("postcode")
            if not pc:
                # nudge toward coverage prefixes if available
                pref = ctx.get("coverage_prefixes") or []
                hint = f" (e.g., {'/'.join(pref[:3])})" if pref else ""
                return True, f"What's your postcode{hint}?"
        if intent == "search_product" and not (ent.get("tags") or ent.get("category")):
            return True, "Which product or category are you after?"
        if intent == "price_check" and not ent.get("sku"):
            return True, "Which SKU should I price-check?"
        return False, None
