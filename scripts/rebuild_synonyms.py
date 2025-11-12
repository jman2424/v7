#!/usr/bin/env python3
"""
Rebuild synonyms suggestions from recent chat logs and analytics.

Usage:
  python scripts/rebuild_synonyms.py --tenant EXAMPLE [--log logs/chatbot.log] [--out business/EXAMPLE/synonyms.suggestions.json]

Logic:
- Parse recent logs for "no match" or "couldn’t find" patterns.
- Tokenize and propose mappings to nearest known catalog tags (simple heuristic).
- Writes suggestions JSON; does NOT modify live synonyms.json.
"""

from __future__ import annotations
import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
BUSINESS = ROOT / "business"

NO_MATCH_PAT = re.compile(r"(couldn.?t find|no match|not find matching items)", re.I)
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9'-]{1,}")
STOP = set("a an the for and or of with on at in near show find tell need want".split())

def load_catalog_tags(tenant: str) -> List[str]:
    cats = json.loads((BUSINESS / tenant / "catalog.json").read_text("utf-8"))
    vocab = set()
    for c in cats.get("categories", []):
        for it in c.get("items", []):
            for t in it.get("tags", []) or []:
                vocab.add(str(t).lower())
            for token in TOKEN_RE.findall(it.get("name") or ""):
                vocab.add(token.lower())
    return sorted(vocab)

def tokenize(text: str) -> List[str]:
    return [t.lower() for t in TOKEN_RE.findall(text or "") if t.lower() not in STOP]

def nearest_tag(term: str, vocab: List[str]) -> str:
    # Simple Jaccard over character bigrams
    def bigrams(s: str) -> set:
        s = f"^{s}$"
        return {s[i:i+2] for i in range(len(s)-1)}
    tb = bigrams(term)
    best = ("", 0.0)
    for v in vocab:
        vb = bigrams(v)
        j = len(tb & vb) / max(1, len(tb | vb))
        if j > best[1]:
            best = (v, j)
    return best[0]

def parse_log_for_queries(path: Path, limit: int = 5000) -> List[str]:
    lines = path.read_text("utf-8", errors="ignore").splitlines()[-limit:]
    queries = []
    for ln in lines:
        if NO_MATCH_PAT.search(ln):
            # naive extract quoted phrase or tail words
            m = re.search(r'"([^"]+)"', ln)
            if m:
                queries.append(m.group(1))
            else:
                # fallback: last 6 words
                tail = " ".join(ln.split()[-6:])
                queries.append(tail)
    return queries

def build_suggestions(tenant: str, log_path: Path, out_path: Path):
    vocab = load_catalog_tags(tenant)
    queries = parse_log_for_queries(log_path)
    if not queries:
        print("[INFO] No ‘no match’ queries found; writing empty suggestions.")
        out_path.write_text(json.dumps({}, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    counts = Counter()
    for q in queries:
        for tok in tokenize(q):
            counts[tok] += 1

    suggestions: Dict[str, List[str]] = {}
    for term, _n in counts.most_common(50):
        if term in vocab:
            continue
        guess = nearest_tag(term, vocab)
        if guess:
            suggestions.setdefault(guess, []).append(term)

    out_path.write_text(json.dumps(suggestions, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Suggestions written → {out_path}")

def main():
    ap = argparse.ArgumentParser(description="Propose synonym mappings from logs")
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--log", default="logs/chatbot.log")
    ap.add_argument("--out", default=None, help="Output JSON (default: business/<TENANT>/synonyms.suggestions.json)")
    args = ap.parse_args()

    out = Path(args.out) if args.out else (BUSINESS / args.tenant / "synonyms.suggestions.json")
    build_suggestions(args.tenant, Path(args.log), out)

if __name__ == "__main__":
    main()
