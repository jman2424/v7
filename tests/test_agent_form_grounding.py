"""The model can select enabled request forms, never execute transactions."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from service import grounded_conversation


def reply(monkeypatch, *, requested='quote', allowed=None, action='open_request_form',
          text='Complete the quote form so the team can review the estimate.', kind='answer'):
    calls = []
    payload = {'kind': kind, 'answer': text, 'sources': ['business'],
               'requested_action': requested, 'agent': {
                   'intent': 'quote', 'stage': 'convert', 'next_action': action,
                   'offering_ids': [], 'selected_offering_id': None, 'requirements': []}}
    def complete(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])
    monkeypatch.setattr(grounded_conversation, 'tracked_completion', complete)
    state = {}
    answer = grounded_conversation.answer(Mock(), 'test-model',
        'Could the team work out a bespoke estimate for a private event?',
        {'business': {'about': 'The team prepares bespoke event estimates after reviewing the request.'}},
        [], 'professional', allowed_actions=allowed or [], agent_state=state)
    return answer, state, calls


def test_approved_form_is_chosen_in_the_same_accounted_answer(monkeypatch):
    answer, state, calls = reply(monkeypatch, allowed=['quote'])
    assert answer and state['requested_action'] == 'quote'
    assert state['next_action'] == 'open_request_form'
    assert len(calls) == 1
    sent = json.loads(calls[0]['messages'][1]['content'])
    assert sent['approved_request_actions'] == ['quote']


@pytest.mark.parametrize('requested,allowed', [
    ('refund', ['refund', 'quote']), ('charge', ['quote']), ('quote', []),
    ('callback', ['quote']), ({'type': 'quote'}, ['quote']), ('quote', {'quote': True}),
])
def test_model_cannot_introduce_an_unsupported_or_disabled_operation(monkeypatch, requested, allowed):
    answer, state, _ = reply(monkeypatch, requested=requested, allowed=allowed)
    assert answer is None and state == {}


def test_form_metadata_never_authorizes_a_completed_booking_claim(monkeypatch):
    answer, state, _ = reply(monkeypatch, allowed=['quote'], text='I have booked your appointment.')
    assert answer is None and state == {}


def test_open_form_step_requires_an_enabled_requested_form(monkeypatch):
    assert reply(monkeypatch, requested=None, allowed=['quote'])[0] is None
    assert reply(monkeypatch, allowed=['quote'], kind='refusal')[0] is None


def test_old_answer_without_form_metadata_remains_valid(monkeypatch):
    answer, state, _ = reply(monkeypatch, requested=None, action='await_customer_question')
    assert answer and 'requested_action' not in state


def test_enabled_quote_form_cannot_replace_a_cancellation_task(monkeypatch):
    def complete(*args, **kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({
            'kind': 'answer', 'answer': 'Cancel future renewal through account settings.',
            'sources': ['business'], 'requested_action': 'quote', 'agent': {
                'intent': 'cancel', 'stage': 'assist', 'next_action': 'open_request_form',
                'offering_ids': [], 'selected_offering_id': None, 'requirements': []}})))])
    monkeypatch.setattr(grounded_conversation, 'tracked_completion', complete)
    state = {}
    answer = grounded_conversation.answer(Mock(), 'test-model', 'I want to cancel, not buy anything.',
        {'business': {'about': 'Cancel future renewal through account settings.'}}, [], 'professional',
        allowed_actions=['quote'], agent_state=state)
    assert answer and state['intent'] == 'cancel'
    assert state['next_action'] == 'await_customer_question' and 'requested_action' not in state
