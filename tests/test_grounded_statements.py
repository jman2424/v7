"""Protected replies retain complete business statements, never model additions."""
import json
from types import SimpleNamespace

import pytest

from service import grounded_conversation
from tests.test_grounded_conversation import _state


STOCK = 'Live inventory is not connected. The team must confirm quantity and availability.'
RETURNS = 'Return unused items within 30 days. Made-to-order items are excluded unless faulty.'


def run(monkeypatch, knowledge, *, text='The team checks stock after checkout.',
        question='How does the policy work?', sources=None, intent='policy', ids=(),
        context=None, agent=None, allowed_actions=None, requested_action=None,
        navigation=None, destinations=None):
    payload = {'answer': text, 'kind': 'answer', 'sources': list(knowledge) if sources is None else sources,
               'agent': agent or _state(intent), 'navigation': navigation or [], 'requested_action': requested_action}
    if ids != ():
        payload['statement_ids'] = ids
    calls = []
    def complete(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])
    monkeypatch.setattr(grounded_conversation, 'tracked_completion', complete)
    state, diagnostics = {}, {}
    answer = grounded_conversation.answer(object(), 'gpt-4.1', question, knowledge, [], 'professional',
        agent_context=context, agent_state=state, diagnostics=diagnostics, allowed_actions=allowed_actions,
        destinations=destinations)
    return answer, state, diagnostics, calls


@pytest.mark.parametrize('invented', [
    'The team confirms stock after your order is placed.', 'Order first; we check availability later.',
    'Inventory is checked once checkout is complete.', 'The team checks stock on receipt of payment.',
    'El equipo confirma la disponibilidad después del pedido.',
    'Le stock sera confirmé après votre commande.', 'سيؤكد الفريق التوفر بعد تقديم الطلب.',
    'I cannot check payments, but our team will confirm payment status.',
])
def test_model_workflow_paraphrases_never_override_complete_policy(monkeypatch, invented):
    answer, _, diagnostics, calls = run(monkeypatch, {'policy:stock': {'answer': STOCK}},
        text=invented, ids=['policy:stock:answer'])
    assert answer == STOCK and len(calls) == 1
    assert diagnostics['accepted'] and diagnostics['mode'] == 'source_statements'
    assert diagnostics['source_ids'] == ['policy:stock']


@pytest.mark.parametrize('policy', [
    RETURNS,
    'The team confirms availability after receiving your order. Do not pay before confirmation.',
    'Our accounts team can verify payment status on request. They cannot amend bank transactions.',
    'Unused items may be returned within 30 days from delivery. Personalised items are excluded.',
    'El equipo confirma el stock después de recibir el pedido. No pagues antes de la confirmación.',
    'Notre comptabilité peut vérifier le paiement sur demande. Aucun remboursement automatique.',
    'يمكن إرجاع المنتجات غير المستخدمة خلال ثلاثين يومًا من التسليم. المنتجات المخصصة مستثناة.',
    'We cannot confirm payment status. The phrase "stock confirmed after checkout" is not our policy.',
])
def test_supported_tenant_conditions_negations_and_languages_survive_whole(monkeypatch, policy):
    answer, _, _, _ = run(monkeypatch, {'policy:custom': {'answer': policy}},
                          text='A typical process applies.', ids=['policy:custom:answer'])
    assert answer == policy


@pytest.mark.parametrize('prefix', ['policy:', 'faq:', 'matched_faq:', 'capability:'])
@pytest.mark.parametrize('ids', [(), []])
def test_legacy_citations_still_preserve_complete_exceptions(monkeypatch, prefix, ids):
    answer, _, _, _ = run(monkeypatch, {prefix + 'returns': {'answer': RETURNS}}, ids=ids)
    assert answer == RETURNS


@pytest.mark.parametrize('ids', [['policy:other:answer'], ['other-tenant:rule'], [7], None,
                               'policy:returns:answer', ['policy:returns:answer'] * 4])
def test_statement_selection_is_request_local_bounded_and_cited(monkeypatch, ids):
    answer, state, diagnostics, calls = run(monkeypatch,
        {'policy:returns': {'answer': RETURNS}, 'policy:other': {'answer': 'Other rules.'}},
        sources=['policy:returns'], ids=ids)
    assert answer is None and state == {} and not diagnostics['accepted'] and len(calls) == 1


@pytest.mark.parametrize('record', [
    {'answer': 'Private policy.', 'public': False}, {'answer': 'Old policy.', 'active': False},
    {'answer': 'Truncated prefix.', 'answer_complete': False}, {'answer': 'x' * 2001},
])
def test_ineligible_units_cannot_become_authoritative_prefixes(monkeypatch, record):
    answer, _, _, _ = run(monkeypatch, {'policy:returns': record}, ids=['policy:returns:answer'])
    assert answer is None
    answer, _, diagnostics, _ = run(monkeypatch, {'policy:returns': record}, ids=[])
    assert 'not established' in answer and diagnostics['source_ids'] == []


@pytest.mark.parametrize('question', ['When is payment confirmed?', '¿Cuándo se confirma el pago?',
                                     'Quand le paiement est-il confirmé ?', 'متى يتم تأكيد الدفع؟'])
def test_customer_request_cannot_bypass_boundary_with_general_intent(monkeypatch, question):
    answer, _, _, _ = run(monkeypatch, {'business': {'about': 'A fictional shop.'}},
                          question=question, intent='answer')
    assert 'not established' in answer


def test_native_rule_preserves_exception_and_manual_review(monkeypatch):
    knowledge = {'business_core': {'business_rules': [{'id': 'returns', 'active': True,
        'description': RETURNS, 'requires_manual_review': True}]}}
    answer, _, _, _ = run(monkeypatch, knowledge, ids=['business_core:rule:returns'])
    assert RETURNS in answer and 'review' in answer


@pytest.mark.parametrize('url', ['https://127.0.0.1/admin', 'https://unapproved.example/collect'])
def test_source_membership_does_not_approve_raw_urls(monkeypatch, url):
    answer, state, diagnostics, _ = run(monkeypatch, {'policy:returns': {'answer': 'Send it to ' + url}},
        text='Please follow the return policy.', ids=['policy:returns:answer'])
    assert answer is None and state == {} and diagnostics['rejection_reason'] == 'unsafe_statement'


def test_source_cannot_confirm_a_customer_transaction(monkeypatch):
    answer, _, _, _ = run(monkeypatch, {'policy:book': {'answer': 'I have booked your appointment.'}},
                          text='Contact the team.', ids=['policy:book:answer'])
    assert answer is None


def test_form_explanation_comes_from_enabled_server_capability(monkeypatch):
    answer, state, diagnostics, calls = run(monkeypatch, {'business': {'name': 'Studio'}},
        question='Please open the quote request form.', text='Completing the form sends nothing until review.',
        agent=_state('quote', action='open_request_form'), allowed_actions=['quote'], requested_action='quote')
    assert answer == 'Open the quote request form to continue.'
    assert 'sends nothing until review' not in answer
    assert state['requested_action'] == 'quote' and len(calls) == 1
    assert diagnostics['source_ids'] == ['capability:request:quote']


def test_support_then_numbered_selection_preserves_verified_task(monkeypatch):
    knowledge = {'product:basic': {'name': 'Basic', 'price': 20, 'currency': 'GBP'},
                 'product:pro': {'name': 'Pro', 'price': 35, 'currency': 'GBP'},
                 'policy:returns': {'answer': RETURNS}}
    context = {'offering_ids': ['product:basic', 'product:pro'],
               'previous_agent': {'requirements': ['under £40']}}
    answer, state, diagnostics, _ = run(monkeypatch, knowledge, sources=['policy:returns'], context=context)
    assert answer == RETURNS and state['offering_ids'] == [] and state['suggested_replies'] == []
    assert state['last_offering_ids'] == ['product:basic', 'product:pro']
    assert state['requirements'] == ['under £40']
    assert RETURNS not in json.dumps(diagnostics)
    answer, chosen, _, _ = run(monkeypatch, knowledge, question="I'll take the second option.",
        sources=['product:pro'], text='Pro costs £35.', context={'previous_agent': state},
        agent=_state('checkout', stage='convert', offerings=['product:pro'], selected='product:pro'))
    assert 'Pro' in answer and '£35' in answer and chosen['selected_offering_id'] == 'product:pro'
    assert chosen['requirements'] == ['under £40']
    assert chosen['last_offering_ids'] == ['product:basic', 'product:pro']


@pytest.mark.parametrize('fields,expected', [
    ({'in_stock': True}, 'in stock'), ({'in_stock': False}, 'out of stock'),
    ({'in_stock': True, 'stock_quantity': 0}, 'out of stock'), ({}, 'needs confirmation'),
])
def test_protected_stock_answer_uses_typed_facts_even_without_offering_metadata(monkeypatch, fields, expected):
    knowledge = {'product:tent': {'name': 'Tent', 'price': 79, 'currency': 'GBP', **fields}}
    answer, state, _, _ = run(monkeypatch, knowledge, question='Is the tent in stock?', intent='answer')
    assert expected in answer and state['offering_ids'] == ['product:tent']


def test_product_units_precision_and_unknown_subscription_interval_are_retained(monkeypatch):
    knowledge = {'offering:pro': {'name': 'Pro', 'price': 0.085, 'currency': 'GBP',
                                 'unit': 'per word', 'type': 'subscription'}}
    answer, _, _, _ = run(monkeypatch, knowledge, intent='checkout', text='Pro pricing needs review.')
    assert '£0.085' in answer and 'per word' in answer
    assert 'Billing interval and renewal terms need confirmation' in answer


def test_protected_recommendation_compares_only_active_verified_budget(monkeypatch):
    knowledge = {'product:trail': {'name': 'Trail', 'price': 20, 'currency': 'GBP'},
                 'product:summit': {'name': 'Summit', 'price': 35, 'currency': 'GBP'},
                 'policy:stock': {'answer': STOCK}}
    answer, _, _, _ = run(monkeypatch, knowledge,
        question='Which bottle fits?', intent='recommend',
        context={'previous_agent': {'requirements': ['light bottle for walks', 'My budget is £25.']}})
    assert 'Trail: £20.00. Listed price is within your stated budget' in answer
    assert 'Summit: £35.00. Listed price is above your stated budget' in answer


@pytest.mark.parametrize('pricing', [
    {'price_type': 'from'}, {'price_type': 'per_hour'}, {'unit': 'each'},
    {'type': 'subscription'}, {'currency': 'EUR'}, {'pricing_mode': 'quote_only'},
])
def test_budget_label_never_compares_incompatible_price_scope(monkeypatch, pricing):
    knowledge = {'offering:design': {'name': 'Design', 'price': 20, 'currency': 'GBP', **pricing}}
    answer, _, _, _ = run(monkeypatch, knowledge, intent='quote',
        context={'previous_agent': {'requirements': ['My budget is £25.']}})
    assert 'your stated budget' not in answer


@pytest.mark.parametrize('pricing', [{'price': 120, 'currency': 'GBP'}, {'pricing_mode': 'quote_only'}])
def test_service_description_survives_without_product_stock_wording(monkeypatch, pricing):
    description = 'A new website designed for the customer.'
    knowledge = {'offering:design': {'name': 'Website', 'type': 'service',
                                    'description': description, **pricing}}
    answer, _, _, _ = run(monkeypatch, knowledge, intent='quote', text='Ask the team for a quote.')
    assert description in answer and 'availability' not in answer and '..' not in answer
    assert ('requires a quote' if 'pricing_mode' in pricing else '£120.00') in answer


def test_requested_form_does_not_repeat_overlapping_capability_statements(monkeypatch):
    policy = 'The team reviews your scope and confirms the quote. Opening a form submits nothing.'
    knowledge = {'policy:quote': {'answer': policy},
                 'capability:requests': {'answer': 'Quote request forms are enabled. Opening a form submits nothing.'}}
    answer, _, diagnostics, _ = run(monkeypatch, knowledge,
        question='Open the quote form.', text='Use the quote form.',
        ids=['policy:quote:answer', 'capability:requests:answer'],
        agent=_state('quote', action='open_request_form'), allowed_actions=['quote'], requested_action='quote')
    assert answer == policy + '\n\nOpen the quote request form to continue.'
    assert 'capability:requests' not in diagnostics['source_ids']


def test_server_numbering_follows_preserved_reference_order(monkeypatch):
    knowledge = {'product:basic': {'name': 'Basic', 'price': 20, 'currency': 'GBP'},
                 'product:pro': {'name': 'Pro', 'price': 35, 'currency': 'GBP'}}
    answer, state, _, _ = run(monkeypatch, knowledge, intent='checkout', text='Choose an option.',
        agent=_state('checkout', offerings=['product:pro', 'product:basic']),
        context={'offering_ids': ['product:basic', 'product:pro']})
    assert answer.index('1. Basic') < answer.index('2. Pro')
    assert state['last_offering_ids'] == ['product:basic', 'product:pro']


def test_broad_core_citation_does_not_select_unrelated_rules(monkeypatch):
    knowledge = {'business_core': {'offerings': [{'name': 'Design'}],
        'business_rules': [{'id': 'returns', 'description': RETURNS}]}}
    answer, _, diagnostics, _ = run(monkeypatch, knowledge, question='What services are there?',
        text='We offer design services.', intent='answer', ids=[])
    assert answer == 'We offer design services.' and diagnostics['mode'] == 'generated'


def test_full_length_rule_preserves_exception_with_manual_review(monkeypatch):
    ending = ' Except custom-made products.'
    text = 'x' * (2000 - len(ending)) + ending
    knowledge = {'business_core': {'business_rules': [
        {'id': 'returns', 'description': text, 'requires_manual_review': True}]}}
    answer, _, _, _ = run(monkeypatch, knowledge, ids=['business_core:rule:returns'])
    assert text in answer and 'require review' in answer


def test_platform_offer_does_not_remove_unrelated_cancellation_faq(monkeypatch):
    knowledge = {'current_platform_offer': {'enabled': True, 'percent': 50,
        'joining_setup_percent': 100, 'sponsor_setup_percent': 50},
        'faq:cancel': {'answer': 'Cancel renewal in subscription settings.'}}
    answer, _, _, _ = run(monkeypatch, knowledge, sources=['faq:cancel'],
        question='How do I cancel?', text='Use the account page.', ids=['faq:cancel:answer'])
    assert answer == knowledge['faq:cancel']['answer']


def test_platform_offer_does_not_replace_setup_instructions(monkeypatch):
    policy = 'For setup, add the widget script to your website footer.'
    knowledge = {'current_platform_offer': {'enabled': True, 'percent': 50,
        'joining_setup_percent': 100, 'sponsor_setup_percent': 50},
        'faq:setup': {'answer': policy}}
    answer, _, _, _ = run(monkeypatch, knowledge, sources=['faq:setup'],
        question='How do I set up the chatbot?', text=policy, ids=['faq:setup:answer'])
    assert answer == policy


def test_current_platform_offer_overrides_stale_referral_faq(monkeypatch):
    knowledge = {'current_platform_offer': {'enabled': True, 'percent': 50,
        'joining_setup_percent': 100, 'sponsor_setup_percent': 50,
        'prices': [{'standard_monthly': '£30', 'referred_first_month': '£15', 'referred_setup': '£0'}]},
        'faq:offer': {'answer': 'The referral discount is 10%.'}}
    answer, _, diagnostics, _ = run(monkeypatch, knowledge, sources=['faq:offer'],
        question='What referral discount applies?', text='The referral discount is 10%.', ids=['faq:offer:answer'])
    assert '50%' in answer and '10%' not in answer
    assert diagnostics['source_ids'] == ['current_platform_offer']


def test_common_money_back_paraphrase_cannot_bypass_protection(monkeypatch):
    answer, _, diagnostics, _ = run(monkeypatch, {'business': {'name': 'Shop'}},
        question='Can I get my money back?', intent='answer', text='You can get your money back within 45 days.')
    assert 'not established' in answer and '45' not in answer
    assert diagnostics['mode'] == 'source_statements'


def test_current_offer_replaces_stale_mixed_referral_and_cancellation_faq(monkeypatch):
    knowledge = {'current_platform_offer': {'enabled': True, 'percent': 50,
        'joining_setup_percent': 100, 'sponsor_setup_percent': 50,
        'prices': [{'standard_monthly': '£30', 'referred_first_month': '£15', 'referred_setup': '£0'}]},
        'faq:0': {'question': 'How do I cancel the referral discount?',
                  'answer': 'The referral discount is 10%. Cancel renewal in subscription settings.'}}
    answer, _, diagnostics, _ = run(monkeypatch, knowledge, sources=['faq:0'],
        question='What referral discount applies, and how do I cancel?',
        text=knowledge['faq:0']['answer'], ids=['faq:0:answer'])
    assert '50%' in answer and '10%' not in answer
    assert 'faq:0' not in diagnostics['source_ids']


def test_enabled_capability_survives_large_unrelated_context(monkeypatch):
    knowledge = {f'website:{index}': {'text': 'Unrelated business history. ' * 100} for index in range(30)}
    knowledge['business'] = {'name': 'Studio'}
    answer, state, _, calls = run(monkeypatch, knowledge, sources=['business'],
        question='Please have someone call me.', text='Use the callback form.',
        agent=_state('handoff', action='open_request_form'), requested_action='callback', allowed_actions=['callback'])
    assert answer and state['requested_action'] == 'callback'
    supplied = json.loads(calls[0]['messages'][1]['content'])['knowledge']
    assert 'capability:request:callback' in supplied
    assert 'requires review' not in answer


@pytest.mark.parametrize('topic,policy', [
    ('cancel', 'Cancel renewal in subscription settings. Cancellation does not refund an existing payment.'),
    ('returns', 'Items bought with a discount may be returned unused within 30 days. Custom items are excluded.'),
])
def test_mixed_promotion_preserves_unrelated_complete_policy(monkeypatch, topic, policy):
    knowledge = {'current_platform_offer': {'enabled': True, 'percent': 50,
        'joining_setup_percent': 100, 'sponsor_setup_percent': 50,
        'prices': [{'standard_monthly': '£30', 'referred_first_month': '£15', 'referred_setup': '£0'}]},
        'faq:' + topic: {'answer': policy}, 'faq:old_offer': {'answer': 'The referral discount is 10%.'}}
    answer, _, diagnostics, _ = run(monkeypatch, knowledge,
        question='What referral discount applies and what is the ' + topic + ' policy?',
        text='Please see the published terms.', ids=['faq:' + topic + ':answer', 'faq:old_offer:answer'])
    assert policy in answer and '50%' in answer and '10%' not in answer
    assert 'faq:' + topic in diagnostics['source_ids']


def test_mixed_comparison_answers_policy_first_and_preserves_numbering(monkeypatch):
    knowledge = {'product:basic': {'name': 'Basic', 'price': 20, 'currency': 'GBP'},
                 'product:pro': {'name': 'Pro', 'price': 35, 'currency': 'GBP'},
                 'policy:returns': {'answer': RETURNS}}
    answer, state, diagnostics, _ = run(monkeypatch, knowledge,
        question='Compare Basic and Pro prices and explain the return policy.',
        text='Here are the published prices and terms.', ids=['policy:returns:answer'],
        agent=_state('policy', offerings=['product:pro', 'product:basic']),
        context={'offering_ids': ['product:basic', 'product:pro']})
    assert answer.startswith(RETURNS)
    assert answer.index('1. Basic: £20.00') < answer.index('2. Pro: £35.00')
    assert state['offering_ids'] == [] and state['suggested_replies'] == [] and state['stage'] == 'assist'
    assert state['last_offering_ids'] == ['product:basic', 'product:pro']
    assert set(diagnostics['source_ids']) == set(knowledge)


def test_named_product_return_does_not_dump_unsolicited_catalogue(monkeypatch):
    knowledge = {'product:tent': {'name': 'Tent', 'price': 79, 'currency': 'GBP'},
                 'policy:returns': {'answer': RETURNS}}
    answer, _, _, _ = run(monkeypatch, knowledge, question='Can I return Tent?',
        text=RETURNS, ids=['policy:returns:answer'], agent=_state('policy', offerings=['product:tent']))
    assert answer == RETURNS


@pytest.mark.parametrize('question', ['What sizes does Tent have and is it in stock?',
                                    '¿Qué tallas tiene Tent y hay disponibilidad?'])
def test_requested_public_options_survive_stock_answer(monkeypatch, question):
    knowledge = {'product:tent': {'name': 'Tent', 'price': 79, 'currency': 'GBP',
        'in_stock': True, 'options': [
            {'name': 'Size', 'value': 'Small'}, {'name': 'Size', 'value': 'Large, except custom fittings'},
            {'name': 'Size', 'value': 'Secret prototype', 'public': False},
            {'name': 'Size', 'value': 'Discontinued size', 'active': False}]}}
    answer, _, diagnostics, _ = run(monkeypatch, knowledge, question=question,
        intent='answer', text='See the catalogue details.')
    assert 'Size: Small' in answer and 'Size: Large, except custom fittings' in answer
    assert 'Secret prototype' not in answer and 'Discontinued size' not in answer
    assert 'Product-level stock does not confirm availability of a specific variant' in answer
    assert diagnostics['source_ids'] == ['product:tent']


def test_large_option_list_is_bounded_without_truncating_values(monkeypatch):
    options = [{'name': 'Colour', 'value': 'Shade ' + str(index)} for index in range(15)]
    knowledge = {'product:tent': {'name': 'Tent', 'options': options}}
    answer, _, _, _ = run(monkeypatch, knowledge, question='What colours does Tent have in stock?',
                          intent='answer', text='See the catalogue options.')
    assert answer.count('Colour: Shade ') == 8
    assert 'Additional catalogue options are not listed here' in answer and 'Shade 8' not in answer


def test_unrequested_options_are_not_dumped_with_price(monkeypatch):
    knowledge = {'product:tent': {'name': 'Tent', 'price': 79, 'currency': 'GBP',
        'options': [{'name': 'Colour', 'value': 'Purple'}]}}
    answer, _, _, _ = run(monkeypatch, knowledge, question='I want to buy Tent.',
                          intent='checkout', text='Tent costs £79.')
    assert '£79.00' in answer and 'Purple' not in answer


def test_policy_button_has_no_generic_repetitive_footer(monkeypatch):
    answer, state, _, _ = run(monkeypatch, {'policy:returns': {'answer': RETURNS}},
        question='Show the return policy.', text=RETURNS, ids=['policy:returns:answer'],
        agent=_state('policy', action='open_destination'), navigation=['returns'],
        destinations=[{'id': 'returns', 'label': 'Read return policy', 'url': 'https://shop.example/returns'}])
    assert answer == RETURNS and state['navigation_ids'] == ['returns']


def test_unconnected_refund_has_a_server_owned_capability_fact(monkeypatch):
    from service.grounded_statements import request_facts
    source = 'capability:transaction_boundary'
    fact = request_facts([])[source]['answer']
    answer, state, diagnostics, _ = run(monkeypatch, {'business':{'name':'Test business'}}, question='Can you issue my refund right now?',
        text='I cannot issue a refund in this chat.', sources=[source], ids=[source+':answer'],
        agent=_state('cancel'))
    assert answer == fact and state.get('requested_action') is None
    assert source in diagnostics['source_ids']
