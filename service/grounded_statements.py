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
_PRODUCT_DETAILS = re.compile(
    r'\b(?:recommend\w*|compar\w*|differences?|features?|prices?|costs?|how much)\b', re.I,
)
_OPTION_DETAILS = re.compile(
    r'\b(?:options?|variants?|sizes?|colou?rs?|materials?|dimensions?|measurements?|'
    r'tallas?|colores?|materiales?|opciones?|tailles?|couleurs?|variantes?)\b|'
    r'مقاسات|ألوان|الوان|خيارات|خامة|أبعاد|ابعاد', re.I,
)
_SUPPORT_TOPIC = re.compile(r'\b(?:returns?|refunds?|cancel\w*|complain\w*|warrant\w*|exchang\w*)\b', re.I)


def direct_size_request(question):
    """A single size classification is not a request for prices or booking terms."""
    return bool(not _PROCESS.search(question) and not _PRODUCT_DETAILS.search(question) and re.search(
        r'\b(?:which|what)\s+(?:vehicle\s+)?size\s+band\b|'
        r'\b(?:where|were)\b.{0,45}\b(?:put|fit)\b.{0,30}\b(?:car|vehicle)\b|'
        r'\b(?:where|were)\b.{0,30}\b(?:car|vehicle)\b.{0,25}\bfit\b',question,re.I))


def _overview_request(text):
    return bool(re.fullmatch(r'what (?:do you (?:sell|offer|provide)|(?:products|services) do you (?:sell|offer|provide))',
                             text.strip().casefold().rstrip('?! .')))


def _overview_statement(question, payload, knowledge, statements):
    """An overview may quote complete introductory sentences, never price terms.

    This applies only to a matching broad-overview FAQ. Consequential sentences
    are not summarized or truncated: pricing/policy questions retain full units.
    """
    if not _overview_request(question):
        return None
    for source in payload['sources']:
        row = knowledge[source]
        if not isinstance(row, dict):
            continue
        topic = row.get('question', '')
        if not (_overview_request(topic) or re.match(r'\s*what (?:is|are)\b', topic, re.I)):
            continue
        statement = next((key for key, value in statements.items() if value['source_id'] == source), None)
        if statement is None:
            continue
        lines = []
        for sentence in re.split(r'(?<=[.!?])\s+', statements[statement]['text']):
            if (_PROCESS.search(sentence) or re.search(
                    r'[$£€]|https?://|\b(?:GBP|USD|EUR|VAT|per month|monthly|setup|onboarding|subscriptions?|credit)\b',
                    sentence, re.I)):
                break
            lines.append(sentence)
            if len(lines) >= 3:
                break
        if lines:
            return ' '.join(lines), [source], [statement]
    return None


def request_facts(allowed_actions, *, native_booking_management=False):
    """Capabilities come from this channel's enabled server configuration."""
    facts = {f'capability:request:{action}': {
        'answer': (f'You can open the {label} request form. '
                   'Opening the form does not submit a request or confirm a booking, quote or payment.'),
    } for action, label in _FORMS.items() if action in allowed_actions}
    facts['capability:transaction_boundary'] = {'answer':
        'Payments, refunds, order changes and external calendar changes cannot be completed in this chat. '
        'Use the business\'s approved page or contact its team for help. '
        'Opening a page or request form does not complete a transaction.'}
    if 'consultation' in allowed_actions and native_booking_management:
        facts['capability:native_booking_management'] = {'answer':
            'For an appointment confirmed through a V7 appointment slot, use the private management link '
            'in its booking confirmation to view, change or cancel it. A change or cancellation requires '
            'your explicit confirmation. The link expires after 30 days. This does not manage appointments '
            'in external calendars, issue refunds or process payments. Contact the business if the link is unavailable.'}
    return facts


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


def _stable_prompt_data(value):
    """Canonical object keys after retrieval; list order and all facts survive."""
    if isinstance(value, dict):
        return {key: _stable_prompt_data(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_stable_prompt_data(row) for row in value]
    return value


def prompt_statements(knowledge, statements):
    """Reference exact duplicated wording without changing trusted statements.

    Only the provider payload uses these references. Rendering and claim checks
    keep the complete original knowledge and statement text on the server.
    """
    result = {}
    for identifier, statement in statements.items():
        source = knowledge.get(statement.get('source_id'))
        text = statement.get('text')
        field = next((name for name in ('answer', 'statement')
                      if isinstance(source, dict) and isinstance(source.get(name), str)
                      and isinstance(text, str) and len(text) > 64
                      and source[name].strip() == text), None)
        result[identifier] = ({key: value for key, value in statement.items() if key != 'text'}
                              | {'text_from_knowledge': field} if field else dict(statement))
        if not field and isinstance(source, dict) and isinstance(text, str):
            for rule in source.get('business_rules', []):
                if not isinstance(rule, dict) or not isinstance(rule.get('description'), str):
                    continue
                suffix = ' The details require review by the team.' if rule.get('requires_manual_review') is True else ''
                if (identifier == 'business_core:rule:' + str(rule.get('id'))
                        and text == rule['description'].strip() + suffix):
                    result[identifier] = {'source_id': statement['source_id'],
                        'text_from_rule': rule['id'], 'review_note': suffix.strip()}
                    break
    return _stable_prompt_data(result)


def prompt_knowledge(knowledge, *, prioritized=()):
    """Send an identical offering once; retain every nonduplicated core fact."""
    result = dict(knowledge)
    core = knowledge.get('business_core')
    if isinstance(core, dict) and isinstance(core.get('offerings'), list):
        references, remaining = [], []
        for row in core['offerings']:
            identifier = 'offering:' + str(row.get('id')) if isinstance(row, dict) else ''
            if identifier in knowledge and knowledge[identifier] == row:
                references.append(identifier)
            else:
                remaining.append(row)
        if references:
            result['business_core'] = {**core, 'offerings': remaining, 'offering_source_ids': references}
    stable = _stable_prompt_data(result)
    # Preserve authoritative offer and verified customer selections at the
    # front. Canonicalize only the remaining object-key presentation.
    pinned = {key: stable[key] for key in ('business', 'current_platform_offer', *prioritized)
              if isinstance(key, str) and key in stable}
    return {**pinned, **{key: row for key, row in stable.items() if key not in pinned}}


def protected_request(question, payload, statements):
    agent = payload.get('agent') if isinstance(payload.get('agent'), dict) else {}
    cited = set(payload.get('sources', []))
    return (bool(_PROCESS.search(question)) or bool(_PROCESS.search(payload.get('answer', '')))
            or bool(payload.get('statement_ids')) or agent.get('intent') in _INTENTS
            or bool(payload.get('requested_action'))
            or any(row['source_id'] in cited and row['source_id'] != 'business_core'
                   for row in statements.values()))


def _descriptive_answer(question, payload, knowledge):
    """Ordinary FAQ facts inform an answer; they do not replace its prose.

    Actual policy/process questions and capabilities retain the extractive
    boundary. Merely citing an overview/size/pricing FAQ must not dump it whole.
    """
    agent = payload.get('agent') if isinstance(payload.get('agent'), dict) else {}
    if (_PROCESS.search(question) or agent.get('intent') in {'policy', 'cancel', 'complaint'}
            or payload.get('requested_action')):
        return False
    if re.search(r'\b(?:payments?|paid|pay|deposits?|fees?|stock|availability|shipping|delivery|orders?|'
                 r'refunds?|returns?|cancel\w*|warrant\w*|guarantee\w*)\b',
                 str(payload.get('answer') or ''), re.I):
        # A descriptive question cannot be used to smuggle a new financial or
        # fulfilment process into generated prose. Those claims still require
        # the complete protected source unit.
        return False
    descriptive_faq = False
    for key in payload.get('sources', []):
        if key.startswith(('policy:', 'capability:')) or key == 'current_platform_offer':
            return False
        row = knowledge.get(key)
        if key.startswith(('faq:', 'matched_faq:')) and isinstance(row, dict):
            if (not row.get('question') or _SUPPORT_TOPIC.search(row['question'])
                    or _SUPPORT_TOPIC.search(str(row.get('answer') or ''))
                    or re.search(r'\b(?:fees?|monthly|per month|subscriptions?|credit|setup)\b',
                                 str(row.get('answer') or ''), re.I)):
                return False
            descriptive_faq = True
    return descriptive_faq


def _option_summary(row, question):
    """Show requested catalogue attributes without inferring variant inventory."""
    options = row.get('options')
    if not isinstance(options, list):
        return ''
    asked = bool(_OPTION_DETAILS.search(question))
    parts = []
    for option in options[:20]:
        if not isinstance(option, dict) or option.get('public') is False or option.get('active') is False:
            continue
        name, value = option.get('name'), option.get('value')
        if (not isinstance(name, str) or not 0 < len(name.strip()) <= 80
                or not isinstance(value, str) or not 0 < len(value.strip()) <= 160):
            continue
        if not asked and not re.search(r'(?<!\w)' + re.escape(name.strip()) + r'(?!\w)', question, re.I):
            continue
        part = name.strip() + ': ' + value.strip()
        if part not in parts:
            parts.append(part)
    if not parts:
        return ''
    shown = []
    for part in parts:
        if len(shown) >= 8 or len('; '.join(shown + [part])) > 900:
            break
        shown.append(part)
    suffix = '. Additional catalogue options are not listed here' if len(shown) < len(parts) else ''
    return '. Catalogue options — ' + '; '.join(shown) + suffix


def _mixed_product_request(question, cited, knowledge):
    if not (_PRODUCT_DETAILS.search(question) or _OPTION_DETAILS.search(question)):
        return False
    for key in cited:
        row = knowledge.get(key)
        name = row.get('name') if isinstance(row, dict) else None
        if (key.startswith(('product:', 'offering:')) and isinstance(name, str) and name.strip()
                and re.search(r'(?<!\w)' + re.escape(name.strip()) + r'(?!\w)', question, re.I)):
            return True
    return False


def _promotion_unit(key, statements, knowledge):
    row = knowledge.get(statements[key]['source_id'])
    topic = key.replace('_', ' ')
    if isinstance(row, dict) and isinstance(row.get('question'), str):
        topic += ' ' + row['question']
    return bool(_OFFER.search(statements[key]['text'])) and (
        bool(_OFFER.search(topic)) or not _SUPPORT_TOPIC.search(topic))


def _offering_summary(row, *, product=False, budget=None, question='', shared_unit=None, service_business=False):
    name = row.get('name')
    if not isinstance(name, str) or not name.strip() or len(name) > 180:
        return ''
    price_type = row.get('price_type') or row.get('pricing_mode')
    quote_only = price_type in {'quote', 'quote_only', 'custom_quote'}
    price, currency = row.get('price'), row.get('currency')
    line = name.strip()
    unit = row.get('unit')
    if (isinstance(unit, str) and 0 < len(unit.strip()) <= 80 and unit != shared_unit
            and unit.casefold() not in line.casefold()):
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
    line += _option_summary(row, question)
    if row.get('type') == 'subscription':
        line += '. Billing interval and renewal terms need confirmation from the team'
    if row.get('type') == 'service' or (service_business and row.get('type') != 'product'):
        # A service catalogue flag is not evidence of appointment availability.
        return line.rstrip('. ') + '.'
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
    if payload.get('kind') in {'greeting', 'clarification', 'refusal'} and not _PROCESS.search(question):
        # Citing a FAQ as context is not permission to replace a conversational
        # clarification/refusal with that FAQ's unrelated onboarding paragraph.
        return None
    selected = payload.get('statement_ids', [])
    if (not isinstance(selected, list) or len(selected) > 3
            or any(not isinstance(key, str) or key not in statements for key in selected)):
        raise ValueError('invalid_statement_selection')
    cited = payload['sources']
    if any(statements[key]['source_id'] not in cited for key in selected):
        raise ValueError('uncited_statement_selection')
    if _descriptive_answer(question, payload, knowledge):
        return None
    overview = _overview_statement(question, payload, knowledge, statements)
    if overview is not None and not requested_action and payload['kind'] != 'refusal':
        return overview
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
        selected = [offer_id] + [key for key in selected if key != offer_id
                                and not (key.startswith(('faq:', 'matched_faq:'))
                                         and _promotion_unit(key, statements, knowledge))][:2]
    selected = list(dict.fromkeys(selected))
    if requested_action in _FORMS:
        # The action line below comes from the enabled channel capability.
        # Avoid repeating overlapping capability explanations selected by the model.
        selected = [key for key in selected if not statements[key]['source_id'].startswith('capability:')]
    lines, sources = [], []
    offering_lines, offering_sources = [], []
    support = state.get('intent') in {'policy', 'cancel', 'complaint'} or payload['kind'] == 'refusal'
    if not support or (payload['kind'] != 'refusal' and _mixed_product_request(question, cited, knowledge)):
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
        if not support:
            state['offering_ids'] = ordered
        state['last_offering_ids'] = list(reference)
        rows = [knowledge[key] for key in ordered if key in cited and isinstance(knowledge.get(key),dict)]
        units = [row.get('unit') for row in rows]
        shared_unit = (units[0] if len(units)>1 and isinstance(units[0],str)
                       and 0<len(units[0].strip())<=80 and all(unit==units[0] for unit in units) else None)
        business = knowledge.get('business',{})
        service_business = isinstance(business,dict) and business.get('offering_type')=='services'
        for key in ordered:
            if key not in cited or key not in knowledge:
                continue
            row = knowledge[key]
            text = _offering_summary(row, product=key.startswith('product:'), budget=budget,
                                     question=question,shared_unit=shared_unit,
                                     service_business=service_business) if isinstance(row, dict) else ''
            if text:
                offering_lines.append((f'{reference.index(key) + 1}. ' if len(ordered) > 1 else '') + text)
                offering_sources.append(key)
        if shared_unit and offering_lines:
            offering_lines.append('Pricing: '+shared_unit.strip().rstrip('. ')+'.')
    for key in selected:
        row = statements[key]
        if row['text'] not in lines:
            lines.append(row['text'])
            sources.append(row['source_id'])
    if support:
        lines += offering_lines
        sources += offering_sources
    else:
        lines = offering_lines + lines
        sources = offering_sources + sources
    if requested_action in _FORMS:
        source = f'capability:request:{requested_action}'
        text = f'Open the {_FORMS[requested_action]} request form to continue.'
        if text not in lines:
            lines.append(text)
        sources.append(source)
        if requested_action=='consultation':
            lines.append('Any price or assessment discussed is an estimate, not a final quote.')
    if not lines:
        lines.append('I cannot perform transactions or provide private information.' if payload['kind'] == 'refusal'
                     else 'That detail is not established in the available business policy. Please ask the team to confirm.')
    text = '\n\n'.join(lines)
    if len(text) > 4000:
        raise ValueError('statement_response_too_long')
    return text, list(dict.fromkeys(sources)), selected
