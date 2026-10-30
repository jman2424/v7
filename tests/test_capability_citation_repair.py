"""Recover the observed live citation omission without weakening final guards."""
import json
from types import SimpleNamespace

import pytest

from service import grounded_conversation

POLICY = 'Quotes depend on project scope. The team confirms the final price.'
BOUNDARY = 'Opening the quote form does not submit a request or confirm a price.'


def exercise(monkeypatch, outputs, *, allowed=('quote',)):
    calls, diagnostics = [], {}
    def complete(*args, **kwargs):
        calls.append(kwargs)
        output = outputs[min(len(calls) - 1, len(outputs) - 1)]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(output)))])
    monkeypatch.setattr(grounded_conversation, 'tracked_completion', complete)
    knowledge = {'policy:quotes': {'answer': POLICY},
                 'capability:request:quote': {'answer': BOUNDARY}}
    answer = grounded_conversation.answer(object(), 'test-model', 'How much would a project cost?',
        knowledge, [], 'professional', allowed_actions=list(allowed), diagnostics=diagnostics)
    return answer, calls, diagnostics


def response(*, complete=False):
    return {'kind': 'answer', 'answer': POLICY, 'sources':
        ['policy:quotes', 'capability:request:quote'] if complete else ['policy:quotes'],
        'statement_ids': ['policy:quotes:answer', 'capability:request:quote:answer'],
        'navigation': [], 'requested_action': None}


def test_missing_known_capability_citation_can_be_corrected_once(monkeypatch):
    answer, calls, diagnostics = exercise(monkeypatch, [response(), response(complete=True)])
    assert answer and POLICY in answer and 'does not submit a request' in answer
    assert diagnostics['accepted'] and len(calls) == 2
    assert 'missing_statement_citations' in calls[1]['messages'][0]['content']
    feedback = json.loads(calls[1]['messages'][1]['content'])['validation_feedback']
    assert feedback == {'missing_statement_source_ids': ['capability:request:quote']}
    assert response()['sources'] == ['policy:quotes']  # no automatic citation expansion


def test_repeated_omission_is_rejected_after_one_correction(monkeypatch):
    answer, calls, diagnostics = exercise(monkeypatch, [response()])
    assert answer is None and len(calls) == 2
    assert diagnostics['rejection_reason'] == 'uncited_statement_selection'


@pytest.mark.parametrize('change', ['unknown_statement', 'unapproved_navigation', 'unapproved_action', 'completed_action'])
def test_unsafe_metadata_or_prose_does_not_qualify_for_this_repair(monkeypatch, change):
    payload = response()
    if change == 'unknown_statement':
        payload['statement_ids'] = ['other-tenant:rule']
    elif change == 'unapproved_navigation':
        payload['navigation'] = ['unapproved']
    elif change == 'unapproved_action':
        payload['requested_action'] = 'refund'
    else:
        payload['answer'] = 'Your booking is confirmed and your payment has been processed.'
    answer, calls, diagnostics = exercise(monkeypatch, [payload])
    assert answer is None and not diagnostics['accepted'] and len(calls) == 1


def test_disabled_form_does_not_qualify_for_capability_repair(monkeypatch):
    answer, calls, diagnostics = exercise(monkeypatch, [response()], allowed=())
    assert answer is None and len(calls) == 1 and not diagnostics['accepted']


def test_valid_response_still_uses_one_model_call(monkeypatch):
    answer, calls, diagnostics = exercise(monkeypatch, [response(complete=True)])
    assert answer and diagnostics['accepted'] and len(calls) == 1
