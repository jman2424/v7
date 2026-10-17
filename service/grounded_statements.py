"""Render consequential policy/process replies from complete public source units.

The model selects evidence and next steps. It does not author policy wording in
this path. This is an extractive boundary, not a general entailment classifier.
"""
from __future__ import annotations

from decimal import Decimal
import math
import re


_PROCESS = re.compile(
    r'\b(?:polic(?:y|ies)|returns?|refunds?|cancel\w*|complain\w*|stock|availability|'
    r'book(?:ing|ed)?|appointments?|reservations?|payments?|paid|quotes?|callbacks?|orders?|'
    r'money[ -]back|money back|exchang\w*|replac\w*|reimburs\w*|warrant\w*|guarantee\w*|'
    r'shipping|delivery|deliver\w*|dispatch\w*|postage|arriv\w*|fees?|'
    r'check\s?out|buy|purchase|submit\w*|forms?|'
    r'devoluci\w*|reembols\w*|cancelar|disponibilidad|reservar|pago|pagado|presupuesto|formulario|'
    r'retour\w*|rembours\w*|annul\w*|disponibilit\w*|rendez-vous|paiement|payé|devis|formulaire)\b|'
    r'إرجاع|استرجاع|إلغاء|الغاء|المخزون|التوفر|حجز|موعد|دفع|الدفع|عرض سعر|نموذج', re.I,
)
_INTENTS = {'policy', 'cancel', 'complaint', 'book', 'quote', 'checkout', 'handoff'}
_FORMS = {'consultation': 'consultation', 'quote': 'quote', 'callback': 'callback'}
_OFFER = re.compile(r'\b(?:referr?al|refer|referred|discount|promotion|parrainage|invitar)\b|إحالة', re.I)


def request_facts(allowed_actions):
    """Capabilities come from this channel's enabled server configuration."""
    return {f'capability:request:{action}': {
        'answer': (f'You can open the {label} request form. '
                   'Opening the form does not submit a request or confirm a booking, quote or payment.'),
    } for action, label in _FORMS.items() if action in allowed_actions}


def statement_catalog(knowledge):
    """Never promote website windows, arbitrary metadata or truncated prefixes."""
    result, size = {}, 0

    def add(identifier, source, text, *, review=False):
        nonlocal size
        if (not isinstance(text, str) or not text.strip() or len(text) > 2000
                or len(identifier) > 180 or len(result) >= 24 or size + len(text) > 16000):
            return
        text = text.strip() + (' The details require review by the team.' if review else '')
        result[identifier] = {'source_id': source, 'text': text}
        size += len(text)

    for source, row in knowledge.items():
        if not isinstance(row, dict) or row.get('active') is False or row.get('public') is False:
            continue
        if source.startswith(('policy:', 'capability:', 'faq:', 'matched_faq:')):
            if row.get('answer_complete') is not False:
                add(source + ':answer', source, row.get('answer'))
        elif source == 'current_platform_offer':
            if (type(row.get('enabled')) is bool and all(type(row.get(key)) is int and 0 <= row[key] <= 100
                    for key in ('percent', 'joining_setup_percent', 'sponsor_setup_percent'))):
                from service.platform_offer_knowledge import automatic_offer_answer
                add(source + ':terms', source, automatic_offer_answer('referral', row))
        elif source == 'delivery':
            text = row.get('statement')
            if text is None and not row.get('matching_rule'):
                parts = [row['notes']] if isinstance(row.get('notes'), str) else []
                notices = row.get('notices')
                if isinstance(notices, list) and all(isinstance(note, str) for note in notices):
                    parts += notices
                text = '\n'.join(parts)
            add(source + ':answer', source, text)
        elif source == 'business_core':
            rules = row.get('business_rules')
            if not isinstance(rules, list):
                continue
            for rule in rules[:8]:
                if (not isinstance(rule, dict) or rule.get('active') is False or rule.get('public') is False
                        or not isinstance(rule.get('id'), str)):
                    continue
                add('business_core:rule:' + rule['id'], source, rule.get('description'),
                    review=rule.get('requires_manual_review') is True)
    return result


def protected_request(question, payload, statements):
    agent = payload.get('agent') if isinstance(payload.get('agent'), dict) else {}
    cited = set(payload.get('sources', []))
    return (bool(_PROCESS.search(question)) or bool(_PROCESS.search(payload.get('answer', '')))
            or bool(payload.get('statement_ids')) or agent.get('intent') in _INTENTS
            or bool(payload.get('requested_action'))
            or any(row['source_id'] in cited and row['source_id'] != 'business_core'
                   for row in statements.values()))


def _offering_summary(row, *, product=False, budget=None):
    name = row.get('name')
    if not isinstance(name, str) or not name.strip() or len(name) > 180:
        return ''
    price_type = row.get('price_type') or row.get('pricing_mode')
    quote_only = price_type in {'quote', 'quote_only', 'custom_quote'}
    price, currency = row.get('price'), row.get('currency')
    line = name.strip()
    unit = row.get('unit')
    if isinstance(unit, str) and 0 < len(unit.strip()) <= 80 and unit.casefold() not in line.casefold():
        line += ' (' + unit.strip() + ')'
    if quote_only:
        line += ': Price requires a quote'
    elif (type(price) in (int, float) and 0 <= price <= 1_000_000_000 and math.isfinite(price)
            and isinstance(currency, str) and re.fullmatch(r'[A-Z]{3}', currency)):
        number = format(Decimal(str(price)), 'f')
        if '.' not in number:
            number += '.00'
        elif len(number.rsplit('.', 1)[1]) < 2:
            number += '0'
        symbol = {'GBP': '£', 'USD': '$', 'EUR': '€'}.get(currency, currency + ' ')
        line += ': ' + ('From ' if price_type == 'from' else '') + symbol + number
        if isinstance(price_type, str) and price_type.startswith('per_'):
            line += ' ' + price_type.replace('_', ' ')
        if (budget is not None and currency == budget[0] and price_type in (None, 'fixed')
                and not unit and row.get('type') != 'subscription'):
            comparison = 'within' if Decimal(str(price)) <= budget[1] else 'above'
            line += f'. Listed price is {comparison} your stated budget'
    description = row.get('description')
    if isinstance(description, str) and 0 < len(description.strip()) <= 1000:
        line += '. ' + description.strip().rstrip('. ')
    if row.get('type') == 'subscription':
        line += '. Billing interval and renewal terms need confirmation from the team'
    if not (product or row.get('type') == 'product'
            or any(key in row for key in ('in_stock', 'stock_quantity', 'stock_status'))):
        return line.rstrip('. ') + '.'
    status = row.get('in_stock')
    quantity = row.get('stock_quantity')
    quantity_known = type(quantity) in (int, float) and 0 <= quantity <= 1_000_000_000 and math.isfinite(quantity)
    if quantity_known and quantity == 0:
        status = False
    if status is True or status is False:
        line += '. Recorded product availability: ' + ('in stock' if status else 'out of stock')
    else:
        line += '. Product availability needs confirmation'
    if quantity_known:
        line += f'. Recorded product quantity: {quantity:g}'
    if row.get('options'):
        line += '. Product-level stock does not confirm availability of a specific variant'
    return line.rstrip('. ') + '.'


def render_response(question, payload, state, knowledge, statements, navigation, requested_action):
    """Return protected text/citations, or None for the normal generated path."""
    selected = payload.get('statement_ids', [])
    if (not isinstance(selected, list) or len(selected) > 3
            or any(not isinstance(key, str) or key not in statements for key in selected)):
        raise ValueError('invalid_statement_selection')
    cited = payload['sources']
    if any(statements[key]['source_id'] not in cited for key in selected):
        raise ValueError('uncited_statement_selection')
    if not protected_request(question, payload, statements):
        return None
    if not selected:
        # Legacy payloads still use complete evidence; missing new metadata
        # cannot restore unrestricted prose on a protected turn.
        selected = [key for key, row in statements.items() if row['source_id'] in cited
                    and (row['source_id'] != 'business_core' or 'statement_ids' not in payload)][:3]
    offer_id = 'current_platform_offer:terms'
    if offer_id in statements and ('current_platform_offer' in cited
            or _OFFER.search(question + ' ' + payload.get('answer', ''))):
        selected = [offer_id] + [key for key in selected
                                if not key.startswith(('faq:', 'matched_faq:')) and key != offer_id][:2]
    selected = list(dict.fromkeys(selected))
    if requested_action in _FORMS:
        # The action line below comes from the enabled channel capability.
        # Avoid repeating overlapping capability explanations selected by the model.
        selected = [key for key in selected if not statements[key]['source_id'].startswith('capability:')]
    lines, sources = [], []
    support = state.get('intent') in {'policy', 'cancel', 'complaint'} or payload['kind'] == 'refusal'
    if not support:
        from service.grounded_money import unqualified_customer_budget
        budget = unqualified_customer_budget(state.get('requirements'))
        offerings = state.get('offering_ids', [])
        if not offerings:
            offerings = [key for key in cited if key.startswith(('product:', 'offering:'))][:3]
        reference = state.get('last_offering_ids') or offerings
        ordered = [key for key in reference if key in offerings]
        ordered += [key for key in offerings if key not in ordered]
        if any(key not in reference for key in ordered):
            reference = ordered
        state['offering_ids'] = ordered
        state['last_offering_ids'] = list(reference)
        for key in ordered:
            if key not in cited or key not in knowledge:
                continue
            row = knowledge[key]
            text = _offering_summary(row, product=key.startswith('product:'), budget=budget) if isinstance(row, dict) else ''
            if text:
                lines.append((f'{reference.index(key) + 1}. ' if len(ordered) > 1 else '') + text)
                sources.append(key)
    for key in selected:
        row = statements[key]
        if row['text'] not in lines:
            lines.append(row['text'])
            sources.append(row['source_id'])
    if requested_action in _FORMS:
        source = f'capability:request:{requested_action}'
        text = f'Open the {_FORMS[requested_action]} request form to continue.'
        if text not in lines:
            lines.append(text)
        sources.append(source)
    if not lines:
        lines.append('I cannot perform transactions or provide private information.' if payload['kind'] == 'refusal'
                     else 'That detail is not established in the available business policy. Please ask the team to confirm.')
    if navigation:
        lines.append('Use the available button to continue.')
    text = '\n\n'.join(lines)
    if len(text) > 4000:
        raise ValueError('statement_response_too_long')
    return text, list(dict.fromkeys(sources)), selected
