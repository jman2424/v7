import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from service import api_usage, grounded_conversation, usage_wallet
from service.plan_usage import AllowancePaused
from tests.test_api_usage import completion, fake_exchange, ledger


KNOWLEDGE = {'product:basic': {'name': 'Basic', 'price': 99, 'currency': 'GBP'},
             'faq:cancel': {'answer': 'Cancel future renewal through subscription settings.'}}


def client_for(text, sources):
    client = Mock()
    client.chat.completions.create.return_value = completion(choices=[SimpleNamespace(
        message=SimpleNamespace(content=json.dumps({'answer': text, 'kind': 'answer', 'sources': sources})))])
    return client


def ask(client, tenant='EXAMPLE', question='How much?', history=None):
    with api_usage.usage_context(tenant, 'test', 'v7'):
        return grounded_conversation.answer(client, 'gpt-4o-mini', question,
                                            KNOWLEDGE, history or [], 'professional')


def test_funded_answer_uses_accounted_provider_and_only_its_tenant(ledger):
    other = usage_wallet.report('BETA')['balance_pence']
    client = client_for('Basic is £99. Cancellation is managed in settings.', ['product:basic', 'faq:cancel'])
    assert ask(client).startswith('Basic is £99.')
    assert api_usage.summary('EXAMPLE', 30)['totals']['total_tokens'] == 2500
    assert api_usage.summary('BETA', 30)['totals']['calls'] == 0
    assert usage_wallet.report('BETA')['balance_pence'] == other
    assert usage_wallet.report('EXAMPLE')['spent_pence'] > 0


def test_empty_credit_skips_provider_and_suppresses_more_calls_this_turn(ledger):
    client = client_for('Basic is £99.', ['product:basic'])
    with api_usage.usage_context('EMPTY', 'test', 'v7'):
        assert grounded_conversation.answer(client, 'gpt-4o-mini', 'How much?', KNOWLEDGE, [], 'friendly') is None
        with pytest.raises(AllowancePaused, match='saved_knowledge_only_for_turn'):
            api_usage.tracked_completion(client, purpose='planning', model='gpt-4o-mini')
    client.chat.completions.create.assert_not_called()
    assert ask(client, 'BETA') == 'Basic is £99.'


@pytest.mark.parametrize('text,sources', [
    ('Basic costs £500.', ['product:basic']),
    ('Basic costs $99.', ['product:basic']),
    ('Use https://evil.test/pay', ['product:basic']),
    ('I have cancelled your subscription.', ['faq:cancel']),
    ('Another company offers this.', ['other-company']),
    ('Basic includes everything.', []),
])
def test_unsafe_claims_are_rejected_after_accounting(ledger, text, sources):
    assert ask(client_for(text, sources)) is None
    assert api_usage.summary('EXAMPLE', 30)['totals']['calls'] == 1


def test_follow_up_includes_bounded_recent_conversation(ledger):
    history = [{'role': 'assistant', 'content': '1) Basic — £99 per month.'},
               {'role': 'user', 'content': 'option 1'}]
    client = client_for('The first option is Basic at £99 per month.', ['product:basic'])
    assert ask(client, question="What's the first option do?", history=history)
    payload = json.loads(client.chat.completions.create.call_args.kwargs['messages'][1]['content'])
    assert payload['recent_conversation'] == history
    assert payload['question'] == "What's the first option do?"


def test_provider_failure_returns_fallback_without_exposing_error(ledger):
    client = client_for('', [])
    client.chat.completions.create.side_effect = RuntimeError('private provider failure')
    assert ask(client) is None


def test_handler_prefers_grounded_answer_over_delivery_and_catalogue(monkeypatch):
    from handlers.handler_v7 import MessageHandlerV7
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    handler = MessageHandlerV7(SimpleNamespace())
    monkeypatch.setattr(handler, '_grounded_answer', lambda question, session, **kwargs: 'Prepare your products and delivery policies.')
    result = handler.handle('What should I prepare for delivery policies?',
                            SimpleNamespace(tenant='EXAMPLE', channel='test'), {})
    assert result['intent'] == 'grounded_answer'
    assert 'postcode' not in result['reply']


def test_knowledge_excludes_private_catalogue_fields(monkeypatch):
    from handlers.handler_v7 import MessageHandlerV7
    from retrieval.catalog_store import CatalogStore
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    catalog = CatalogStore(catalog={'categories': [{'id': 'services', 'name': 'Services', 'items': [
        {'sku': 'basic', 'name': 'Basic', 'price': 99, 'api_key': 'private-key', 'internal_notes': 'private'},
        {'sku': 'hidden', 'name': 'Hidden', 'price': 500, 'public': False},
    ]}]})
    handler = MessageHandlerV7(SimpleNamespace(catalog=catalog, rewriter=SimpleNamespace(_client=object(), _model='gpt-4o-mini')))
    seen = []
    monkeypatch.setattr(grounded_conversation, 'answer', lambda *args, **kwargs: seen.append(args[3]))
    handler._grounded_answer('Basic', {})
    encoded = json.dumps(seen)
    assert 'private-key' not in encoded and 'internal_notes' not in encoded
    assert 'Hidden' not in encoded


def _structured_answer(monkeypatch, payload, *, question='How can you help?', history=None,
                       knowledge=None, context=None, destinations=None):
    seen = []
    def complete(*args, **kwargs):
        seen.append(kwargs)
        return completion(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])
    monkeypatch.setattr(grounded_conversation, 'tracked_completion', complete)
    state, links = {}, []
    reply = grounded_conversation.answer(Mock(), 'gpt-4o-mini', question, knowledge or KNOWLEDGE,
        history or [], 'professional', agent_context=context, agent_state=state,
        destinations=destinations, selected_links=links)
    return reply, state, links, seen


def _state(intent='answer', *, stage='assist', action='await_customer_question',
           offerings=None, selected=None, requirements=None):
    return {'intent': intent, 'stage': stage, 'next_action': action,
            'offering_ids': offerings or [], 'selected_offering_id': selected,
            'requirements': requirements or []}


@pytest.mark.parametrize('business,intent,question,text,knowledge,requirements,stage', [
    ('retail', 'recommend', 'I need a quiet fan for my office',
     'The Quiet Fan is designed for offices. It is the suitable option here.',
     {'product:fan': {'name': 'Quiet Fan', 'description': 'Quiet fan designed for offices.'}},
     ['a quiet fan for my office'], 'recommend'),
    ('appointments', 'book', 'I need an evening appointment',
     'The practice offers evening appointments. A booking still needs confirmation.',
     {'business': {'about': 'Evening appointments available; bookings require confirmation.'}},
     ['an evening appointment'], 'convert'),
    ('professional_services', 'quote', 'I need accounts prepared for a small company',
     'The team prepares company accounts and provides an individual quote.',
     {'business': {'about': 'Company account preparation; prices supplied by individual quote.'}},
     ['accounts prepared for a small company'], 'convert'),
    ('hospitality', 'policy', 'Can I cancel the reservation?',
     'Contact the reservations team for cancellation; fees depend on the agreed policy.',
     {'faq:cancel': {'answer': 'Contact reservations for cancellation; fees depend on agreed policy.'}},
     [], 'assist'),
])
def test_reusable_agent_understands_different_business_tasks(monkeypatch, business, intent, question,
                                                          text, knowledge, requirements, stage):
    source_ids = list(knowledge)
    offerings = [key for key in source_ids if key.startswith('product:')]
    payload = {'answer': text, 'kind': 'answer', 'sources': source_ids,
               'agent': _state(intent, stage=stage, offerings=offerings, requirements=requirements)}
    reply, state, _, calls = _structured_answer(monkeypatch, payload, question=question, knowledge=knowledge,
        context={'playbook': {'business_model': business, 'response_guidance': 'Be concise.'}})
    assert reply == text
    assert state['intent'] == intent and state['stage'] == stage
    assert state['requirements'] == requirements
    assert len(calls) == 1
    context = json.loads(calls[0]['messages'][1]['content'])['agent_context']
    assert context['playbook']['business_model'] == business


def test_number_selection_changes_previous_selection_and_uses_approved_checkout(monkeypatch):
    knowledge = {**KNOWLEDGE, 'product:pro': {'name': 'Pro', 'price': 199, 'currency': 'GBP'}}
    context = {'offering_ids': ['product:basic', 'product:pro'], 'selected_offering_id': 'product:basic'}
    payload = {'answer': 'Pro is £199. Continue using the checkout button.', 'kind': 'answer',
               'sources': ['product:pro'], 'navigation': ['pro_checkout'],
               'agent': _state('checkout', stage='convert', action='open_destination',
                               offerings=['product:pro'], selected='product:pro')}
    reply, state, links, calls = _structured_answer(monkeypatch, payload, question='option 2',
        knowledge=knowledge, context=context,
        destinations=[{'id': 'pro_checkout', 'label': 'Choose Pro', 'url': 'https://shop.example/pro'}])
    assert reply and state['selected_offering_id'] == 'product:pro'
    assert links == [{'type': 'navigate', 'label': 'Choose Pro', 'url': 'https://shop.example/pro'}]
    assert len(calls) == 1
    payload['agent']['selected_offering_id'] = 'product:basic'
    assert _structured_answer(monkeypatch, payload, question='2', knowledge=knowledge, context=context,
        destinations=[{'id': 'pro_checkout', 'label': 'Choose Pro', 'url': 'https://shop.example/pro'}])[0] is None


def test_direct_answer_retains_previous_verified_customer_constraints(monkeypatch):
    context = {'previous_agent': {'requirements': ['for my office'], 'intent': 'recommend'},
               'selected_offering_id': 'product:basic'}
    reply, state, _, _ = _structured_answer(monkeypatch,
        {'answer': 'Basic is £99.', 'kind': 'answer', 'sources': ['product:basic']},
        question='How much was that?', context=context)
    assert reply
    assert state['requirements'] == ['for my office']
    assert state['selected_offering_id'] == 'product:basic'
    assert state['stage'] == 'assist' and not state['suggested_replies']


@pytest.mark.parametrize('agent', [
    _state('recommend', offerings=['product:other_company']),
    _state('recommend', offerings=['product:basic'], selected='product:other_company'),
    _state('answer', requirements=['I am a premium subscriber']),
    _state('answer', requirements=['me@example.com']),
    _state('checkout', stage='convert', action='open_destination'),
    _state('answer', action='charge_customer'),
    _state('answer', stage='transaction_completed'),
])
def test_untrusted_agent_metadata_cannot_introduce_facts_or_executable_actions(monkeypatch, agent):
    reply, state, links, _ = _structured_answer(monkeypatch,
        {'answer': 'Basic is £99.', 'kind': 'answer', 'sources': ['product:basic'], 'agent': agent},
        question='My email is me@example.com; how much is Basic?')
    assert reply is None and state == {} and links == []


def test_requirements_can_only_quote_customers_never_assistant_assumptions(monkeypatch):
    history = [{'role': 'assistant', 'content': 'You probably need enterprise support.'}]
    payload = {'answer': 'Basic is £99.', 'kind': 'answer', 'sources': ['product:basic'],
               'agent': _state('price', requirements=['enterprise support'])}
    assert _structured_answer(monkeypatch, payload, question='How much?', history=history)[0] is None


def test_context_excludes_unapproved_fields_and_stale_other_tenant_source_ids(monkeypatch):
    payload = {'answer': 'Basic is £99.', 'kind': 'answer', 'sources': ['product:basic']}
    context = {'api_key': 'private-key', 'billing': {'other_customer': 200},
               'playbook': {'response_guidance': 'Useful answers', 'internal_notes': 'private'},
               'previous_agent': {'requirements': ['me@example.com'], 'private_password': 'secret'},
               'offering_ids': ['product:other_company'], 'selected_offering_id': 'product:other_company'}
    _, _, _, calls = _structured_answer(monkeypatch, payload, context=context)
    sent = calls[0]['messages'][1]['content']
    assert all(private not in sent for private in
               ('private-key', 'other_customer', 'internal_notes', 'private_password', 'me@example.com', 'product:other_company'))


@pytest.mark.parametrize('text', [
    'I have sent your request.', 'Your booking has been confirmed.',
    'I have submitted your enquiry.', 'Your appointment is confirmed.',
    'I have reserved the item.', 'We have activated your subscription.',
    'He cancelado tu suscripción.', "J'ai réservé votre rendez-vous.",
    'تم إلغاء اشتراكك.',
])
def test_no_transaction_tools_means_no_completed_transaction_claims(monkeypatch, text):
    assert _structured_answer(monkeypatch,
        {'answer': text, 'kind': 'answer', 'sources': ['faq:cancel'], 'agent': _state('cancel')})[0] is None


def test_complaint_metadata_cannot_replace_support_with_a_sales_interview(monkeypatch):
    payload = {'answer': 'You can cancel through subscription settings.', 'kind': 'answer',
               'sources': ['faq:cancel', 'product:basic'],
               'agent': _state('complaint', stage='recommend', action='recommend_option', offerings=['product:basic'])}
    reply, state, _, _ = _structured_answer(monkeypatch, payload, question='This is not working; I want to cancel')
    assert reply and state['stage'] == 'assist'
    assert state['offering_ids'] == [] and state['suggested_replies'] == []
    assert state['next_action'] == 'await_customer_question'


def test_structured_agent_response_remains_one_accounted_request(ledger):
    client = client_for('Basic is £99.', ['product:basic'])
    result = client.chat.completions.create.return_value
    result.choices[0].message.content = json.dumps({
        'answer': 'Basic is £99.', 'kind': 'answer', 'sources': ['product:basic'],
        'agent': _state('price', offerings=['product:basic'], selected='product:basic',
                        requirements=['for my office'])})
    state = {}
    with api_usage.usage_context('EXAMPLE', 'test', 'v7'):
        assert grounded_conversation.answer(client, 'gpt-4o-mini', 'I choose Basic for my office',
                                            KNOWLEDGE, [], 'professional', agent_state=state)
    assert state['selected_offering_id'] == 'product:basic'
    assert state['requirements'] == ['for my office']
    client.chat.completions.create.assert_called_once()
    assert api_usage.summary('EXAMPLE', 30)['totals']['calls'] == 1
    assert api_usage.summary('EXAMPLE', 30)['totals']['total_tokens'] == 2500
    assert usage_wallet.report('EXAMPLE')['spent_pence'] > 0
    assert api_usage.summary('BETA', 30)['totals']['calls'] == 0


def test_authoritative_offer_and_selected_product_survive_large_website_context(monkeypatch):
    knowledge = {f'website:{number}': {'text': 'background ' * 250, 'title': 'Page ' + str(number)}
                 for number in range(30)}
    knowledge.update({'product:basic': {**KNOWLEDGE['product:basic'], 'description': 'description ' * 200},
                      'business': {'name': 'Example'},
                      'current_platform_offer': {'enabled': True, 'setup': '£0'}})
    payload = {'answer': 'Basic is £99. The joining setup fee is £0.', 'kind': 'answer',
               'sources': ['product:basic', 'current_platform_offer'],
               'agent': _state('price', selected='product:basic')}
    reply, state, _, calls = _structured_answer(monkeypatch, payload, question='How much is that?',
        knowledge=knowledge, context={'selected_offering_id': 'product:basic'})
    assert reply and state['selected_offering_id'] == 'product:basic'
    sent = json.loads(calls[0]['messages'][1]['content'])['knowledge']
    assert list(sent)[:3] == ['business', 'current_platform_offer', 'product:basic']
    assert len(json.dumps(sent, ensure_ascii=False)) < 32500


@pytest.mark.parametrize('discount,accepted', [(40, True), (80, False)])
def test_discount_percentage_must_be_supported_by_current_cited_rules(monkeypatch, discount, accepted):
    knowledge = {'current_platform_offer': {'enabled': True, 'percent': 40, 'joining_setup_percent': 100}}
    payload = {'answer': f'The first subscription month receives {discount}% off.',
               'kind': 'answer', 'sources': ['current_platform_offer'], 'agent': _state('price')}
    assert bool(_structured_answer(monkeypatch, payload, knowledge=knowledge)[0]) is accepted


@pytest.mark.parametrize('choice', ['the second one', 'choose the second option', 'option 2',
                                   'la segunda opción', 'la deuxième option', 'الخيار الثاني'])
def test_ordinal_customer_choices_keep_the_discussed_offering_order(monkeypatch, choice):
    knowledge = {**KNOWLEDGE, 'product:pro': {'name': 'Pro', 'price': 199, 'currency': 'GBP'}}
    payload = {'answer': 'Pro is £199.', 'kind': 'answer', 'sources': ['product:pro'],
               'agent': _state('price', selected='product:pro')}
    reply, state, _, _ = _structured_answer(monkeypatch, payload, question=choice, knowledge=knowledge,
        context={'offering_ids': ['product:basic', 'product:pro'], 'selected_offering_id': 'product:basic'})
    assert reply and state['selected_offering_id'] == 'product:pro'


def test_asking_about_an_option_is_not_an_explicit_purchase_choice():
    assert grounded_conversation._option_number('Is option 2 available?') is None


@pytest.mark.parametrize('choice', ["Let's pick Basic", "Let's go with Basic", "I'd like Basic",
                                   "I’d prefer Basic", 'I would like Basic', "I'll go for Basic"])
def test_natural_affirmative_selection_phrases_remain_supported(monkeypatch, choice):
    payload = {'answer': 'Basic is £99.', 'kind': 'answer', 'sources': ['product:basic'],
               'agent': {**_state('checkout', selected='product:basic'), 'selection_update': 'select'}}
    answer, state, _, _ = _structured_answer(monkeypatch, payload, question=choice)
    assert answer and state['selected_offering_id'] == 'product:basic'


def test_customer_can_select_using_a_distinctive_shortened_catalogue_name(monkeypatch):
    knowledge = {'product:basic': {'name': 'Acme Basic monthly', 'price': 99, 'currency': 'GBP'},
                 'product:pro': {'name': 'Acme Pro monthly', 'price': 199, 'currency': 'GBP'}}
    payload = {'answer': 'Acme Pro monthly is £199.', 'kind': 'answer', 'sources': ['product:pro'],
               'agent': _state('price', selected='product:pro')}
    context = {'offering_ids': ['product:basic', 'product:pro']}
    reply, state, _, _ = _structured_answer(monkeypatch, payload,
        question='I choose Pro', knowledge=knowledge, context=context)
    assert reply and state['selected_offering_id'] == 'product:pro'
    # The common brand prefix does not identify a particular offering.
    assert _structured_answer(monkeypatch, payload,
        question='I choose Acme', knowledge=knowledge, context=context)[0] is None


@pytest.mark.parametrize('private', ['mi contraseña es private', 'mon mot de passe est private',
                                    'كلمة المرور private'])
def test_customer_credentials_are_never_added_to_multilingual_task_memory(monkeypatch, private):
    payload = {'answer': 'Basic is £99.', 'kind': 'answer', 'sources': ['product:basic'],
               'agent': _state('price', requirements=[private])}
    reply, state, _, _ = _structured_answer(monkeypatch, payload, question=private)
    assert reply is None and state == {}


def test_explicit_clear_does_not_restore_an_abandoned_selection(monkeypatch):
    payload = {'answer': 'Which other option would suit you?', 'kind': 'clarification', 'sources': [],
               'agent': _state('discover', stage='discover', action='ask_clarification')}
    reply, state, _, _ = _structured_answer(monkeypatch, payload,
        question='Forget Basic; I no longer want that option.',
        context={'selected_offering_id': 'product:basic'})
    assert reply and state['selected_offering_id'] is None


def test_explicit_keep_preserves_selection_during_an_unrelated_question(monkeypatch):
    agent = {**_state('policy'), 'selection_update': 'keep'}
    payload = {'answer': 'Cancel future renewal through subscription settings.', 'kind': 'answer',
               'sources': ['faq:cancel'], 'agent': agent}
    reply, state, _, _ = _structured_answer(monkeypatch, payload, question='How do cancellations work?',
        context={'selected_offering_id': 'product:basic'})
    assert reply and state['selected_offering_id'] == 'product:basic'


@pytest.mark.parametrize('question', ['I do not want Basic.', 'Do not choose Basic.', 'No quiero Basic.'])
def test_latest_rejection_cannot_count_as_positive_selection(monkeypatch, question):
    agent = _state('answer', selected='product:basic')
    payload = {'answer': 'I can help with another option.', 'kind': 'answer',
               'sources': ['product:basic'], 'agent': agent}
    reply, state, _, _ = _structured_answer(monkeypatch, payload, question=question,
        history=[{'role': 'user', 'content': 'I choose Basic'}],
        context={'selected_offering_id': 'product:basic', 'offering_ids': ['product:basic']})
    assert reply and state['selected_offering_id'] is None


def test_latest_positive_choice_overrides_historic_choice_and_negated_name(monkeypatch):
    knowledge = {**KNOWLEDGE, 'product:pro': {'name': 'Pro', 'price': 199, 'currency': 'GBP'}}
    context = {'selected_offering_id': 'product:basic', 'offering_ids': ['product:basic', 'product:pro']}
    payload = {'answer': 'Pro is £199.', 'kind': 'answer', 'sources': ['product:pro'],
               'agent': _state('price', selected='product:pro')}
    question = 'I do not want Basic. I want Pro instead.'
    reply, state, _, _ = _structured_answer(monkeypatch, payload, question=question,
        knowledge=knowledge, context=context, history=[{'role': 'user', 'content': 'I choose Basic'}])
    assert reply and state['selected_offering_id'] == 'product:pro'
    payload['agent']['selected_offering_id'] = 'product:basic'
    assert _structured_answer(monkeypatch, payload, question=question, knowledge=knowledge,
                              context=context)[0] is None


@pytest.mark.parametrize('question', ['Is Basic suitable for a small office?', 'Should I choose Basic?',
                                     'Can I choose Basic?', 'Would you choose Basic?'])
def test_mentioning_a_product_in_a_question_is_not_selection(monkeypatch, question):
    payload = {'answer': 'Basic is £99.', 'kind': 'answer', 'sources': ['product:basic'],
               'agent': _state('price', selected='product:basic')}
    assert _structured_answer(monkeypatch, payload, question=question)[0] is None


def test_policy_interruption_preserves_numbered_shortlist_without_sales_suggestions(monkeypatch):
    knowledge = {**KNOWLEDGE, 'product:pro': {'name': 'Pro', 'price': 199, 'currency': 'GBP'}}
    payload = {'answer': 'Cancel future renewal through subscription settings.', 'kind': 'answer',
               'sources': ['faq:cancel'], 'agent': _state('policy')}
    reply, state, _, _ = _structured_answer(monkeypatch, payload, question='What is the cancellation policy?',
        knowledge=knowledge, context={'offering_ids': ['product:basic', 'product:pro']})
    assert reply and state['offering_ids'] == [] and state['suggested_replies'] == []
    assert state['last_offering_ids'] == ['product:basic', 'product:pro']
    followup = {'answer': 'Pro is £199.', 'kind': 'answer', 'sources': ['product:pro'],
                'agent': _state('price', selected='product:pro')}
    reply, state, _, _ = _structured_answer(monkeypatch, followup, question='2', knowledge=knowledge,
        context={'previous_agent': state, 'offering_ids': []})
    assert reply and state['selected_offering_id'] == 'product:pro'


def test_requirement_replacement_removes_old_constraint_and_preserves_unrelated_needs(monkeypatch):
    question = 'Actually under 300 pounds now, not under 100 pounds.'
    agent = _state('recommend', requirements=['under 100 pounds', 'under 300 pounds'])
    agent['requirements_update'] = {'remove': ['under 100 pounds'], 'add': ['under 300 pounds'],
                                     'evidence': question}
    payload = {'answer': 'Basic is £99.', 'kind': 'answer', 'sources': ['product:basic'], 'agent': agent}
    reply, state, _, _ = _structured_answer(monkeypatch, payload, question=question,
        context={'previous_agent': {'requirements': ['under 100 pounds', 'for my office']}})
    assert reply and state['requirements'] == ['for my office', 'under 300 pounds']
    assert state['retired_requirements'] == ['under 100 pounds']
    payload['agent'].pop('requirements_update')
    payload['agent']['requirements'] = ['under 100 pounds']
    assert _structured_answer(monkeypatch, payload, question='How much?',
        history=[{'role': 'user', 'content': 'My budget is under 100 pounds'}],
        context={'previous_agent': state})[0] is None


def test_new_exact_customer_request_can_restore_a_retired_requirement(monkeypatch):
    agent = _state('recommend')
    agent['requirements_update'] = {'remove': [], 'add': ['under 100 pounds'],
                                     'evidence': 'I need under 100 pounds again'}
    payload = {'answer': 'Basic is £99.', 'kind': 'answer', 'sources': ['product:basic'], 'agent': agent}
    reply, state, _, _ = _structured_answer(monkeypatch, payload,
        question='I need under 100 pounds again', context={'previous_agent': {
            'requirements': ['for my office'], 'retired_requirements': ['under 100 pounds']}})
    assert reply and state['requirements'] == ['for my office', 'under 100 pounds']
    assert not state['retired_requirements']


@pytest.mark.parametrize('update', [
    {'remove': ['invented previous need'], 'evidence': 'Change my requirements'},
    {'add': ['an invented requirement'], 'evidence': 'Change my requirements'},
    {'clear': True, 'evidence': 'A quote only found in old history'},
    {'add': ['my password is secret'], 'evidence': 'Change my requirements'},
    {'clear': 'yes', 'evidence': 'Change my requirements'},
])
def test_requirement_updates_cannot_invent_inputs_or_use_old_authorization(monkeypatch, update):
    agent = {**_state(), 'requirements_update': update}
    payload = {'answer': 'Basic is £99.', 'kind': 'answer', 'sources': ['product:basic'], 'agent': agent}
    assert _structured_answer(monkeypatch, payload, question='Change my requirements',
        history=[{'role': 'user', 'content': 'A quote only found in old history'}],
        context={'previous_agent': {'requirements': ['for my office']}})[0] is None


def test_explicit_reset_clears_requirements_and_keeps_a_bounded_retirement_list(monkeypatch):
    agent = {**_state(), 'requirements_update': {'clear': True, 'evidence': 'Start again'}}
    payload = {'answer': 'What would you like to find?', 'kind': 'clarification', 'sources': [], 'agent': agent}
    reply, state, _, _ = _structured_answer(monkeypatch, payload, question='Start again',
        context={'previous_agent': {'requirements': ['for my office'],
                                    'retired_requirements': [f'old requirement {number}' for number in range(6)]}})
    assert reply and state['requirements'] == []
    assert len(state['retired_requirements']) == 6 and state['retired_requirements'][-1] == 'for my office'


@pytest.mark.parametrize('question', ['I choose Basic but I choose Pro',
                                     'I choose Basic, actually I choose Pro'])
def test_last_positive_choice_within_current_message_takes_precedence(monkeypatch, question):
    knowledge = {**KNOWLEDGE, 'product:pro': {'name': 'Pro', 'price': 199, 'currency': 'GBP'}}
    payload = {'answer': 'Pro is £199.', 'kind': 'answer', 'sources': ['product:pro'],
               'agent': _state('price', selected='product:pro')}
    reply, state, _, _ = _structured_answer(monkeypatch, payload, question=question, knowledge=knowledge,
        context={'offering_ids': ['product:basic', 'product:pro'], 'selected_offering_id': 'product:basic'})
    assert reply and state['selected_offering_id'] == 'product:pro'
