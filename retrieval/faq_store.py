"""
FAQStore
- Loads curated Q/A from business/{TENANT}/faq.json
- Lightweight fuzzy matching on questions + tags
- Placeholder interpolation: {postcode}, {branch}, {branch_name}, etc.
- Read-only API for router/rewriter layers

faq.json (validated by schemas/faq.schema.json):
[
  {"q": "What are your hours?", "a": "We're open {open_range} today.", "tags": ["hours"]},
  {"q": "Do you deliver to E6?", "a": "We deliver to {postcode} with {delivery_summary}.", "tags": ["delivery"]}
]
"""

from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from retrieval.storage import Storage

_WORD_RE = re.compile(r"[A-Za-z0-9']+")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _tokenize(s: str) -> List[str]:
    return [m.group(0).lower() for m in _WORD_RE.finditer(s or "")]


def _jaccard(a: List[str], b: List[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


@dataclass
class FAQStore:
    storage: Storage

    def __post_init__(self):
        self._faqs: List[Dict[str, Any]] = self._load()
        # Precompute tokens for quick similarity checks
        for f in self._faqs:
            f["_q_norm"] = _norm(f.get("q", ""))
            f["_q_tokens"] = _tokenize(f.get("q", ""))
            f["_tags_norm"] = [ _norm(t) for t in (f.get("tags") or []) ]

    # -------- internal --------

    def _load(self) -> List[Dict[str, Any]]:
        try:
            data = self.storage.read_json(self.storage.tenant_key, "faq.json")
            if not isinstance(data, list):
                raise ValueError("faq.json must be an array")
            return data
        except FileNotFoundError:
            return []

    # -------- public API --------

    def all(self) -> List[Dict[str, Any]]:
        return list(self._faqs)

    def best_match(
        self,
        user_question: str,
        *,
        hint_tags: Optional[List[str]] = None,
        min_sim: float = 0.18,
        top_k: int = 1,
    ) -> List[Dict[str, Any]]:
        """
        Returns top_k FAQ entries sorted by similarity.
        - Uses Jaccard similarity on token sets
        - If hint_tags provided, adds a small boost when tag intersects
        """
        q_tokens = _tokenize(user_question)
        tagset = set(_norm(t) for t in (hint_tags or []))

        scored: List[Tuple[float, Dict[str, Any]]] = []
        for f in self._faqs:
            sim = _jaccard(q_tokens, f["_q_tokens"])
            if tagset and tagset.intersection(f["_tags_norm"]):
                sim += 0.05
            if sim >= min_sim:
                scored.append((sim, f))

        scored.sort(key=lambda t: t[0], reverse=True)
        return [e for _, e in scored[: max(1, top_k)]]

    def render_answer(self, faq_entry: Dict[str, Any], placeholders: Optional[Dict[str, str]] = None) -> str:
        """
        Interpolate {placeholders} inside the answer text.
        Unknown placeholders are left verbatim to avoid lying.
        """
        ans = str(faq_entry.get("a", ""))
        placeholders = placeholders or {}
        def _replace(m):
            key = m.group(1).strip()
            return str(placeholders.get(key, m.group(0)))
        return re.sub(r"\{([^{}]+)\}", _replace, ans)
