"""An unknown annual discount must not become a canned monthly-pricing answer."""
import json
from types import SimpleNamespace

from evals.scenarios import BUSINESSES
from service import grounded_conversation


def exercise(monkeypatch, outputs):
    business = BUSINESSES['software']
    calls, diagnostics = [], {}
    def complete(*args, **kwargs):
        calls.append(kwargs)
        payload = outputs[min(len(calls) - 1, len(outputs) - 1)]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])
    monkeypatch.setattr(grounded_conversation, 'tracked_completion', complete)
    result = grounded_conversation.answer(object(), 'test-model', 'Do you offer an annual payment discount?',
        business['knowledge'], [], 'professional', destinations=business['destinations'], diagnostics=diagnostics)
    return result, calls, diagnostics


def unrelated_answer():
    return {'kind': 'answer', 'answer': 'Starter costs GBP 20 per month. Team costs GBP 50 per month. '
            'There is no mention of an annual payment discount in the available information.',
            'sources': ['faq:plans'], 'statement_ids': [], 'navigation': [], 'requested_action': None}


def test_uncertainty_is_not_replaced_by_an_unrelated_pricing_statement(monkeypatch):
    corrected = {'kind': 'clarification', 'answer': 'I cannot confirm an annual payment discount. Contact support to confirm.',
                 'sources': ['business:identity'], 'statement_ids': [],
                 'navigation': ['software-support'], 'requested_action': None}
    answer, calls, diagnostics = exercise(monkeypatch, [unrelated_answer(), corrected])
    assert answer and 'confirm' in answer.lower() and diagnostics['accepted']
    assert 'Starter' not in answer and 'GBP 20' not in answer and len(calls) == 1


def test_unknown_policy_uses_the_existing_verified_path_without_an_extra_call(monkeypatch):
    answer, calls, diagnostics = exercise(monkeypatch, [unrelated_answer()])
    assert answer and 'confirmed information' in answer and 'confirm' in answer and len(calls) == 1
    assert diagnostics['accepted'] and 'GBP 20' not in answer


def test_missing_information_cannot_hide_an_unknown_statement_or_unauthorized_action(monkeypatch):
    for field, value in [('statement_ids', ['other-tenant:rule']), ('navigation', ['unapproved']),
                         ('requested_action', 'refund')]:
        payload = {**unrelated_answer(), field: value}
        answer, calls, diagnostics = exercise(monkeypatch, [payload])
        assert answer is None and len(calls) == 1 and not diagnostics['accepted']


def test_approved_relevant_policy_keeps_all_conditions_without_an_extra_call(monkeypatch):
    facts = {'faq:annual': {'question': 'Annual payment discount?',
             'answer': 'An annual payment discount needs team approval. No automatic discount is applied.'}}
    calls = []
    payload = {'kind': 'answer', 'answer': 'An annual payment discount needs team approval.',
               'sources': ['faq:annual'], 'statement_ids': [], 'navigation': [], 'requested_action': None}
    def complete(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])
    monkeypatch.setattr(grounded_conversation, 'tracked_completion', complete)
    result = grounded_conversation.answer(object(), 'test-model', 'Do you offer an annual payment discount?',
                                           facts, [], 'professional')
    assert result == facts['faq:annual']['answer'] and len(calls) == 1
