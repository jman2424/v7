"""Only complete curated answers qualify as authoritative policy text."""
import json
from types import SimpleNamespace

import pytest

from handlers.handler_v7 import MessageHandlerV7
from service import grounded_conversation


@pytest.mark.parametrize('raw,complete', [
    ('Return unused items within 30 days. Except personalised items.', True),
    ('x' * 2000, True), ('x' * 2000 + ' Except personalised items.', False),
    ('', False), (' \n ', False), (None, False), (7, False),
])
def test_faq_projection_retains_original_completeness(monkeypatch, raw, complete):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    handler = MessageHandlerV7(SimpleNamespace(
        rewriter=SimpleNamespace(_client=object(), _model='test-model')))
    rows = [{'q': 'Returns?', 'a': raw}, {'q': 'Private?', 'a': 'hidden-policy', 'public': False}]
    handler.faq = SimpleNamespace(best_match=lambda question, top_k: rows, all=lambda: rows)
    seen = []
    monkeypatch.setattr(grounded_conversation, 'answer', lambda *args, **kwargs: seen.append(args[3]))
    handler._grounded_answer('How do returns work?', {})
    knowledge = grounded_conversation.bounded_knowledge(seen[0])
    for key in ('matched_faq:0',):
        assert knowledge[key]['answer'] == str(raw or '')[:2000]
        assert knowledge[key]['answer_complete'] is complete
    assert 'faq:0' not in knowledge
    assert 'hidden-policy' not in json.dumps(knowledge)
