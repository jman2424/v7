"""Rank already public tenant facts for the current customer task."""
from __future__ import annotations

import re


_STOP_WORDS = frozenset({
    'the', 'and', 'for', 'from', 'this', 'that', 'with', 'what', 'which',
    'how', 'can', 'could', 'would', 'you', 'your', 'our', 'have', 'does',
    'about', 'please', 'tell', 'want', 'need', 'are', 'was', 'into',
    'les', 'des', 'une', 'pour', 'avec', 'vous', 'quel', 'que',
    'los', 'las', 'una', 'para', 'con', 'por', 'como', 'puedo',
})


def _terms(value):
    return {'price' if word in {'price','prices','pricing','cost','costs'} else word
            for word in re.findall(r'[^\W_]+', str(value or '').casefold())
            if len(word) > 2 and word not in _STOP_WORDS}


def _public_text(value, depth=0):
    if depth > 4:
        return ''
    if isinstance(value, str):
        return value[:2000]
    if isinstance(value, dict):
        return ' '.join(_public_text(item, depth + 1) for item in list(value.values())[:40])
    if isinstance(value, list):
        return ' '.join(_public_text(item, depth + 1) for item in value[:30])
    return ''


def relevance(record, question):
    words = _terms(question)
    if not words:
        return 0
    title = ' '.join(str(record.get(key) or '') for key in ('name', 'title', 'question', 'sku', 'id')) \
        if isinstance(record, dict) else ''
    return 4 * len(words & _terms(title)) + len(words & _terms(_public_text(record)))


def rank_public_records(rows, question, selected_ids=()):
    """Stable ranking; callers remain responsible for tenant/public filtering."""
    selected = set(selected_ids or ())
    return sorted(rows, key=lambda row: (
        isinstance(row, dict) and row.get('id') in selected,
        relevance(row, question),
    ), reverse=True)


def prioritize_knowledge(knowledge, question, remembered):
    """Keep relevant structured facts ahead of large imported website passages.

    Previous choices retain their references, but past assistant replies cannot
    outweigh a customer's new question. The existing context size cap still
    applies after ranking; no new data is fetched or permissions expanded here.
    """
    pinned = ['business', 'current_platform_offer', remembered.get('selected_offering_id')]
    narrow = len(knowledge) > 24
    pinned += remembered.get('offering_ids', [])
    ordered = {key: knowledge[key] for key in pinned if isinstance(key, str) and key in knowledge}
    candidates = [(key, row) for key, row in knowledge.items() if key not in ordered]
    related = [(key, row) for key, row in candidates
               if not key.startswith('website:') and key != 'business_core'
               and (key.startswith('matched_faq:') or relevance(row, question) > 0)]
    related.sort(key=lambda pair: relevance(pair[1], question), reverse=True)
    for key, row in related[:16] if narrow else related:
        ordered[key] = row
    # Bounded business rules and details supplement individually cited offerings.
    if 'business_core' in knowledge:
        ordered['business_core'] = knowledge['business_core']
    for key, row in candidates:
        if key.startswith('website:'):
            ordered[key] = row
            if narrow and sum(name.startswith('website:') for name in ordered) >= 3:
                break
    # Do not send every unrelated FAQ and catalogue record on every turn.
    # Context is rebuilt for each question; current matches and remembered
    # choices have already been prioritised above. A small preview still helps
    # broad discovery requests that share no literal product-name vocabulary.
    for key, row in candidates if not narrow or not related else []:
        if len(ordered) >= 24:
            break
        if key not in ordered and not key.startswith('website:'):
            ordered[key] = row
    return ordered
