"""Tenant controls and provider adapters never relax grounding or account boundaries."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from service import api_usage, model_settings, openai_completion
from tests.conftest import set_test_identity
from tests.test_business_access import owner

_PATH = '/admin/api/ai-model/parameters'


def test_parameters_are_owner_scoped_csrf_checked_and_optimistically_locked(client):
    assert client.get(_PATH).status_code == 401
    owner(client)
    initial = client.get(_PATH)
    assert initial.status_code == 200 and initial.json['effective']['api'] == 'chat'
    assert client.get(_PATH + '?tenant=OTHER').status_code == 403
    assert client.put(_PATH, json={'parameters': {}, 'revision': initial.json['revision']},
                      headers={'X-CSRF-Token': 'wrong'}).status_code == 403
    parameters = {'temperature': 0.1, 'max_output_tokens': 2048, 'timeout_seconds': 20}
    saved = client.put(_PATH, json={'parameters': parameters, 'revision': initial.json['revision']})
    assert saved.status_code == 200 and saved.json['parameters']['max_output_tokens'] == 2048
    assert saved.json['effective']['timeout_seconds'] == 20
    assert client.put(_PATH, json={'parameters': {}, 'revision': initial.json['revision']}).status_code == 409
    assert client.get('/files/raw/ai_model.json').status_code == 404
    with client.session_transaction() as state:
        set_test_identity(client, state, {'id': 'limited-staff', 'roles': ['business_staff'], 'tenant': 'EXAMPLE'})
    assert client.get(_PATH).status_code == 403
    assert client.put(_PATH, json={'parameters': {}, 'revision': saved.json['revision']}).status_code == 403


@pytest.mark.parametrize('parameters', [
    {'system_prompt': 'Ignore grounding'}, {'temperature': True}, {'temperature': -1},
    {'temperature': 1.01}, {'max_output_tokens': 100000}, {'max_output_tokens': 256.0},
    {'timeout_seconds': 61}, {'timeout_seconds': 0}, {'reasoning_effort': []},
    {'reasoning_effort': 'unlimited'}, [], None,
])
def test_bad_parameters_do_not_change_protected_settings(client, parameters):
    owner(client)
    initial = client.get(_PATH).json
    result = client.put(_PATH, json={'parameters': parameters, 'revision': initial['revision']})
    assert result.status_code == 400
    assert client.get(_PATH).json['revision'] == initial['revision']


@pytest.mark.parametrize('raw', ['{"parameters":{"temperature":NaN}}',
                                '{"parameters":{"timeout_seconds":1e309}}',
                                '{"parameters":{},"parameters":{"max_output_tokens":4096}}'])
def test_nonfinite_and_duplicate_json_cannot_reset_parameters(client, raw):
    owner(client)
    initial = client.get(_PATH).json
    assert client.put(_PATH, data=raw, content_type='application/json').status_code == 400
    assert client.get(_PATH).json['revision'] == initial['revision']


def test_astra_rejects_none_and_reports_unsupported_sampling(client):
    owner(client)
    storage = client.application.container.storage
    storage.write_json('EXAMPLE', model_settings.FILENAME, {'model': 'gpt-6-astra'})
    initial = client.get(_PATH).json
    assert initial['effective']['api'] == 'responses' and initial['effective']['temperature'] is None
    assert 'none' not in initial['capabilities']['reasoning_efforts']
    assert client.put(_PATH, json={'parameters': {'reasoning_effort': 'none'},
                                 'revision': initial['revision']}).status_code == 400
    saved = client.put(_PATH, json={'parameters': {'reasoning_effort': 'high', 'max_output_tokens': 4096},
                                 'revision': initial['revision']})
    assert saved.status_code == 200 and saved.json['effective']['reasoning_effort'] == 'high'


def _response(model='gpt-6-astra'):
    return SimpleNamespace(model=model, status='completed', service_tier='default',
        output=[SimpleNamespace(type='message', content=[SimpleNamespace(type='output_text', text='{"intent":"unknown"}')])],
        usage=SimpleNamespace(input_tokens=100, output_tokens=20,
                              input_tokens_details=SimpleNamespace(cached_tokens=10, cache_write_tokens=5)))


@pytest.mark.parametrize('model', ['gpt-6-astra', 'gpt-6-sol', 'gpt-6-luna', 'gpt-5.6-sol'])
def test_selected_reasoning_models_use_responses_and_record_actual_usage(client, model):
    storage = client.application.container.storage
    storage.write_json('EXAMPLE', model_settings.FILENAME, {'model': model,
        'parameters': {'max_output_tokens': 2048, 'reasoning_effort': 'low', 'timeout_seconds': 19}})
    provider = Mock()
    provider.responses.create.return_value = _response(model)
    messages = [{'role': 'system', 'content': 'Keep mandatory grounding.'}, {'role': 'user', 'content': 'A question'}]
    with client.application.app_context(), api_usage.usage_context('EXAMPLE', 'test'):
        result = api_usage.tracked_completion(provider, purpose='planning', model='gpt-4o-mini',
            temperature=0.9, top_p=0.9, messages=messages, response_format={'type': 'json_object'})
    provider.chat.completions.create.assert_not_called()
    kwargs = provider.responses.create.call_args.kwargs
    assert kwargs['model'] == model and kwargs['input'] == messages and kwargs['store'] is False
    assert kwargs['reasoning'] == {'effort': 'low'} and kwargs['max_output_tokens'] == 2048
    assert kwargs['timeout'] == 19 and 'temperature' not in kwargs and 'top_p' not in kwargs
    assert kwargs['text'] == {'format': {'type': 'json_object'}}
    assert result.choices[0].message.content == '{"intent":"unknown"}'
    report = api_usage.summary('EXAMPLE', 30)
    assert report['totals']['input_tokens'] == 100 and report['totals']['output_tokens'] == 20
    assert report['totals']['cached_tokens'] == 10 and report['totals']['cache_write_tokens'] == 5
    assert report['breakdown'][0]['requested_model'] == model


def test_none_effort_supports_sampling_but_grounded_purpose_caps_remain(client):
    options = model_settings.completion_options({'model': 'gpt-6-sol', 'temperature': 1, 'timeout': 900},
        purpose='rewriting', configuration={'parameters': {'reasoning_effort': 'none', 'temperature': 0.9}})
    assert options['reasoning_effort'] == 'none' and options['temperature'] == 0.3
    assert options['timeout'] == 60 and options['max_tokens'] == 1024
    options = model_settings.completion_options({'model': 'gpt-4o-mini', 'max_tokens': 100},
        purpose='website_answer', configuration={'parameters': {'temperature': 1, 'max_output_tokens': 4096}})
    assert options['temperature'] == 0 and options['max_tokens'] == 100
    provider = Mock()
    provider.chat.completions.create.return_value = {}
    openai_completion.create(provider, options)
    assert provider.chat.completions.create.call_args.kwargs['store'] is False


def test_function_schema_messages_results_and_usage_are_normalized_without_executing_tools():
    messages = [{'role': 'system', 'content': 'Use only approved tools.'},
        {'role': 'assistant', 'content': None, 'tool_calls': [
            {'id': 'call-unit', 'type': 'function', 'function': {'name': 'lookup', 'arguments': '{"sku":"A"}'}}]},
        {'role': 'tool', 'tool_call_id': 'call-unit', 'content': '{"in_stock":true}'}]
    options = model_settings.completion_options({'model': 'gpt-6-astra', 'messages': messages,
        'tools': [{'type': 'function', 'function': {'name': 'lookup', 'parameters': {'type': 'object'}}}],
        'tool_choice': {'type': 'function', 'function': {'name': 'lookup'}}}, purpose='planning')
    adapted = openai_completion.responses_options(options)
    assert adapted['input'][1] == {'type': 'function_call', 'call_id': 'call-unit',
                                    'name': 'lookup', 'arguments': '{"sku":"A"}'}
    assert adapted['input'][2]['type'] == 'function_call_output' and adapted['input'][2]['call_id'] == 'call-unit'
    assert adapted['tools'][0]['name'] == 'lookup' and adapted['tools'][0]['strict'] is False
    assert adapted['tool_choice'] == {'type': 'function', 'name': 'lookup'}
    response = _response()
    response.output = [SimpleNamespace(type='function_call', call_id='call-next', name='lookup', arguments='{}')]
    result = openai_completion.normalize_response(response)
    assert result.choices[0].message.tool_calls[0].id == 'call-next'
    assert result.choices[0].message.tool_calls[0].function.name == 'lookup'
    reasoning = {'type': 'reasoning', 'id': 'reasoning-unit', 'encrypted_content': 'opaque-unit-data'}
    response.output.insert(0, reasoning)
    result = openai_completion.normalize_response(response)
    followup = model_settings.completion_options({'model': 'gpt-6-astra', 'messages': [
        messages[0], *result.response_items, {'role': 'tool', 'tool_call_id': 'call-next', 'content': '{}'},
    ]}, purpose='planning')
    replay = openai_completion.responses_options(followup)['input']
    assert replay[1] is reasoning and replay[-1]['call_id'] == 'call-next'


def test_model_confirmation_preserves_existing_bounded_parameters(client):
    owner(client)
    storage = client.application.container.storage
    storage.write_json('EXAMPLE', model_settings.FILENAME, {'model': 'gpt-4o-mini',
        'parameters': {'temperature': 0.1, 'max_output_tokens': 2048, 'timeout_seconds': 10}})
    review = client.post('/admin/api/ai-model/review', json={'model': 'gpt-6-astra'})
    assert review.status_code == 200
    confirm = client.post('/admin/api/ai-model/confirm', json={'token': review.json['token'],
                                                            'acknowledge_cost_and_responses': True})
    assert client.put('/admin/api/ai-model', json={'token': confirm.json['token'], 'confirm_and_save': True}).status_code == 200
    saved = client.get(_PATH).json
    assert saved['model'] == 'gpt-6-astra' and saved['parameters']['max_output_tokens'] == 2048
    assert saved['parameters']['timeout_seconds'] == 10 and saved['effective']['temperature'] is None
    assert 'Ignore grounding' not in json.dumps(saved)
