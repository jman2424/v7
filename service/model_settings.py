"""Tenant-specific model selection, separate from ordinary editable overrides."""
import math
import os

from retrieval.storage import Storage
from service.business_management import revision

MODELS = (
    'gpt-4o-mini', 'gpt-4o', 'gpt-4.1-mini', 'gpt-4.1',
    'gpt-5.6-luna', 'gpt-5.6-terra', 'gpt-5.6-sol',
    'gpt-6-luna', 'gpt-6-sol', 'gpt-6-astra',
)
FILENAME = 'ai_model.json'
_EFFORTS = ('none', 'low', 'medium', 'high', 'xhigh', 'max')
PARAMETER_DEFAULTS = {'temperature': 0.3, 'max_output_tokens': 1024, 'timeout_seconds': 30}


def validated_parameters(value):
    if not isinstance(value, dict) or set(value) - {*PARAMETER_DEFAULTS, 'reasoning_effort'}:
        raise ValueError('invalid_ai_parameters')
    result = dict(value)
    for key, low, high in [('temperature', 0, 1), ('max_output_tokens', 256, 4096), ('timeout_seconds', 5, 60)]:
        if key not in result:
            continue
        number = result[key]
        if (isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number)
                or not low <= number <= high or (key == 'max_output_tokens' and type(number) is not int)):
            raise ValueError('invalid_' + key)
    if 'reasoning_effort' in result:
        if result['reasoning_effort'] is None:
            result.pop('reasoning_effort')
        elif not isinstance(result['reasoning_effort'], str) or result['reasoning_effort'] not in _EFFORTS:
            raise ValueError('invalid_reasoning_effort')
    return result


def capabilities(model, effort=None):
    reasoning = model.startswith(('gpt-5.6', 'gpt-6-'))
    efforts = list(_EFFORTS[1:] if model == 'gpt-6-astra' else _EFFORTS) if reasoning else []
    default = 'low' if model.startswith('gpt-6-') else 'medium' if reasoning else None
    effort = effort if effort in efforts else default
    return {'temperature': model.startswith(('gpt-4o', 'gpt-4.1')) or (reasoning and effort == 'none'),
            'reasoning_efforts': efforts, 'default_reasoning_effort': default,
            'max_output_tokens': {'min': 256, 'max': 4096}, 'timeout_seconds': {'min': 5, 'max': 60}}


def uses_responses(model):
    # These models keep reasoning/tool calls on the supported Responses path.
    return model.startswith(('gpt-5.6', 'gpt-6-'))


def document(storage, tenant):
    try:
        value = storage.read_json(tenant,FILENAME)
    except FileNotFoundError:
        return {}
    if (not isinstance(value,dict) or ('model' in value and value['model'] not in MODELS)
            or ('model' not in value and 'parameters' not in value)):
        raise ValueError('invalid_model_configuration')
    validated_parameters(value.get('parameters', {}))
    return value


def selected(tenant, storage=None):
    return document(storage or Storage(tenant),tenant).get('model')


def options():
    from service.api_usage import RATES, _CACHE_WRITE_RATES
    return [{'id': model,
             'input_usd_per_million': RATES[model][0] / 1000 if model in RATES else None,
             'cached_usd_per_million': RATES[model][1] / 1000 if model in RATES else None,
             'cache_write_usd_per_million': _CACHE_WRITE_RATES[model] / 1000 if model in _CACHE_WRITE_RATES else None,
             'output_usd_per_million': RATES[model][2] / 1000 if model in RATES else None}
            for model in MODELS]


def compatible_completion_kwargs(kwargs):
    """Keep the requested model and remove only unsupported sampling parameters."""
    options = dict(kwargs)
    model = str(options.get('model') or '')
    supported = capabilities(model, options.get('reasoning_effort'))
    if not supported['temperature']:
        for key in ('temperature', 'top_p', 'top_logprobs', 'logprobs'):
            options.pop(key, None)
    if not supported['reasoning_efforts']:
        options.pop('reasoning_effort', None)
    return options


def parameter_status(storage, tenant, value=None):
    value = document(storage, tenant) if value is None else value
    model = value.get('model') or os.getenv('OPENAI_MODEL') or 'gpt-4o-mini'
    saved = validated_parameters(value.get('parameters', {}))
    support = capabilities(model, saved.get('reasoning_effort'))
    parameters = {**PARAMETER_DEFAULTS, 'reasoning_effort': support['default_reasoning_effort'], **saved}
    effort = parameters['reasoning_effort']
    if effort not in support['reasoning_efforts']:
        effort = support['default_reasoning_effort']
    effective = {**parameters, 'reasoning_effort': effort,
                 'temperature': parameters['temperature'] if support['temperature'] else None,
                 'api': 'responses' if uses_responses(model) else 'chat'}
    return {'tenant': tenant, 'model': model, 'revision': revision(value), 'parameters': parameters,
            'effective': effective, 'capabilities': support, 'guardrails': [
                'Only this company’s approved information is available to the agent.',
                'Grounding, tenant permissions and confirmed sales actions remain mandatory.',
                'Website answers stay extractive; planning temperature is capped at 0.5 and rewriting at 0.3.',
                'Output tokens include reasoning; the maximum is 4096 per request.',
                'Provider response storage is disabled; cost records contain usage metadata only.',
            ]}


def completion_options(kwargs, *, purpose, configuration=None):
    options = dict(kwargs)
    configuration = configuration or {}
    saved = validated_parameters(configuration.get('parameters', {}))
    model = configuration.get('model') or options['model']
    options['model'] = model
    support = capabilities(model, saved.get('reasoning_effort') or options.get('reasoning_effort'))
    if support['reasoning_efforts']:
        effort = saved.get('reasoning_effort') or options.get('reasoning_effort') or support['default_reasoning_effort']
        options['reasoning_effort'] = effort if effort in support['reasoning_efforts'] else support['default_reasoning_effort']
    output_limit = saved.get('max_output_tokens', PARAMETER_DEFAULTS['max_output_tokens'])
    for key in ('max_tokens', 'max_completion_tokens', 'max_output_tokens'):
        old = options.pop(key, None)
        if type(old) is int and old > 0:
            output_limit = min(old, output_limit)
    options['max_tokens'] = output_limit
    timeout = saved.get('timeout_seconds', options.get('timeout', PARAMETER_DEFAULTS['timeout_seconds']))
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout):
        timeout = PARAMETER_DEFAULTS['timeout_seconds']
    options['timeout'] = min(60, max(5, timeout))
    temperature = saved.get('temperature', options.get('temperature', PARAMETER_DEFAULTS['temperature']))
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not math.isfinite(temperature):
        temperature = PARAMETER_DEFAULTS['temperature']
    cap = {'planning': 0.5, 'rewriting': 0.3, 'website_answer': 0}.get(purpose, 1)
    options['temperature'] = min(cap, max(0, temperature))
    return compatible_completion_kwargs(options)
