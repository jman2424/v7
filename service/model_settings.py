"""Tenant-specific model selection, separate from ordinary editable overrides."""
from retrieval.storage import Storage
from service.business_management import revision

MODELS = (
    'gpt-4o-mini', 'gpt-4o', 'gpt-4.1-mini', 'gpt-4.1',
    'gpt-5.6-luna', 'gpt-5.6-terra', 'gpt-5.6-sol',
    'gpt-6-luna', 'gpt-6-sol', 'gpt-6-astra',
)
FILENAME = 'ai_model.json'


def document(storage, tenant):
    try:
        value = storage.read_json(tenant,FILENAME)
    except FileNotFoundError:
        return {}
    if not isinstance(value,dict) or value.get('model') not in MODELS:
        raise ValueError('invalid_model_configuration')
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
    """Remove sampling options unsupported by reasoning models at default effort."""
    options = dict(kwargs)
    model = str(options.get('model') or '')
    if not model.startswith(('gpt-4o', 'gpt-4.1')):
        options.pop('temperature', None)
    return options
