"""Reduce duplicate provider input without dropping or weakening business facts."""
import copy
import json

from service.agent_response_schema import response_format
from service.grounded_statements import prompt_statements, statement_catalog
from tests.test_grounded_statements import RETURNS, run


def test_exact_policy_wording_is_sent_once_and_still_rendered_in_full(monkeypatch):
    knowledge = {'faq:returns': {'question': 'What is the returns policy?', 'answer': RETURNS}}
    original = copy.deepcopy(knowledge)
    answer, _, diagnostics, calls = run(monkeypatch, knowledge, text=RETURNS,
        question='What is the returns policy?', sources=['faq:returns'], ids=['faq:returns:answer'])
    sent = json.loads(calls[0]['messages'][1]['content'])
    assert diagnostics['accepted'] and answer == RETURNS
    assert sent['knowledge']['faq:returns']['answer'] == RETURNS
    assert sent['approved_statements']['faq:returns:answer'] == {
        'source_id': 'faq:returns', 'text_from_knowledge': 'answer'}
    assert calls[0]['messages'][1]['content'].count(RETURNS) == 1
    assert list(sent)[-1] == 'question'
    assert knowledge == original


def test_only_complete_identical_fields_can_replace_duplicate_statement_text():
    text = 'Published delivery details remain complete, including every condition and exception.'
    knowledge = {'delivery': {'statement': text, 'notes': 'Keep these separate notes.'},
                 'faq:other': {'answer': text + ' Additional conditions.'}}
    statements = {'delivery:answer': {'source_id': 'delivery', 'text': text},
                  'faq:other:answer': {'source_id': 'faq:other', 'text': text},
                  'unknown': {'source_id': 'missing', 'text': text}}
    original = copy.deepcopy(statements)
    result = prompt_statements(knowledge, statements)
    assert result['delivery:answer']['text_from_knowledge'] == 'statement'
    assert result['faq:other:answer']['text'] == text
    assert result['unknown']['text'] == text
    assert statements == original and knowledge['delivery']['notes'] == 'Keep these separate notes.'


def test_large_faq_context_preserves_every_word_with_less_duplicate_input():
    knowledge = {f'faq:{index}': {'question': f'Policy {index}?',
                 'answer': (f'Published condition {index}: ' + 'retain every condition and exclusion. ' * 28)}
                 for index in range(12)}
    statements = statement_catalog(knowledge)
    before = json.dumps({'knowledge': knowledge, 'approved_statements': statements})
    compact = prompt_statements(knowledge, statements)
    after = json.dumps({'knowledge': knowledge, 'approved_statements': compact})
    assert len(after.encode()) < len(before.encode()) * .65
    for identifier, original in statements.items():
        reference = compact[identifier]
        restored = knowledge[reference['source_id']][reference['text_from_knowledge']].strip()
        assert restored == original['text']


def test_schema_cache_prefix_is_stable_for_the_same_evidence_in_a_different_rank_order():
    knowledge = {'product:z': {'name': 'Z'}, 'product:a': {'name': 'A'},
                 'faq:one': {'answer': 'Policy facts.'}}
    destinations = [{'id': 'z', 'url': 'https://example.test/z'},
                    {'id': 'a', 'url': 'https://example.test/a'}]
    arguments = dict(intents={'answer'}, stages={'assist'}, actions={'answer'})
    first = response_format(knowledge, destinations, [], **arguments)
    second = response_format(dict(reversed(list(knowledge.items()))), list(reversed(destinations)), [], **arguments)
    assert first == second
    assert first['json_schema']['schema']['properties']['sources']['items']['enum'] == sorted(knowledge)
    properties = list(first['json_schema']['schema']['properties'])
    assert properties.index('sources') < properties.index('agent') < properties.index('answer')


def test_catalogue_related_reads_share_one_fresh_document_and_next_turn_sees_edits(app, monkeypatch):
    from retrieval.catalog_store import CatalogStore
    from handlers.handler_v7 import MessageHandlerV7
    source = {'version': 1, 'currency': 'GBP', 'categories': [{'id': 'coatings', 'name': 'Coatings',
              'items': [{'sku': 'entry', 'name': 'Entry Coating', 'price': 100, 'unit': 'vehicle'}]}]}
    reads = []
    storage = app.container.storage
    original_read = type(storage).read_json

    def read(instance, tenant, filename):
        if instance is not storage:
            return original_read(instance, tenant, filename)
        assert tenant == 'EXAMPLE' and filename == 'catalog.json'
        reads.append((tenant, filename))
        return copy.deepcopy(source)

    monkeypatch.setattr(type(storage), 'read_json', read)
    live = CatalogStore(storage)
    reads.clear()
    first = live.snapshot()
    handler = object.__new__(MessageHandlerV7)
    handler.catalog = live
    assert handler._exact_catalog_item_in_text('Entry Coating', catalog=first)['sku'] == 'entry'
    assert handler._looks_like_product_query('Entry Coating', catalog=first)
    assert first.get_item_by_sku('entry')['price'] == 100
    assert first.search(text='Coating', limit=9)
    assert first.list_all_items() and first.currency() == 'GBP'
    assert len(reads) == 1
    source['categories'][0]['items'][0]['price'] = 200
    assert first.get_item_by_sku('entry')['price'] == 100, 'One answer keeps its consistent snapshot'
    second = live.snapshot()
    assert second.get_item_by_sku('entry')['price'] == 200, 'Next turn must read current facts'
    assert len(reads) == 2


def test_informational_quote_reply_ignores_stray_form_step_without_opening_a_form(monkeypatch):
    from tests.test_grounded_conversation import _state
    answer, state, diagnostics, calls = run(monkeypatch,
        {'policy:quotes': {'answer': 'Bespoke work is priced by quote after the team reviews the project scope.'}},
        question='How much does a bespoke website cost?',
        text='Bespoke work is priced by quote after the team reviews the project scope.',
        sources=['policy:quotes'], ids=['policy:quotes:answer'],
        agent=_state('quote', action='open_request_form'), allowed_actions=['quote'])
    assert diagnostics['accepted'] and 'quote' in answer.lower()
    assert state['next_action'] == 'await_customer_question'
    assert not state.get('requested_action') and not state['navigation_ids']
    assert len(calls) == 1


def test_missing_form_action_on_an_explicit_request_still_fails_closed(monkeypatch):
    from tests.test_grounded_conversation import _state
    answer, _, diagnostics, _ = run(monkeypatch,
        {'policy:quotes': {'answer': 'The team reviews quote requests.'}},
        question='Please open the quote request form.', text='The team reviews quote requests.',
        sources=['policy:quotes'], ids=['policy:quotes:answer'],
        agent=_state('quote', action='open_request_form'), allowed_actions=['quote'])
    assert answer is None and diagnostics['rejection_reason'] == 'missing_requested_action'
