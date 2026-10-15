"""Mirrored public offering records must not make a clear choice ambiguous."""
from tests.test_grounded_conversation import _state, _structured_answer


def test_equivalent_native_and_catalogue_references_keep_a_natural_customer_choice(monkeypatch):
    knowledge = {'product:starter': {'name': 'Fixture Starter monthly', 'price': 99, 'currency': 'GBP'},
                 'offering:starter': {'name': 'Fixture Starter monthly', 'price': 99, 'currency': 'GBP'}}
    payload = {'answer': 'Starter is £99 per month.', 'kind': 'answer', 'sources': ['offering:starter'],
               'agent': {**_state('checkout', selected='offering:starter'), 'selection_update': 'select'}}
    answer, state, _, _ = _structured_answer(monkeypatch, payload, question="Let's pick Starter.",
        knowledge=knowledge, context={'offering_ids': ['product:starter']})
    assert answer and state['selected_offering_id'] in knowledge


def test_same_label_with_different_price_is_not_an_equivalent_selection(monkeypatch):
    knowledge = {'product:starter': {'name': 'Fixture Starter monthly', 'price': 99, 'currency': 'GBP'},
                 'offering:starter': {'name': 'Fixture Starter monthly', 'price': 149, 'currency': 'GBP'}}
    payload = {'answer': 'Starter is £149 per month.', 'kind': 'answer', 'sources': ['offering:starter'],
               'agent': {**_state('checkout', selected='offering:starter'), 'selection_update': 'select'}}
    assert _structured_answer(monkeypatch, payload, question="Let's pick Starter.",
        knowledge=knowledge, context={'offering_ids': ['product:starter']})[0] is None
