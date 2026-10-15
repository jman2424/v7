"""Structured output prevents malformed provider responses before validation."""
import copy

import pytest
from jsonschema import Draft202012Validator, ValidationError

from service import grounded_conversation
from service.agent_response_schema import response_format
from service.openai_completion import responses_options
from tests.test_grounded_conversation import _state, _structured_answer


def contract():
    return response_format({'business': {'name': 'Fixture'}}, [], ['quote'],
        intents=grounded_conversation.AGENT_INTENTS, stages=grounded_conversation.AGENT_STAGES,
        actions=grounded_conversation.AGENT_ACTIONS)


def test_request_contract_requires_citations_known_ids_and_explicit_nullable_updates():
    schema = contract()['json_schema']['schema']
    validator = Draft202012Validator(schema)
    payload = {'answer': 'Complete the quote request form for the team to review.',
               'kind': 'answer', 'sources': ['business'], 'navigation': [], 'requested_action': 'quote',
               'agent': {**_state('quote', stage='convert', action='open_request_form'),
                         'selection_update': 'keep', 'selection_evidence': None, 'requirements_update': None}}
    validator.validate(payload)
    for changes in ({'sources': []}, {'sources': ['other-company']},
                    {'navigation': ['not-enabled']}, {'requested_action': 'refund'}):
        with pytest.raises(ValidationError):
            validator.validate({**payload, **changes})
    invalid = copy.deepcopy(payload)
    invalid['agent']['requirements_update'] = {'add': [], 'remove': [], 'clear': False, 'evidence': ''}
    with pytest.raises(ValidationError):
        validator.validate(invalid)


def test_existing_responses_adapter_preserves_the_strict_output_schema():
    format_ = contract()
    options = responses_options({'model': 'gpt-6-sol', 'messages': [], 'max_tokens': 1024,
                                 'response_format': format_})
    result = options['text']['format']
    assert result['type'] == 'json_schema' and result['strict'] is True
    assert result['schema'] == format_['json_schema']['schema']


def test_legacy_empty_optional_update_keeps_grounded_reply_and_verified_constraints(monkeypatch):
    payload = {'answer': 'Basic is £99.', 'kind': 'answer', 'sources': ['product:basic'],
               'agent': {**_state(requirements=['for my office']), 'requirements_update': {
                   'add': [], 'remove': [], 'clear': False, 'evidence': ''}}}
    answer, state, _, _ = _structured_answer(monkeypatch, payload,
        context={'previous_agent': {'requirements': ['for my office']}})
    assert answer and state['requirements'] == ['for my office']


@pytest.mark.parametrize('update', [None, {}, {'add': [], 'remove': [], 'clear': False, 'evidence': ''}])
def test_policy_answer_without_constraint_changes_keeps_previous_customer_needs(monkeypatch, update):
    payload = {'answer': 'Cancel future renewal through subscription settings.', 'kind': 'answer',
               'sources': ['faq:cancel'], 'agent': {
                   **_state('cancel', stage='assist'), 'requirements_update': update}}
    old = ['for my office', 'under 100 pounds']
    answer, state, _, _ = _structured_answer(monkeypatch, payload, question='How can I cancel?',
        context={'previous_agent': {'requirements': old}})
    assert answer and state['requirements'] == old
