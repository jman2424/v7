"""Version-checked public business snapshots, never authentication/billing state.

The process cache is only an optimization: every new request checks database row
versions (or filesystem identities). A request keeps one consistent copy of each
document. No TTL permits serving prices after an observed change.
"""
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
import copy
import hashlib
import json
import os
from threading import RLock

PUBLIC_DOCUMENTS = ('catalog.json', 'faq.json', 'delivery.json', 'branches.json',
                    'offers.json', 'business_core.json', 'store_info.json',
                    'website_knowledge.json', 'website_destinations.json')
_active = ContextVar('v7_business_read_snapshot', default=None)
_cache = OrderedDict()
_lock = RLock()
_MAX_BYTES = 4 * 1024 * 1024
_MAX_ENTRIES = 128
_MISSING = object()
_UNLOADED = object()


def namespace(storage, tenant):
    backend = 'postgres' if storage._using_postgres() else 'sqlite'
    location = os.getenv('V7_POSTGRES_DSN', '') if backend == 'postgres' else str(storage.business_root.resolve())
    return backend, hashlib.sha256(location.encode()).hexdigest(), storage.canonical_tenant_key(tenant)


def cached(key):
    with _lock:
        row = _cache.get(key)
        if row is not None:
            _cache.move_to_end(key)
            return copy.deepcopy(row[:2])
    return None


def remember(key, version, payload):
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
    if len(encoded) > _MAX_BYTES // 2:
        return
    with _lock:
        _cache[key] = (version, copy.deepcopy(payload), len(encoded))
        _cache.move_to_end(key)
        while len(_cache) > _MAX_ENTRIES or sum(row[2] for row in _cache.values()) > _MAX_BYTES:
            _cache.popitem(last=False)


def invalidate(storage, tenant, filename=None):
    scope = namespace(storage, tenant)
    with _lock:
        for key in list(_cache):
            if key[:3] == scope and (filename is None or key[-1] == filename):
                del _cache[key]
    active = _active.get()
    if active and active['namespace'] == scope:
        for name in list(active['documents']):
            if filename is None or filename == name:
                active['documents'][name] = _UNLOADED


def request_value(storage, tenant, filename):
    active = _active.get()
    if not active or filename not in PUBLIC_DOCUMENTS:
        return False, None
    # The immutable Storage instance and exact tenant were already validated
    # when opening this turn. Avoid repeating filesystem alias enumeration for
    # every helper read. Different instances/aliases still resolve normally.
    same_binding = active['storage'] is storage and tenant in (active['tenant'], active['namespace'][2])
    if not same_binding and active['namespace'] != namespace(storage, tenant):
        return False, None
    row = active['documents'].get(filename, _MISSING)
    if row is _UNLOADED:
        return False, None
    if row is _MISSING:
        raise FileNotFoundError(filename)
    if isinstance(row, Exception):
        raise row
    active['hits'] += 1
    return True, copy.deepcopy(row)


@contextmanager
def snapshot(storage, tenant):
    """One checked batch per turn; ContextVar isolation also covers threads."""
    scope = namespace(storage, tenant)
    existing = _active.get()
    if existing and existing['namespace'] == scope:
        yield
        return
    from service.chat_diagnostics import emit, phase
    documents, hits = {}, 0
    with phase('business_snapshot'):
        if storage._using_postgres():
            repository = storage._postgres_repository(tenant)
            entries = {name: cached((*scope, name)) for name in PUBLIC_DOCUMENTS}
            versions = {name: row[0] for name, row in entries.items() if row is not None}
            for name, version, unchanged, payload in repository.read_versioned_documents(PUBLIC_DOCUMENTS, versions):
                if unchanged:
                    if entries[name] is None or entries[name][0] != version:
                        raise RuntimeError('Business cache version mismatch')
                    documents[name] = entries[name][1]
                    hits += 1
                else:
                    documents[name] = payload
                    remember((*scope, name), version, payload)
        else:
            from retrieval.storage import _read_json
            for name in PUBLIC_DOCUMENTS:
                try:
                    path = storage.file_path(tenant, name)
                    stat = path.stat()
                    version = (stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
                    entry = cached((*scope, name))
                    if entry is not None and entry[0] == version:
                        documents[name] = entry[1]
                        hits += 1
                    else:
                        payload = _read_json(path)
                        # Never assign an old identity to bytes replaced while
                        # they were being read. The next request checks again.
                        after = path.stat()
                        current = (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_ctime_ns, after.st_size)
                        documents[name] = payload
                        if current == version:
                            remember((*scope, name), version, payload)
                except FileNotFoundError:
                    continue
                except (OSError, ValueError) as exc:
                    # A malformed optional FAQ cannot break an independent
                    # valid catalogue; preserve each reader's error semantics.
                    documents[name] = exc
        emit('business_cache', outcome='version_checked', cache_hits=hits,
             cache_misses=len(documents) - hits)
    state = {'namespace': scope, 'storage': storage, 'tenant': tenant, 'documents': documents, 'hits': 0}
    token = _active.set(state)
    try:
        yield
    finally:
        emit('business_cache', outcome='request_reuse', request_cache_hits=state['hits'])
        _active.reset(token)
