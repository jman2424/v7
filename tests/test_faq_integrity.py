"""Conflicting public FAQs require review rather than an insertion-order policy."""
import copy
import json
from types import SimpleNamespace

import pytest

from retrieval.faq_store import FAQStore
from service.agent_knowledge import prioritize_knowledge
from service.faq_integrity import safe_public_faqs


@pytest.mark.parametrize('question', ['Refund policy?', '  REFUND   policy  ?', 'Refund policy؟'])
def test_conflicting_exact_question_has_no_automatic_winner(question):
    rows = [{'q': 'Refund policy?', 'a': 'Refunds within 14 days.'},
            {'q': question, 'a': 'Refunds within 30 days.'},
            {'q': 'Opening hours?', 'a': 'Open Monday to Friday.'}]
    before = copy.deepcopy(rows)
    assert safe_public_faqs(rows) == [rows[2]]
    assert rows == before
    assert not FAQStore(faq=copy.deepcopy(rows)).best_match('Refund policy?')


@pytest.mark.parametrize('flag', ['active', 'public'])
def test_private_or_inactive_answer_cannot_suppress_public_policy(flag):
    public = {'q': 'Returns?', 'a': 'Within 14 days.'}
    rows = [public, {'q': 'Returns?', 'a': 'PRIVATE', flag: False}]
    assert safe_public_faqs(rows) == [public]


def test_duplicates_are_deduplicated_without_changing_answer_conditions():
    first = {'q': 'Returns?', 'a': 'Within 14 days, if unused.\nReceipt required.'}
    assert safe_public_faqs([first, {'q': 'RETURNS?', 'a':
        'Within 14 days, if unused. Receipt required.'}]) == [first]
    assert safe_public_faqs([first, {'q': 'Returns?', 'a': 'Within 14 days.'}]) == []


def test_incomplete_and_malformed_rows_are_not_usable_facts():
    assert safe_public_faqs([None, 'text', {}, {'q': 'Returns', 'a': None},
                            {'q': 'Returns', 'a': ' '}, {'q': '?', 'a': 'Yes'}]) == []


def test_distinct_questions_are_not_assumed_semantically_equivalent():
    rows = [{'q': 'Refund policy?', 'a': 'No refunds on custom work.'},
            {'q': 'Can standard goods be returned?', 'a': 'Within 14 days.'}]
    assert safe_public_faqs(rows) == rows


def test_legacy_curated_answer_only_sources_keep_their_validation_contract():
    facts = {'faq:cancel': {'answer': 'Cancel future renewal in account settings.'}}
    assert prioritize_knowledge(facts, 'How can I cancel?', {}) == facts


@pytest.mark.parametrize('questions', [
    ('Quels sont les délais de retour ?', 'QUELS SONT LES DÉLAIS DE RETOUR?'),
    ('ما هي شروط الإرجاع؟', 'ما هي شروط الإرجاع ?'),
])
def test_exact_conflict_detection_preserves_non_english_questions(questions):
    assert safe_public_faqs([{'q': questions[0], 'a': 'First policy.'},
                             {'q': questions[1], 'a': 'Different policy.'}]) == []


def test_separate_businesses_with_the_same_question_keep_their_own_answer():
    first = FAQStore(faq=[{'q': 'Returns?', 'a': 'Within 14 days.'}])
    second = FAQStore(faq=[{'q': 'Returns?', 'a': 'Within 30 days.'}])
    assert first.best_match('Returns?')[0]['a'] == 'Within 14 days.'
    assert second.best_match('Returns?')[0]['a'] == 'Within 30 days.'


def test_prompt_boundary_also_withholds_conflicts_from_different_faq_ids():
    ranked = prioritize_knowledge({'business': {'name': 'Fixture'},
        'matched_faq:0': {'question': 'Returns?', 'answer': 'Within 14 days.'},
        'faq:12': {'question': 'RETURNS?', 'answer': 'Within 30 days.'}}, 'Returns?', {})
    assert list(ranked) == ['business']


def test_handler_does_not_reintroduce_conflicting_faqs_via_broad_fallback(monkeypatch):
    from handlers.handler_v7 import MessageHandlerV7
    from service import grounded_conversation
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    seen = []
    monkeypatch.setattr(grounded_conversation, 'answer', lambda *args, **kwargs: seen.append(args[3]))
    handler = MessageHandlerV7(SimpleNamespace(faq=FAQStore(faq=[
        {'q': 'How long can I return an item?', 'a': '14 days.'},
        {'q': 'How long can I return an item?', 'a': '30 days.'}]),
        rewriter=SimpleNamespace(_client=object(), _model='test-model')))
    handler._grounded_answer('How long can I return an item?', {})
    assert not any(key.startswith(('faq:', 'matched_faq:')) for key in seen[0])


@pytest.mark.parametrize('padding', [0, 40])
def test_focused_credit_topic_does_not_collect_a_separate_long_pricing_faq(padding):
    knowledge = {'business': {'name': 'Fixture'},
        'matched_faq:credit': {'question': 'How is AI usage credit charged?',
            'answer': 'Prepaid AI credit is metered by model and input/output tokens. No automatic recharges.'},
        'matched_faq:plans': {'question': 'What are the subscription plans?',
            'answer': 'Starter GBP 99; Business GBP 199. AI usage credit is separate.'},
        'faq:hours': {'question': 'When are you open?', 'answer': 'Monday to Friday.'},
        **{f'faq:{i}': {'question': f'Unrelated topic {i}', 'answer': 'Background.'} for i in range(padding)}}
    ranked = prioritize_knowledge(knowledge, 'How is AI usage credit charged?', {})
    assert 'matched_faq:credit' in ranked
    assert 'matched_faq:plans' not in ranked and 'faq:hours' not in ranked
    assert 'No automatic recharges.' in json.dumps(ranked)


def test_compound_question_keeps_independent_relevant_topics():
    facts = {'faq:returns': {'question': 'Returns policy?', 'answer': 'Within 14 days if unused.'},
             'faq:delivery': {'question': 'Delivery prices?', 'answer': 'GBP 5 per order.'},
             'faq:history': {'question': 'Our history?', 'answer': 'Founded last year.'}}
    ranked = prioritize_knowledge(facts, 'What is your returns policy and delivery prices?', {})
    assert set(ranked) == {'faq:returns', 'faq:delivery'}


def test_distinctive_answer_only_information_and_broad_fallback_survive():
    facts = {'business': {'name': 'Fixture'},
             'faq:certification': {'question': 'Our certifications?', 'answer': 'HMC certified.'},
             'faq:general': {'question': 'Our history?', 'answer': 'Founded last year.'}}
    assert 'faq:certification' in prioritize_knowledge(facts, 'Are you HMC certified?', {})
    assert 'faq:general' in prioritize_knowledge(facts, 'Tell me about the company', {})


def test_answer_only_exception_survives_a_different_faqs_title_match():
    facts = {'faq:hours': {'question': 'Opening hours?', 'answer': 'Monday to Friday.'},
             'faq:dates': {'question': 'Special dates?', 'answer': 'Closed on Diwali.'},
             'faq:history': {'question': 'Our history?', 'answer': 'Founded last year.'}}
    assert set(prioritize_knowledge(facts, 'What are your opening hours on Diwali?', {})) == {'faq:hours', 'faq:dates'}


def test_single_topic_followup_does_not_restore_plan_pricing_from_answer_overlap():
    facts = {'faq:credit': {'question': 'How is usage credit charged?', 'answer': 'Credit is prepaid and metered by tokens.'},
             'faq:plans': {'question': 'Subscription plans?', 'answer': 'Starter GBP 20 monthly. AI credit is separate.'}}
    assert set(prioritize_knowledge(facts, 'How does credit work?', {})) == {'faq:credit'}


def test_strong_catalogue_match_does_not_remove_conditions_or_selection():
    facts = {'product:gold': {'name': 'Gold coating', 'price': 300, 'currency': 'GBP'},
             'faq:gold': {'question': 'What does gold coating include?', 'answer': 'Paint preparation.'},
             'faq:rules': {'question': 'Estimates and inspection?',
                           'answer': 'Starting prices are estimates, subject to inspection.'}}
    ranked = prioritize_knowledge(facts, 'What does gold coating include?',
                                  {'selected_offering_id': 'product:gold'})
    assert set(ranked) == set(facts)


def test_classification_rules_keep_quote_conditions_even_before_an_offering_is_selected():
    facts = {'faq:size': {'question': 'Which size band is a Yaris?', 'answer': 'A Yaris uses Small.'},
             'faq:quote': {'question': 'How do quotes work?', 'answer': 'Final quotes require inspection.'}}
    assert prioritize_knowledge(facts, 'Which size band is a Yaris?', {}) == facts
