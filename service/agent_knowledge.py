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


def size_variant_family(name):
    """Recognise an explicitly size-labelled catalogue family, not a car model."""
    if not isinstance(name,str):
        return ''
    match=re.fullmatch(r'(.+?)\s*(?:[—–-]\s*)?\b(?:Small|Medium|Large)\b\s*'
                      r'(?:\(starting price\))?\s*',name,re.I)
    return match[1].strip(' —–-') if match else ''


def remembered_size_variants(knowledge,remembered):
    """Keep current public sibling prices when a follow-up changes size/model."""
    references=[remembered.get('selected_offering_id'),*remembered.get('offering_ids',[])]
    families=set()
    for key in references:
        row=knowledge.get(key) if isinstance(key,str) else None
        if isinstance(row,dict) and (family:=size_variant_family(row.get('name'))):
            families.add((family.casefold(),row.get('currency')))
    return [key for key,row in knowledge.items() if key.startswith(('product:','offering:'))
            and isinstance(row,dict) and row.get('public') is not False and row.get('active') is not False
            and (size_variant_family(row.get('name')).casefold(),row.get('currency')) in families][:9]


def displayed_catalogue_ids(text,knowledge):
    """Bind a short visible price list to unique, current public records.

    This recovers references when a model cited a combined pricing FAQ. A name
    prefix alone is insufficient: currency and exact price must also match.
    Ambiguous/mixed/incomplete lists are left for normal clarification.
    """
    from service.grounded_money import extract_money_claims, _structured_price
    normalize = lambda value:' '.join(re.findall(r'[^\W_]+',value.casefold()))
    candidates = [(key,row) for key,row in knowledge.items()
        if key.startswith(('product:','offering:')) and isinstance(row,dict)
        and row.get('active') is not False and row.get('public') is not False
        and isinstance(row.get('name'),str) and isinstance(row.get('currency'),str)
        and row.get('price_type') not in ('quote','quote_only','custom_quote')
        and row.get('pricing_mode') not in ('quote','quote_only','custom_quote')]
    found, fence = [], None
    for line in str(text or '').splitlines()[:100]:
        marker = re.match(r'^\s*(`{3,}|~{3,})',line)
        if marker:
            if not fence:
                fence = marker[1]
            elif marker[1][0]==fence[0] and len(marker[1])>=len(fence):
                fence = None
            continue
        if fence:
            continue
        option = re.match(r'^(?:([1-9]\d*)[.)]|[•*-])\s+(.+)$',line)
        if not option:
            continue
        if len(found)>=3 or (option[1] and int(option[1])!=len(found)+1):
            return []
        body = option[2]
        label = re.match(r'^(.*?)\s*(?:£|\$|€|GBP\b|USD\b|EUR\b)\s*[+\-−]?\d',body,re.I)
        prices = extract_money_claims(body)
        if not label or not prices or len(prices)!=1:
            return []
        name = normalize(label[1].strip(' \t:—–-'))
        matches = [key for key,row in candidates if _structured_price(row) in prices
            and (normalize(row['name'])==name
                 or (len(name.split())>=2 and normalize(row['name']).startswith(name+' ')))]
        if len(matches)!=1 or matches[0] in found:
            return []
        found.append(matches[0])
    return found if len(found)>=2 else []


def prioritize_knowledge(knowledge, question, remembered):
    """Keep relevant structured facts ahead of large imported website passages.

    Previous choices retain their references, but past assistant replies cannot
    outweigh a customer's new question. The existing context size cap still
    applies after ranking; no new data is fetched or permissions expanded here.
    """
    pinned = ['business', 'current_platform_offer', remembered.get('selected_offering_id')]
    narrow = len(knowledge) > 24
    pinned += remembered.get('offering_ids', [])
    pinned += remembered_size_variants(knowledge,remembered)
    # Many near-identical price variants can outrank the rule needed to choose
    # between them. Keep bounded public sizing/classification guidance alongside
    # a matching catalogue task, even when a new model name has no literal match.
    catalogue_task = any(key.startswith(('product:','offering:')) and relevance(row,question)>0
                         for key,row in knowledge.items())
    if catalogue_task:
        guides = [key for key,row in knowledge.items() if key.startswith(('faq:','matched_faq:'))
            and isinstance(row,dict) and re.search(
                r'\b(?:classif\w*|sizing|size (?:bands?|guide|categor\w*))\b',
                str(row.get('question',''))+' '+str(row.get('answer',''))[:160],re.I)]
        guides.sort(key=lambda key:relevance(knowledge[key],question),reverse=True)
        # Keep the specific clarification plus the core band examples; one
        # generic guide must not displace either side of that decision.
        pinned += guides[:3]
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
