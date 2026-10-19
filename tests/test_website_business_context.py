"""Website facts follow the configured business, independently of its niche."""
import json
from types import SimpleNamespace

import pytest

from handlers.handler_v7 import MessageHandlerV7
from retrieval.storage import Storage
from service import grounded_conversation
from service.website_knowledge import current_website_knowledge, relevant_passages
from tests.test_widget_tenancy import _add_tenant


def imported(url='https://business.example/', text='Roof surveys include a written inspection report.'):
    return {'source_url':url, 'pages':[{'url':url+'services', 'title':'Services', 'text':text}]}


@pytest.mark.parametrize('configured', [None, '', 'https://other.example/', 'https://business.example/new'])
def test_import_is_not_used_after_source_changes(configured):
    assert current_website_knowledge(imported(), configured) == {}


def test_current_import_normalizes_host_but_excludes_other_sites():
    knowledge = imported()
    knowledge['pages'] += [{'url':'https://other.example/', 'text':'Other business private facts.'}]
    result = current_website_knowledge(knowledge, 'https://BUSINESS.example')
    assert len(result['pages']) == 1 and result['pages'][0]['text'].startswith('Roof surveys')
    assert len(knowledge['pages']) == 2  # Do not mutate stored imports.


@pytest.mark.parametrize('question', ['What do you sell?', 'What do you do?',
                                    'Tell me about your services.'])
def test_business_overview_uses_website_even_without_literal_keyword_overlap(question):
    result = relevant_passages(imported(), question)
    assert len(result) == 1 and 'Roof surveys' in result[0]['text']


@pytest.mark.parametrize('question', ['hello', 'green = good', 'make me a Python calculator',
                                    "how'd your day go"])
def test_website_overview_does_not_become_an_unrelated_chat_fallback(question):
    assert relevant_passages(imported(), question) == []


def agent(storage, website):
    catalog = SimpleNamespace(storage=storage, categories=lambda:[], search=lambda **kw:[],
        list_all_items=lambda:[], currency=lambda:'GBP')
    return MessageHandlerV7(SimpleNamespace(catalog=catalog, business_profile={'website':website},
        rewriter=SimpleNamespace(_client=object(), _model='test-model')))


@pytest.mark.parametrize('question,fact', [
    ('What do roof surveys include?', 'Roof surveys include a written inspection report.'),
    ('What does studio hire include?', 'Studio hire includes lighting and a private changing room.'),
    ('What does garden maintenance include?', 'Garden maintenance includes lawn mowing and hedge trimming.'),
])
def test_real_handler_uses_its_own_imported_website_facts(app, monkeypatch, question, fact):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    _add_tenant(app)
    storage = Storage('EXAMPLE')
    storage.write_json('EXAMPLE', 'website_knowledge.json', imported(text=fact))
    storage.write_json('ALT', 'website_knowledge.json', imported('https://other.example/', 'Unrelated tenant facts.'))
    seen = []
    def complete(*args, **kwargs):
        payload = json.loads(kwargs['messages'][1]['content'])
        seen.append(payload)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({
            'kind':'answer', 'answer':fact, 'sources':['website:0']})))])
    monkeypatch.setattr(grounded_conversation, 'tracked_completion', complete)
    result = agent(storage, 'https://business.example/')._grounded_answer(question, {})
    assert fact in result['reply']
    assert fact in json.dumps(seen[0]['knowledge'])
    assert 'Unrelated tenant facts' not in json.dumps(seen)


def test_handler_and_owner_summary_reject_an_old_source(app, client, monkeypatch):
    from tests.conftest import set_test_identity
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    storage = app.container.storage
    storage.write_json('EXAMPLE', 'website_knowledge.json', imported())
    profile = storage.read_json('EXAMPLE', 'store_info.json')
    profile['website'] = 'https://new-business.example/'
    storage.write_json('EXAMPLE', 'store_info.json', profile)
    assert agent(Storage('EXAMPLE'), profile['website']).website_knowledge == {}
    with client.session_transaction() as state:
        set_test_identity(client, state, {'id':'operator', 'roles':['platform_admin'], 'tenant':'EXAMPLE'})
    summary = client.get('/admin/api/website-knowledge?tenant=EXAMPLE')
    assert summary.status_code == 200 and summary.json['source_current'] is False
    assert summary.json['page_count'] == 1
