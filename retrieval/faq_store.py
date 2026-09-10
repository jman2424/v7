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

# These words help form a sentence but say very little about its subject.  FAQ
# matching must not choose an answer just because two questions both contain
# "do you" or "what are".
_QUESTION_WORDS = {
    "a", "an", "and", "are", "can", "could", "do", "does", "every", "for",
    "have", "how", "i", "if", "in", "is", "it", "me", "my", "of", "on",
    "or", "our", "please", "the", "this", "to", "we", "what", "when", "where",
    "which", "who", "will", "with", "would", "you", "your",
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _tokenize(s: str) -> List[str]:
    return [m.group(0).lower() for m in _WORD_RE.finditer(s or "")]


def _meaningful_tokens(s: str) -> List[str]:
    """Return stable topic words for matching tenant-maintained FAQ data."""
    tokens: List[str] = []
    for token in _tokenize(s):
        if len(token) < 2 or token in _QUESTION_WORDS:
            continue
        if token not in tokens:
            tokens.append(token)
        # A lightweight singular form handles catalog/FAQ wording such as
        # "bags" versus "bag" without requiring a language dependency.
        if token.endswith("s") and len(token) > 3:
            singular = token[:-1]
            if singular not in tokens:
                tokens.append(singular)
    return tokens


def _jaccard(a: List[str], b: List[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


class FAQMatchResult(list):
    def get(self, key: str, default: Any = None) -> Any:
        if not self:
            return default
        first = self[0]
        if isinstance(first, dict):
            return first.get(key, default)
        return default


@dataclass(init=False)
class FAQStore:
    storage: Optional[Storage]

    def __init__(
        self,
        storage: Optional[Storage | List[Dict[str, Any]]] = None,
        *,
        faq: Optional[List[Dict[str, Any]]] = None,
        data: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        if isinstance(storage, list) and faq is None and data is None:
            faq = storage
            storage = None

        self.storage = storage if isinstance(storage, Storage) else None
        self._faqs: List[Dict[str, Any]] = faq or data or self._load()
        # Precompute tokens for quick similarity checks
        for f in self._faqs:
            f["_q_norm"] = _norm(f.get("q", ""))
            f["_q_tokens"] = _tokenize(f.get("q", ""))
            f["_tags_norm"] = [ _norm(t) for t in (f.get("tags") or []) ]
            f["_topic_tokens"] = _meaningful_tokens(
                " ".join(
                    [
                        str(f.get("q", "")),
                        str(f.get("a", "")),
                        " ".join(str(tag) for tag in (f.get("tags") or [])),
                    ]
                )
            )

    # -------- internal --------

    def _load(self) -> List[Dict[str, Any]]:
        if self.storage is None:
            return []
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
    ) -> Any:
        """
        Returns top_k FAQ entries sorted by similarity.
        - Uses Jaccard similarity on token sets
        - If hint_tags provided, adds a small boost when tag intersects
        """
        q_tokens = _tokenize(user_question)
        topic_tokens = _meaningful_tokens(user_question)
        tagset = set(_norm(t) for t in (hint_tags or []))

        scored: List[Tuple[float, Dict[str, Any]]] = []
        for f in self._faqs:
            candidate_topics = f.get("_topic_tokens") or []
            # Topic coverage is intentionally based on the customer's terms,
            # not sentence filler. Answers are included so that a tenant can
            # support terms such as a certification that appear in the answer.
            sim = _jaccard(topic_tokens, candidate_topics)
            if topic_tokens and candidate_topics:
                overlap = len(set(topic_tokens) & set(candidate_topics))
                sim = max(sim, overlap / len(set(topic_tokens)))
            elif not topic_tokens:
                sim = _jaccard(q_tokens, f["_q_tokens"])
            if tagset and tagset.intersection(f["_tags_norm"]):
                sim += 0.05
            if sim >= min_sim:
                scored.append((sim, f))

        scored.sort(key=lambda t: t[0], reverse=True)
        matches = FAQMatchResult([e for _, e in scored[: max(1, top_k)]])
        for item in matches:
            if "answer" not in item and "a" in item:
                item["answer"] = item.get("a")
        return matches

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
