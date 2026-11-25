"""Platform-assigned phone numbers, email addresses and WhatsApp senders per business.

Each business keeps its assignments in its own ``channel_routes.json`` document,
written only by a platform administrator through the admin API. Inbound lookups
merge these with the operator's server settings. A recipient claimed by more than
one business routes to none of them, so a mistake can stop routing but can never
send one business's customers to another.
"""
from __future__ import annotations

import copy
import re
import threading
import time
from typing import Any

FILENAME = 'channel_routes.json'
KINDS = ('phone', 'email', 'whatsapp_twilio', 'whatsapp_meta')
DEFAULTS: dict[str, Any] = {'version': 1, 'phone': [], 'email': [], 'whatsapp_twilio': [], 'whatsapp_meta': []}
MAX_PER_KIND = 10
_E164 = re.compile(r'\+[1-9][0-9]{7,14}\Z')
_META_ID = re.compile(r'[0-9]{5,30}\Z')
_CACHE_SECONDS = 10.0
_lock = threading.Lock()
_cache: dict[str, Any] = {'at': 0.0, 'value': None}


def _email_row(row: Any) -> dict[str, str]:
    from service.business_channels import UUID, address
    if not isinstance(row, dict) or set(row) - {'address', 'sender', 'inbox_id'} or 'address' not in row:
        raise ValueError('invalid_channel_routes')
    inbound = address(row['address'])
    sender = address(row.get('sender') or inbound)
    result = {'address': inbound, 'sender': sender}
    if 'inbox_id' in row:
        identifier = row['inbox_id']
        if not isinstance(identifier, str) or not UUID.fullmatch(identifier):
            raise ValueError('invalid_channel_routes')
        result['inbox_id'] = identifier
    return result


def validate(value: Any) -> dict[str, Any]:
    """Return a normalised document or raise ``invalid_channel_routes``."""
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError('invalid_channel_routes')
    result = copy.deepcopy(DEFAULTS)
    for kind in KINDS:
        rows = value.get(kind, [])
        if not isinstance(rows, list) or len(rows) > MAX_PER_KIND:
            raise ValueError('invalid_channel_routes')
        clean: list[Any] = []
        for row in rows:
            if kind == 'email':
                item: Any = _email_row(row)
                key = item['address']
            else:
                if not isinstance(row, str):
                    raise ValueError('invalid_channel_routes')
                item = row.strip()
                if kind in ('phone', 'whatsapp_twilio') and not _E164.fullmatch(item):
                    raise ValueError('invalid_channel_routes')
                if kind == 'whatsapp_meta' and not _META_ID.fullmatch(item):
                    raise ValueError('invalid_channel_routes')
                key = item
            if key in [r['address'] if kind == 'email' else r for r in clean]:
                raise ValueError('invalid_channel_routes')
            clean.append(item)
        result[kind] = clean
    return result


def document(storage: Any, tenant: str) -> dict[str, Any]:
    try:
        return validate(storage.read_json(tenant, FILENAME))
    except FileNotFoundError:
        return copy.deepcopy(DEFAULTS)


def _all_documents() -> list[tuple[str, dict[str, Any]]]:
    """Every business's assignments. No other business data is read."""
    from service import session_store
    rows: list[tuple[str, Any]] = []
    if session_store._using_postgres():
        with session_store.postgres_connection() as db:
            rows = [(row[0], row[1]) for row in db.execute(
                'SELECT tenant, payload FROM v7_private.channel_route_documents()').fetchall()]
    else:
        from flask import current_app, has_app_context
        container = getattr(current_app, 'container', None) if has_app_context() else None
        if container is not None:
            storage = container.storage
        else:
            from retrieval.storage import Storage
            storage = Storage()
        for tenant in storage.tenant_keys():
            try:
                rows.append((tenant, storage.read_json(tenant, FILENAME)))
            except FileNotFoundError:
                continue
    result = []
    for tenant, payload in rows:
        try:
            result.append((tenant, validate(payload)))
        except ValueError:
            continue  # A damaged document routes nothing rather than guessing.
    return result


def _stored() -> list[tuple[str, dict[str, Any]]]:
    now = time.monotonic()
    with _lock:
        if _cache['value'] is not None and now - _cache['at'] < _CACHE_SECONDS:
            return _cache['value']
    try:
        value = _all_documents()
    except Exception as exc:  # Storage outage: keep operator routes working.
        from service.chat_diagnostics import emit
        emit('chat_optional_failure', phase='channel_routes', error_type=type(exc).__name__)
        value = []
    with _lock:
        _cache.update(at=now, value=value)
    return value


def invalidate() -> None:
    with _lock:
        _cache.update(at=0.0, value=None)


def merge(base: dict[str, str], kind: str) -> dict[str, str]:
    """Add stored assignments to an operator map; any double claim is dropped."""
    claims: dict[str, set[str]] = {key: {tenant} for key, tenant in base.items()}
    for tenant, doc in _stored():
        for row in doc[kind]:
            key = row['address'] if kind == 'email' else row
            if kind == 'whatsapp_twilio':
                key = key.lstrip('+')
            claims.setdefault(key, set()).add(tenant)
    return {key: next(iter(owners)) for key, owners in claims.items() if len(owners) == 1}


def stored_inboxes():
    return [(row['inbox_id'], tenant, row['address'], row['sender'])
            for tenant, doc in _stored() for row in doc['email'] if 'inbox_id' in row]


def stored_senders() -> dict[str, tuple[str, str]]:
    """Inbound address -> (tenant, verified sending address) from stored assignments."""
    return {row['address']: (tenant, row['sender']) for tenant, doc in _stored() for row in doc['email']}


def conflicts(tenant: str, value: dict[str, Any]) -> list[str]:
    """Recipients in ``value`` already assigned to another business."""
    from service import business_channels as channels
    from service.whatsapp_configuration import operator_routes
    taken: dict[str, dict[str, str]] = {
        'phone': channels.operator_bindings('phone'), 'email': channels.operator_bindings('email'),
        'whatsapp_twilio': operator_routes('twilio'), 'whatsapp_meta': operator_routes('meta')}
    invalidate()
    for other, doc in _all_documents():
        if other == tenant:
            continue
        for kind in KINDS:
            for row in doc[kind]:
                key = row['address'] if kind == 'email' else row
                taken[kind][key.lstrip('+') if kind == 'whatsapp_twilio' else key] = other
    found = []
    for kind in KINDS:
        for row in value[kind]:
            key = row['address'] if kind == 'email' else row
            key = key.lstrip('+') if kind == 'whatsapp_twilio' else key
            if taken[kind].get(key, tenant) != tenant:
                found.append(row['address'] if kind == 'email' else row)
    return found
