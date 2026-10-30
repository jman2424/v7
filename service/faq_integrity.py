"""Exact curated-FAQ integrity checks, without a model or semantic assumptions.

Conflicting answers to the same question are not resolved by insertion order.
Inactive/private entries cannot suppress an otherwise usable public fact.
"""
from __future__ import annotations

import unicodedata


def _text(row, short, long):
    value = row.get(short, row.get(long, ''))
    return value if isinstance(value, str) else ''


def question_key(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split()).rstrip(' ?？؟')


def faq_groups(rows):
    """Return public, nonempty question groups and their original row indexes."""
    groups = {}
    for index, row in enumerate(rows if isinstance(rows, list) else []):
        if not isinstance(row, dict) or row.get('active') is False or row.get('public') is False:
            continue
        question, answer = _text(row, 'q', 'question'), _text(row, 'a', 'answer')
        key = question_key(question)
        if not key or not answer.strip():
            continue
        # Do not remove punctuation, numbers, case or conditions from answers.
        normalized = ' '.join(unicodedata.normalize('NFC', answer).split())
        group = groups.setdefault(key, {'question': question, 'indexes': [], 'answers': set()})
        group['indexes'].append(index)
        group['answers'].add(normalized)
    return list(groups.values())


def safe_public_faqs(rows):
    """Keep one exact duplicate; withhold every conflicting answer for review.

This detects identical question topics only. Different questions can still
contradict each other; it is not an entailment or full policy review system.
The originals are retained in storage and the management editor.
"""
    return [rows[group['indexes'][0]] for group in faq_groups(rows) if len(group['answers']) == 1]
