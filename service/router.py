from __future__ import annotations
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

# Full UK postcode (simplified but strong enough for your use)
POSTCODE_FULL_RE = re.compile(r"\b([A-Z]{1,2}\d{1,2}[A-Z]?)\s*(\d[A-Z]{2})\b", re.I)

# Outward only: E7, E1, SW11, etc.
POSTCODE_OUTWARD_RE = re.compile(r"\b([A-Z]{1,2}\d{1,2}[A-Z]?)\b", re.I)

SKU_RE = re.compile(r"\b([A-Z0-9_]{3,})\b")
PHONE_RE = re.compile(r"\+?\d{7,15}")

STOPWORDS = set("""
a an the i we you to for and or of with on at in near around show find tell need want
""".split())


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _tokens(s: str) -> List[str]:
    return [t for t in re.findall(r"[a-z0-9'_]+", _norm(s)) if t not in STOPWORDS]


def _only_alnum(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", s or "")


@dataclass
class Router:
    synonyms: Any = None
    geo_prefixes: Optional[List[str]] = None

    def route(self, text: str, ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        t0 = time.time()
        text = text or ""
        ctx = ctx or {}
        norm = _norm(text)
        toks = _tokens(text)

        entities: Dict[str, Any] = {}
        utterance = text

        # ---- Extract postcode (robust) ----
        pc_norm, pc_is_full, pc_is_outward, pc_needs_space_fix = self._extract_postcode(text)
        if pc_norm:
            entities["postcode_normalized"] = pc_norm
            entities["postcode_is_full"] = pc_is_full
            entities["postcode_is_outward"] = pc_is_outward
            entities["postcode_needs_space_fix"] = pc_needs_space_fix

            # Backwards-compat: if your other code expects "postcode"
            entities["postcode"] = pc_norm

        # ---- Other entities ----
        phone = self._extract_phone(norm)
        if phone:
            entities["phone"] = phone

        sku = self._extract_sku(text)
        if sku:
            entities["sku"] = sku

        # ---- Canonical tags via synonyms ----
        tags = self._guess_tags(toks)
        if tags:
            entities["tags"] = tags
            entities["category"] = tags[0]

        # ---- Intent ----
        intent = self._infer_intent(norm, toks, entities)

        # ---- Clarifiers ----
        needs_clarification, clarifier = self._maybe_clarify(intent, entities, ctx)

        return {
            "intent": intent,
            "entities": entities,
            "needs_clarification": needs_clarification,
            "need_clarification": needs_clarification,
            "clarify": needs_clarification,
            "clarifier": clarifier,
            "utterance": utterance,
            "_latency_ms": int((time.time() - t0) * 1000),
        }

    # -------------------
    # Extractors
    # -------------------

    def _extract_postcode(self, raw_text: str) -> Tuple[Optional[str], bool, bool, bool]:
        """
        Returns:
          (postcode_normalized, is_full, is_outward, needs_space_fix)

        Rules:
        - Accepts E7 9QS and E79QS (normalizes to "E7 9QS")
        - If only outward exists (e.g., "E7"), return that as outward
        """
        raw_up = (raw_text or "").upper()

        # Try full postcode first (space optional in match)
        m = POSTCODE_FULL_RE.search(raw_up)
        if m:
            outward = m.group(1).strip()
            inward = m.group(2).strip()
            normalized = f"{outward} {inward}"

            # Determine if user typed without a space (so you can decide to *not* nag)
            compact = _only_alnum(raw_up)
            compact_norm = _only_alnum(normalized)
            needs_space_fix = (compact == compact_norm) and (" " not in raw_up[m.start():m.end()])

            return normalized, True, False, needs_space_fix

        # If not full, try outward-only
        m2 = POSTCODE_OUTWARD_RE.search(raw_up)
        if m2:
            outward = m2.group(1).strip()
            # Outward-only is not "missing a space" — it’s just incomplete
            return outward, False, True, False

        return None, False, False, False

    def _extract_sku(self, text: str) -> Optional[str]:
        cands = [m.group(1) for m in SKU_RE.finditer((text or "").upper())]
        for c in cands:
            if len(c) >= 4 and any(ch.isdigit() for ch in c):
                return c
        return None

    def _extract_phone(self, norm: str) -> Optional[str]:
        m = PHONE_RE.search(norm or "")
        return m.group(0) if m else None

    def _guess_tags(self, toks: List[str]) -> List[str]:
        syn = getattr(self, "synonyms", None)

        if syn is not None and hasattr(syn, "canonical"):
            canon: List[str] = []
            for t in toks:
                try:
                    c = syn.canonical(t)
                except Exception:
                    c = t
                canon.append(c)
        else:
            canon = toks

        seen, out = set(), []
        for c in canon:
            if c and c not in seen:
                seen.add(c)
                out.append(c)
        return out[:5]

    # -------------------
    # Intent
    # -------------------

    def _infer_intent(self, norm: str, toks: List[str], ent: Dict[str, Any]) -> str:
        # If the user just sent a postcode (full or outward), treat it as delivery/nearest-store intent
        if ent.get("postcode_normalized"):
            # Optional: if message is basically only the postcode, force check_delivery
            cleaned = _only_alnum(norm)
            pc_clean = _only_alnum(ent["postcode_normalized"].lower())
            if cleaned == pc_clean:
                return "check_delivery"

        if any(k in norm for k in ["deliver", "delivery", "ship", "postcode", "post code", "nearest", "closest", "branch"]):
            return "check_delivery"

        if "price" in toks or "cost" in toks or "how much" in norm:
            return "price_check"

        if any(k in toks for k in ["open", "hours", "time", "when"]):
            return "faq"

        if ent.get("sku"):
            return "price_check"

        if ent.get("tags"):
            return "search_product"

        if norm.endswith("?") or any(k in toks for k in ["do", "can", "is", "are"]):
            return "faq"

        return "unknown"

    # -------------------
    # Clarifiers
    # -------------------

    def _maybe_clarify(self, intent: str, ent: Dict[str, Any], ctx: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        if intent == "check_delivery":
            # Accept full postcodes immediately. Only clarify if missing.
            pc = ent.get("postcode_normalized") or ctx.get("session", {}).get("postcode")
            if not pc:
                pref = ctx.get("coverage_prefixes") or self.geo_prefixes or []
                hint = f" (e.g., {'/'.join(pref[:3])})" if pref else ""
                return True, f"What's your postcode{hint}?"

            # If they only gave outward code, ask for full postcode (don’t talk about spaces)
            if ent.get("postcode_is_outward"):
                return True, f"Got it — what's the full postcode (e.g., {pc} 9QS) so I can check delivery and the nearest branch?"

            # If they gave a full postcode, NEVER nag about spacing. You can silently normalize.
            return False, None

        if intent == "search_product" and not (ent.get("tags") or ent.get("category")):
            return True, "Which product or category are you after?"

        if intent == "price_check" and not ent.get("sku"):
            return True, "Which SKU should I price-check?"

        return False, None
