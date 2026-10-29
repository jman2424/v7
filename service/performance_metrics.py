"""Bounded per-worker timing aggregates, with no messages or identities."""
from collections import OrderedDict, deque
import math
import re
from threading import RLock

_values = OrderedDict()
_lock = RLock()
_TENANT = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z')
_NAME = re.compile(r'[A-Za-z0-9_.:-]{1,100}\Z')


def record(tenant, metric, value):
    if (not isinstance(tenant, str) or not _TENANT.fullmatch(tenant)
            or not isinstance(metric, str) or not _NAME.fullmatch(metric)
            or type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100_000_000):
        return
    with _lock:
        key = (tenant, metric)
        _values.setdefault(key, deque(maxlen=256)).append(float(value))
        _values.move_to_end(key)
        while len(_values) > 128:
            _values.popitem(last=False)


def observe(tenant, event, fields):
    if event == 'provider_connection' and fields.get('outcome') in {'opened', 'reused'}:
        record(tenant, 'provider_new_connections', int(fields['outcome'] == 'opened'))
    names = {'chat_http_finished': 'http_total_ms', 'provider_finished': 'model_ms',
             'stream_first_visible': 'server_first_visible_ms', 'prompt_built': 'prompt_build_ms',
             'validation_finished': 'validation_ms', 'db_connection': 'db_acquire_ms'}
    metric = names.get(event)
    if event == 'chat_phase' and _NAME.fullmatch(str(fields.get('phase', ''))):
        metric = 'phase.' + fields['phase'] + '_ms'
    if metric and 'elapsed_ms' in fields:
        record(tenant, metric, fields['elapsed_ms'])
    for name in ('input_tokens', 'output_tokens', 'cached_tokens', 'cache_hits', 'cache_misses', 'request_cache_hits', 'prompt_bytes'):
        if name in fields:
            record(tenant, name, fields[name])


def snapshot(tenant):
    result = {}
    with _lock:
        for (owner, metric), samples in _values.items():
            if owner != tenant or not samples:
                continue
            rows = sorted(samples)
            size = len(rows)
            result[metric] = {'count': size, 'p50': rows[(size - 1) // 2],
                              'p95': rows[math.ceil(size * .95) - 1], 'sum': sum(rows)}
    return {'scope': 'current_worker_bounded_window', 'maximum_samples_per_metric': 256, 'metrics': result}
