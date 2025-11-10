"""
SynonymsStore
- Loads term→canonical mappings from business/{TENANT}/synonyms.json
- Merges suggestions from self-repair pipeline (if present)
- Provides forward and reverse lookups, and an apply() helper to normalize tags

synonyms.json (free-form but usually):
{
  "wings": ["wing", "chicken wing", "hot wings"],
  "bbq": ["barbecue", "grill", "bbq pack"]
}
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from retrieval.storage import Storage


def _norm(s: str) -> str:
    return (s or "").strip().lower()


@dataclass
class SynonymsStore:
    storage: Storage

    def __post_init__(self):
        self._forward: Dict[str, List[str]] = self._load()
        self._reverse: Dict[str, str] = {}
        self._build_reverse()

    # -------- internal --------

    def _load(self) -> Dict[str, List[str]]:
        try:
            data = self.storage.read_json(self.storage.tenant_key, "synonyms.json")
            if not isinstance(data, dict):
                return {}
            out: Dict[str, List[str]] = {}
            for canon, alts in data.items():
                canon_n = _norm(canon)
                if not canon_n:
                    continue
                if isinstance(alts, list):
                    out[canon_n] = sorted({_norm(a) for a in alts if _norm(a)})
                elif isinstance(alts, str) and _norm(alts):
                    out[canon_n] = [_norm(alts)]
            return out
        except FileNotFoundError:
            return {}

    def _build_reverse(self) -> None:
        self._reverse.clear()
        for canon, alts in self._forward.items():
            self._reverse[canon] = canon
            for a in alts:
                self._reverse[a] = canon

    # -------- public API --------

    def canonical(self, term: str) -> str:
        """Return canonical tag for a term (or the term itself if unknown)."""
        t = _norm(term)
        return self._reverse.get(t, t)

    def apply(self, tags: List[str]) -> List[str]:
        """Normalize a list of tags to canonical set (deduped, sorted)."""
        return sorted({self.canonical(t) for t in tags if _norm(t)})

    def forward(self) -> Dict[str, List[str]]:
        """Return copy of canon→alts for UI consumption."""
        return {k: list(v) for k, v in self._forward.items()}

    def reverse(self) -> Dict[str, str]:
        """Return copy of alt→canon mapping."""
        return dict(self._reverse)

    # -------- suggestions merging (from self-repair) --------

    def merge_suggestions(self, suggestions: Dict[str, List[str]]) -> Dict[str, List[str]]:
        """
        Merge suggested synonyms into memory only (does not persist).
        suggestions: {canon: [alts...]}; builds reverse on the fly.
        """
        for canon, alts in suggestions.items():
            c = _norm(canon)
            if not c:
                continue
            cur = set(self._forward.get(c, []))
            for a in alts or []:
                a_n = _norm(a)
                if a_n:
                    cur.add(a_n)
            self._forward[c] = sorted(cur)
        self._build_reverse()
        return self.forward()
