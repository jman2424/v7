"""A completed provider call must not masquerade as a validated customer answer."""
import json
from types import SimpleNamespace

import pytest

from service import grounded_conversation


KNOWLEDGE = {'product:basic': {'name': 'Basic', 'price': 99, 'currency': 'GBP'}}


def test_known_uncited_shortlist_does_not_destroy_a_grounded_consultation(monkeypatch):
    from tests.test_grounded_conversation import _state, _structured_answer
    knowledge={'product:entry-large':{'name':'Entry Coating Large','price':300,'currency':'GBP'},
               'faq:size':{'question':'Which size band applies?','answer':'SUVs use Large.'},
               'faq:price':{'question':'What is the Entry Coating price?',
                             'answer':'Entry Coating starts at GBP 300 for Large vehicles.'}}
    payload={'answer':'Your SUV uses Large. Entry Coating starts at GBP 300.',
             'kind':'answer','sources':['faq:price','faq:size'],'navigation':['booking'],
             'agent':_state('price',offerings=['product:entry-large'],action='open_destination')}
    result,state,links,_=_structured_answer(monkeypatch,payload,knowledge=knowledge,
        question='My SUV needs Entry Coating. What is its starting estimate?',
        destinations=[{'id':'booking','label':'Book','url':'https://fixture.example/book'}])
    assert result==payload['answer'] and state['offering_ids']==[]
    assert state['sources']==['faq:price','faq:size'] and links[0]['url']=='https://fixture.example/book'
    # A foreign/unknown reference is still rejected rather than pruned.
    payload['agent']['offering_ids']=['product:another-company']
    assert _structured_answer(monkeypatch,payload,knowledge=knowledge)[0] is None


def run_answer(monkeypatch, payload, *, diagnostics=None):
    def complete(*args, **kwargs):
        if isinstance(payload, Exception):
            raise payload
        text = payload if isinstance(payload, str) else json.dumps(payload)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])

    monkeypatch.setattr(grounded_conversation, 'tracked_completion', complete)
    return grounded_conversation.answer(object(), 'gpt-4o-mini', 'Private customer question',
                                        KNOWLEDGE, [], 'professional', diagnostics=diagnostics)


def test_validated_answer_records_only_public_source_ids(monkeypatch):
    diagnostics = {}
    text = 'Basic costs £99.'
    assert run_answer(monkeypatch, {'answer': text, 'kind': 'answer',
                                   'sources': ['product:basic']}, diagnostics=diagnostics) == text
    assert diagnostics['accepted'] is True
    assert diagnostics['provider_completed'] is True
    assert diagnostics['rejection_reason'] is None
    assert diagnostics['source_ids'] == ['product:basic']
    # Public product plus the server-owned transaction capability boundary.
    assert diagnostics['knowledge_count'] == 2
    assert diagnostics['latency_ms'] >= 0
    assert 'Private customer question' not in json.dumps(diagnostics)
    assert text not in json.dumps(diagnostics)


@pytest.mark.parametrize('payload,reason', [
    ({'answer': 'Basic costs £500.', 'kind': 'answer', 'sources': ['product:basic']},
     'unsupported_claim'),
    ({'answer': 'Private invented facts', 'kind': 'answer', 'sources': ['private-source']},
     'output_contract'),
    ({'answer': 'Basic costs £99.', 'kind': 'answer', 'sources': ['product:basic'],
      'navigation': ['unapproved-checkout']}, 'invalid_navigation'),
    ('private malformed JSON', 'invalid_json'),
])
def test_completed_provider_response_can_still_fail_validation(monkeypatch, payload, reason):
    diagnostics = {'accepted': True, 'source_ids': ['old-source']}
    assert run_answer(monkeypatch, payload, diagnostics=diagnostics) is None
    assert diagnostics['accepted'] is False
    assert diagnostics['provider_completed'] is True
    assert diagnostics['rejection_reason'] == reason
    assert diagnostics['source_ids'] == []
    assert 'private' not in json.dumps(diagnostics).casefold()


def test_provider_failure_diagnostics_never_include_exception_contents(monkeypatch):
    diagnostics = {}
    assert run_answer(monkeypatch, RuntimeError('private provider credential'),
                      diagnostics=diagnostics) is None
    assert diagnostics['accepted'] is False
    assert diagnostics['provider_completed'] is False
    assert diagnostics['rejection_reason'] == 'provider_unavailable'
    assert 'private provider credential' not in json.dumps(diagnostics)


@pytest.mark.parametrize('client,knowledge,reason', [
    (None, KNOWLEDGE, 'missing_client'),
    (object(), None, 'missing_knowledge'),
])
def test_unavailable_answer_has_a_safe_diagnostic(client, knowledge, reason):
    diagnostics = {}
    assert grounded_conversation.answer(client, 'gpt-4o-mini', 'Question', knowledge,
                                        [], 'professional', diagnostics=diagnostics) is None
    assert diagnostics['rejection_reason'] == reason
    assert diagnostics['provider_completed'] is False
    assert diagnostics['source_ids'] == []


def test_qualification_context_retains_refusal_and_only_bounded_public_evidence():
    context = grounded_conversation.agent_context_rows({
        'playbook': {'qualification_questions': ['What is your budget?', 'When do you need it?']},
        'previous_agent': {
            'qualification_declined': True, 'qualification_paused': False,
            'qualification_answers': {
                'What is your budget?': {'status': 'declined', 'evidence': 'No thanks'},
                'When do you need it?': {'status': 'answered', 'evidence': 'contact me at private@example.test'},
                'Unknown internal question': {'status': 'answered', 'evidence': 'Private instruction'},
            },
        },
    }, KNOWLEDGE)
    previous = context['previous_agent']
    assert previous['qualification_declined'] is True
    assert previous['qualification_paused'] is False
    assert previous['qualification_answers'] == {
        'What is your budget?': {'status': 'declined', 'evidence': 'No thanks'},
    }
    assert 'private@example.test' not in json.dumps(context)
    assert 'Private instruction' not in json.dumps(context)


@pytest.mark.parametrize('question,selected', [
    ("I'll take the second option; where can I buy it?", 'product:pro'),
    ('I choose option 2, actually I choose Basic.', 'product:basic'),
    ('I choose Basic, actually I choose the second option.', 'product:pro'),
    ("I'll take the second.", 'product:pro'),
    ('Could I choose the second option?', None),
    ('Is the second option right for me?', None),
    ("I don't want the second option.", None),
    ("I'll take the second option. Do not choose the second option.", None),
    ("I'll take the second option. Do not choose Pro.", None),
    ("I'll take Pro. Do not choose the second option.", None),
    ("I'll take the second option. I don't want Pro.", None),
    ("Do not choose Pro. I'll take the second option.", 'product:pro'),
    ("I'll take 2 bottles.", None),
])
def test_ordinal_choices_use_actual_consent_and_latest_customer_choice(question, selected):
    knowledge = {**KNOWLEDGE, 'product:pro': {'name': 'Pro', 'price': 199, 'currency': 'GBP'}}
    raw = {'selected_offering_id': selected, 'selection_update': 'keep' if selected is None else 'select'}
    context = {'offering_ids': ['product:basic', 'product:pro'], 'selected_offering_id': None}
    assert grounded_conversation._selection_state(raw, question, knowledge, context) == selected


def test_preexisting_retired_qualification_evidence_never_reaches_the_provider():
    context = grounded_conversation.agent_context_rows({
        'playbook': {'qualification_questions': ['What is your budget?']},
        'previous_agent': {
            'retired_requirements': ['budget is £100'],
            'qualification_complete': True, 'qualification_index': 1,
            'qualification_answers': {'What is your budget?': {
                'status': 'answered', 'evidence': 'My budget is £100',
            }},
        },
    }, KNOWLEDGE)
    assert 'qualification_answers' not in context['previous_agent']
    assert context['previous_agent']['qualification_complete'] is False
    assert context['previous_agent']['qualification_index'] == 0
    assert context['previous_agent']['qualification_paused'] is True


@pytest.mark.parametrize('kind,intent', [('answer', 'policy'), ('refusal', 'answer')])
def test_support_discards_only_known_stale_shortlist_metadata(monkeypatch, kind, intent):
    from tests.test_grounded_conversation import _state, _structured_answer

    knowledge = {**KNOWLEDGE, 'policy:returns': {'answer': 'Return unused items within 30 days.'}}
    payload = {'answer': 'Return unused items within 30 days.', 'kind': kind,
               'sources': ['policy:returns'], 'agent': _state(intent, offerings=['product:basic'])}
    answer, state, _, _ = _structured_answer(monkeypatch, payload, question='How do returns work?',
        knowledge=knowledge, context={'offering_ids': ['product:basic']})
    assert answer
    assert state['offering_ids'] == []
    assert state['last_offering_ids'] == ['product:basic']
    assert state['stage'] == 'assist'
    assert state['suggested_replies'] == []
    payload['agent']['offering_ids'] = ['product:unknown']
    assert _structured_answer(monkeypatch, payload, question='How do returns work?',
        knowledge=knowledge, context={'offering_ids': ['product:basic']})[0] is None


def test_visible_recommendations_still_require_cited_offering_sources(monkeypatch):
    from tests.test_grounded_conversation import _state, _structured_answer

    payload = {'answer': 'The shop can help.', 'kind': 'answer', 'sources': ['business'],
               'agent': _state('recommend', offerings=['product:basic'])}
    knowledge = {**KNOWLEDGE, 'business': {'name': 'Example shop'}}
    answer,state,_,_ = _structured_answer(monkeypatch,payload,knowledge=knowledge)
    assert answer==payload['answer']
    assert state['offering_ids']==[] and state['last_offering_ids']==[] and state['suggested_replies']==[]


@pytest.mark.parametrize('action', ['await_customer_question', 'open_destination', 'open_request_form'])
def test_refusal_never_reuses_an_old_checkout_link(monkeypatch, action):
    from tests.test_grounded_conversation import _state, _structured_answer

    payload = {'answer': 'I cannot share private information.', 'kind': 'refusal', 'sources': ['business'],
               'navigation': ['checkout'], 'agent': _state('answer', action=action)}
    answer, state, links, _ = _structured_answer(monkeypatch, payload,
        knowledge={'business': {'name': 'Example shop'}},
        destinations=[{'id': 'checkout', 'label': 'Checkout', 'url': 'https://example.com/checkout'}])
    assert answer
    assert links == [] and state['navigation_ids'] == []
    assert state['next_action'] == 'await_customer_question'


@pytest.mark.parametrize('prefix', ['within', 'well within', 'under', 'fits', 'meets'])
def test_budget_comparison_keeps_offering_price_subject_to_cited_evidence(prefix):
    from service.grounded_money import monetary_claims_supported

    facts = [{'name': 'Basic', 'price': 20, 'currency': 'GBP'}]
    customer = ['My budget is £40.']
    assert monetary_claims_supported(f'Basic is {prefix} your budget at £20.', facts,
                                    customer_text=customer)
    assert not monetary_claims_supported(f'Basic is {prefix} your budget at £999.', facts,
                                        customer_text=customer)
    assert not monetary_claims_supported('Your budget is £20.', facts, customer_text=customer)
    assert monetary_claims_supported('Your budget is £40. Basic costs £20.', facts,
                                    customer_text=customer)
    assert monetary_claims_supported('With a budget of £40, Basic costs £20.', facts,
                                    customer_text=customer)
    assert not monetary_claims_supported('With a budget of £999, Basic costs £20.', facts,
                                        customer_text=customer)
    assert not monetary_claims_supported('Basic costs £40, within your £40 budget.', facts,
                                        customer_text=customer)


@pytest.mark.parametrize('prefix', ['is priced above', 'is over', 'is outside', 'exceeds'])
def test_above_budget_comparison_does_not_change_customer_budget(prefix):
    from service.grounded_money import monetary_claims_supported

    facts = [{'name': 'Summit', 'price': 35, 'currency': 'GBP'}]
    customer = ['My budget is £25.']
    assert monetary_claims_supported(
        f'With your budget of £25, Summit {prefix} your budget at £35.', facts,
        customer_text=customer)
    assert not monetary_claims_supported(
        f'Summit {prefix} your budget at £999.', facts, customer_text=customer)
    assert not monetary_claims_supported(
        'With your budget of £35, Summit costs £35.', facts, customer_text=customer)


def test_remembered_uncited_shortlist_is_not_a_new_recommendation(monkeypatch):
    from service.memory import Memory
    from service.message_handler import MessageHandler
    from tests.test_grounded_conversation import _state, _structured_answer

    knowledge = {**KNOWLEDGE, 'product:pro': {'name': 'Pro', 'price': 199, 'currency': 'GBP'}}
    payload = {'answer': 'Pro costs £199.', 'kind': 'answer', 'sources': ['product:pro'],
               'agent': _state('price', offerings=['product:basic', 'product:pro'])}
    answer, state, _, _ = _structured_answer(monkeypatch, payload, knowledge=knowledge,
        context={'offering_ids': ['product:basic', 'product:pro']})
    assert answer and state['offering_ids'] == ['product:pro']
    assert state['last_offering_ids'] == ['product:basic', 'product:pro']

    handler = object.__new__(MessageHandler)
    handler.memory = Memory()
    customer = SimpleNamespace(session_id='price-follow-up')
    handler._save_session(customer, {}, {'reply': answer, 'agent': state})
    previous = handler._load_session(customer)['sales_agent']
    context = {'previous_agent': previous, 'offering_ids': previous['offering_ids']}
    followup = {'answer': 'Pro costs £199.', 'kind': 'answer', 'sources': ['product:pro'],
                'agent': _state('checkout', offerings=['product:pro'], selected='product:pro')}
    answer, chosen, _, calls = _structured_answer(monkeypatch, followup, knowledge=knowledge,
        question="I'll take the second option.", context=context)
    assert answer and chosen['selected_offering_id'] == 'product:pro'
    assert chosen['last_offering_ids'] == ['product:basic', 'product:pro']
    assert json.loads(calls[0]['messages'][1]['content'])['agent_context']['offering_ids'] == [
        'product:basic', 'product:pro']
    followup['agent'] = _state('checkout', offerings=['product:basic'], selected='product:basic')
    followup.update(answer='Basic costs £99.', sources=['product:basic'])
    assert _structured_answer(monkeypatch, followup, knowledge=knowledge,
        question="I'll take the first option.", context=context)[1]['selected_offering_id'] == 'product:basic'
    answer,pruned,_,_ = _structured_answer(monkeypatch,payload,knowledge=knowledge)
    assert answer==payload['answer']
    assert pruned['offering_ids']==['product:pro'] and pruned['last_offering_ids']==['product:pro']


@pytest.mark.parametrize('intent', ['discover', 'recommend', 'compare'])
def test_new_grounded_choices_replace_the_previous_reference_order(monkeypatch, intent):
    from tests.test_grounded_conversation import _state, _structured_answer

    knowledge = {**KNOWLEDGE, 'product:pro': {'name': 'Pro', 'price': 199, 'currency': 'GBP'}}
    payload = {'answer': '1. Pro costs £199. 2. Basic costs £99.', 'kind': 'answer',
               'sources': ['product:pro', 'product:basic'],
               'agent': _state(intent, offerings=['product:pro', 'product:basic'])}
    answer, state, _, _ = _structured_answer(monkeypatch, payload, knowledge=knowledge,
        context={'offering_ids': ['product:basic', 'product:pro']})
    assert answer and state['last_offering_ids'] == ['product:pro', 'product:basic']


@pytest.mark.parametrize('reference', [[], ['product:deleted', 'product:basic']])
def test_explicit_or_invalid_reference_list_never_renumbers_visible_options(reference):
    context = grounded_conversation.agent_context_rows({
        'offering_ids': ['product:basic'],
        'previous_agent': {'offering_ids': ['product:basic'], 'last_offering_ids': reference},
    }, KNOWLEDGE)
    assert context['offering_ids'] == []
    raw = {'selected_offering_id': 'product:basic', 'selection_update': 'select'}
    with pytest.raises(ValueError, match='unconfirmed_agent_selection'):
        grounded_conversation._selection_state(raw, "I'll take option 1.", KNOWLEDGE, context)


def test_single_existing_recommendation_preserves_numbered_reference_list(monkeypatch):
    from tests.test_grounded_conversation import _state, _structured_answer

    knowledge = {**KNOWLEDGE, 'product:pro': {'name': 'Pro', 'price': 199, 'currency': 'GBP'}}
    payload = {'answer': 'Pro costs £199.', 'kind': 'answer', 'sources': ['product:pro'],
               'agent': _state('recommend', offerings=['product:pro'])}
    answer, state, _, _ = _structured_answer(monkeypatch, payload, knowledge=knowledge,
        context={'offering_ids': ['product:basic', 'product:pro']})
    assert answer and state['last_offering_ids'] == ['product:basic', 'product:pro']
