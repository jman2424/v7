"""Content-free chat timing and one shared provider budget per customer turn."""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import logging
import re
import time

logger = logging.getLogger('Chat.Diagnostics')
_turn = ContextVar('chat_diagnostics', default=None)


def emit(event, **fields):
    from flask import g, has_request_context
    current = _turn.get() or {}
    safe = {'event': event, 'request_id': current.get('request_id') or (g.get('request_id', '-') if has_request_context() else '-'),
            'session_hash': current.get('session_hash', '-')}
    for key in ('phase', 'outcome', 'route', 'error_type', 'purpose', 'model', 'provider_calls',
                'history_messages', 'elapsed_ms', 'timeout_seconds', 'status_code',
                'input_tokens', 'output_tokens', 'cached_tokens', 'knowledge_count'):
        value = fields.get(key)
        if type(value) in (int, float, bool) or (isinstance(value, str)
                and re.fullmatch(r'[A-Za-z0-9_.:-]{1,80}', value)
                and not value.startswith(('sk-', 'sk_', 'whsec_', 'Bearer'))):
            safe[key] = value
    logger.info('%s', json.dumps(safe, separators=(',', ':')))


@contextmanager
def turn_scope(channel, request_id, session_id):
    started = time.monotonic()
    current = {'request_id': request_id if isinstance(request_id, str) and re.fullmatch(r'[a-f0-9]{24}', request_id) else '-',
               'session_hash': hashlib.sha256(str(session_id).encode()).hexdigest()[:16],
               'deadline': started + 30 if channel in {'web', 'test'} else None, 'provider_calls': 0}
    token = _turn.set(current)
    try:
        yield
    except Exception as exc:
        emit('chat_failed', error_type=type(exc).__name__)
        raise
    finally:
        emit('chat_finished', elapsed_ms=round((time.monotonic()-started)*1000, 2),
             provider_calls=current['provider_calls'])
        _turn.reset(token)


@contextmanager
def phase(name):
    started = time.monotonic()
    try:
        yield
    except Exception as exc:
        emit('chat_phase', phase=name, outcome='failed', error_type=type(exc).__name__,
             elapsed_ms=round((time.monotonic()-started)*1000, 2))
        raise
    else:
        emit('chat_phase', phase=name, outcome='completed', elapsed_ms=round((time.monotonic()-started)*1000, 2))


def provider_timeout(configured):
    current = _turn.get()
    if not current or current['deadline'] is None:
        return configured
    remaining = current['deadline'] - time.monotonic()
    if remaining < 1:
        from service.plan_usage import AllowancePaused
        emit('provider_skipped', outcome='turn_budget_exhausted')
        raise AllowancePaused('turn_budget_exhausted')
    return min(float(configured), remaining, 20)


def provider_started():
    if _turn.get() is not None:
        _turn.get()['provider_calls'] += 1
