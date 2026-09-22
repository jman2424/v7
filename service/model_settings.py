"""Tenant-specific model selection, separate from ordinary editable overrides."""
from retrieval.storage import Storage
from service.business_management import revision

MODELS = ('gpt-4o-mini','gpt-4o')
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
    from service.api_usage import RATES
    return [{'id':model,'input_usd_per_million':RATES[model][0]/1000,
             'cached_usd_per_million':RATES[model][1]/1000,
             'output_usd_per_million':RATES[model][2]/1000} for model in MODELS]
