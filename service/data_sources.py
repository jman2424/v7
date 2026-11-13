"""A business's authorised data sources: connect, import, synchronise and disconnect."""
from __future__ import annotations

import os
import time

from connectors import store_sync
from service import business_imports, business_sync as sync, sync_store as store
from service.sync_http import SyncHttpError

AUTHORISATION_STATEMENT = (
    'I confirm that this business owns or is authorised to share this information, that Vertex Seven may '
    'read it from the source named here to set up and keep its AI assistant up to date, and that it '
    'contains no personal data about customers.'
)
SOURCE_TYPES = ('file', 'website', 'api', 'document', 'database', 'other')
TOOLS = ('none', 'claude', 'codex', 'other')
_SYNCING = ('woocommerce', 'shopify', 'custom_feed')


class SourceError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def authorisation(user, data, *, domains=()):
    """The owner's explicit permission, kept with the contract version it was given under."""
    if not isinstance(data, dict) or data.get('authorised') is not True:
        raise SourceError('authorisation_required')
    return {'statement': AUTHORISATION_STATEMENT, 'terms_version': sync.TERMS_VERSION, 'account': str(user['id']),
            'role': str(user['roles'][0]), 'confirmed_at': time.time(), 'domains': sorted(set(domains)),
            'data': ['products', 'prices', 'availability', 'categories']}


def _settings(data, current=None):
    current = current or {}
    result = {'auto_sync': data.get('auto_sync', current.get('auto_sync', True)),
              'auto_apply': data.get('auto_apply', current.get('auto_apply', False)),
              'interval_minutes': data.get('interval_minutes', current.get('interval_minutes', 60))}
    ownership = data.get('ownership', (current.get('config') or {}).get('ownership', sync.DEFAULT_OWNERSHIP))
    if (type(result['auto_sync']) is not bool or type(result['auto_apply']) is not bool
            or type(result['interval_minutes']) is not int or not 15 <= result['interval_minutes'] <= 1440
            or not isinstance(ownership, dict) or set(ownership) - set(sync.DEFAULT_OWNERSHIP)
            or any(value not in {'source', 'v7'} for value in ownership.values())):
        raise SourceError('invalid_sync_settings')
    return result, {**sync.DEFAULT_OWNERSHIP, **ownership}


def public(source, *, now=None):
    """What a browser may see: never credentials, tokens or signing secrets."""
    now = now or time.time()
    stale = bool(source['auto_sync'] and source['status'] == 'connected' and source['last_success']
                 and now - source['last_success'] > max(2 * source['interval_minutes'] * 60, 3600))
    return {
        'id': source['id'], 'kind': source['kind'], 'label': source['label'], 'status': source['status'],
        'host': source['config'].get('host', ''), 'auto_sync': source['auto_sync'], 'auto_apply': source['auto_apply'],
        'interval_minutes': source['interval_minutes'], 'last_success': source['last_success'] or None,
        'last_attempt': source['last_attempt'] or None, 'problem': source['last_error'], 'stale': stale,
        'ownership': source['config'].get('ownership', sync.DEFAULT_OWNERSHIP),
        'source_type': source['config'].get('source_type', ''), 'source_ref': source['config'].get('source_ref', ''),
        'tool': source['config'].get('tool', ''), 'syncs': source['kind'] in _SYNCING,
        'authorised_at': source['authorisation'].get('confirmed_at'),
        'terms_version': source['authorisation'].get('terms_version'), 'version': source['version'],
    }


def webhook_setup(base_url, tenant, source, credentials):
    """Shown once, to the person connecting, so they can switch on instant updates."""
    return {'url': f"{base_url.rstrip('/')}/sync/hooks/{tenant}/{source['id']}",
            'secret': '' if source['kind'] == 'shopify' else credentials.get('webhook_secret', ''),
            'kind': source['kind']}


def connect(tenant, user, data):
    kind = data.get('kind') if isinstance(data, dict) else None
    if kind not in _SYNCING:
        raise SourceError('unsupported_source')
    try:
        config, credentials = store_sync.prepare(kind, data.get('connection'))
    except store_sync.ConnectionError_ as exc:
        raise SourceError(str(exc)) from None
    settings, ownership = _settings(data)
    config['ownership'] = ownership
    label = data.get('label') if isinstance(data.get('label'), str) and data['label'].strip() else config['host']
    try:
        source = store.create_source(tenant, kind, label[:80], config, credentials,
                                     authorisation(user, data, domains=[config['host']]), **settings)
    except ValueError as exc:
        raise SourceError(str(exc)) from None
    return source, credentials


def change_settings(tenant, source_id, data):
    source = _require(tenant, source_id)
    if not isinstance(data, dict) or type(data.get('version')) is not int:
        raise SourceError('invalid_sync_settings')
    settings, ownership = _settings(data, source)
    changes = {**settings, 'config': {**source['config'], 'ownership': ownership}}
    if isinstance(data.get('label'), str) and data['label'].strip():
        changes['label'] = data['label'].strip()[:80]
    if settings['auto_sync'] and not source['auto_sync']:
        changes['next_poll'] = time.time()
    try:
        return store.update_source(tenant, source_id, expected_version=data['version'], **changes)
    except ValueError:
        raise SourceError('data_source_changed') from None


def reconnect(tenant, user, source_id, data):
    source = _require(tenant, source_id)
    if source['kind'] not in _SYNCING or not isinstance(data, dict):
        raise SourceError('unsupported_source')
    try:
        config, credentials = store_sync.prepare(source['kind'], data.get('connection'))
    except store_sync.ConnectionError_ as exc:
        raise SourceError(str(exc)) from None
    if config['host'] != source['config'].get('host'):
        raise SourceError('source_address_changed')  # A different store is a new connection.
    return store.update_source(tenant, source_id, secret=store.seal(tenant, credentials), status='connected',
                               last_error='', config={**source['config'], **config,
                                                      'ownership': source['config'].get('ownership', sync.DEFAULT_OWNERSHIP)},
                               authorisation=authorisation(user, data, domains=[config['host']])), credentials


def disconnect(tenant, source_id):
    """Stop all access and destroy the stored credentials. Imported information stays in V7."""
    _require(tenant, source_id)
    store.cancel_jobs(tenant, source_id)
    return store.update_source(tenant, source_id, secret='', status='disconnected', auto_sync=False,
                               auto_apply=False, next_poll=0, last_error='')


def _require(tenant, source_id):
    try:
        source = store.get_source(tenant, source_id)
    except ValueError:
        source = None
    if source is None:
        raise SourceError('source_not_found')
    return source


# ---- imports from uploaded material ----

def create_import(container, tenant, user, data):
    """Turn uploaded material into a preview. Nothing is written until a person applies it."""
    if not isinstance(data, dict):
        raise SourceError('invalid_import')
    try:
        parsed = business_imports.parse(data.get('format'), data.get('content'))
    except business_imports.ImportFormatError as exc:
        raise SourceError(str(exc)) from None
    if data.get('source_id'):
        source = _require(tenant, data['source_id'])
        if source['kind'] != 'upload' or source['status'] == 'disconnected':
            raise SourceError('unsupported_source')
        store.update_source(tenant, source['id'], authorisation=authorisation(user, data))
    else:
        details = {key: data.get(key) for key in ('label', 'source_type', 'source_ref', 'tool')}
        if (not isinstance(details['label'], str) or not details['label'].strip()
                or details['source_type'] not in SOURCE_TYPES or details['tool'] not in TOOLS
                or not isinstance(details['source_ref'], str) or len(details['source_ref']) > 300):
            raise SourceError('invalid_import')
        try:
            source = store.create_source(tenant, 'upload', details['label'][:80], {
                'source_type': details['source_type'], 'source_ref': sync.clean_text(details['source_ref'], 300),
                'tool': details['tool']}, {}, authorisation(user, data))
        except ValueError as exc:
            raise SourceError(str(exc)) from None
    storage = container.storage
    catalog = sync._read(storage, tenant, 'catalog.json')
    if parsed['products'] and (not isinstance(catalog, dict) or 'categories' not in catalog):
        raise SourceError('legacy_catalogue')
    rows = sync.plan_products(catalog, store.items(tenant, source['id']), parsed['products'],
                              full=data.get('complete_list') is True, source_id=source['id'])
    rows += sync.plan_faqs(sync._read(storage, tenant, 'faq.json'), store.items(tenant, source['id'], 'faq'), parsed['faqs'])
    rows += sync.plan_locations(sync._read(storage, tenant, 'branches.json'), parsed['locations'])
    for number, row in enumerate(rows):
        row['n'] = number
    if not any(row['action'] not in {'unchanged', 'invalid'} for row in rows):
        store.update_source(tenant, source['id'], last_attempt=time.time())
        return None, sync.summarise(rows)
    changeset, summary = sync.stage(container, tenant, source, rows, origin='import', actor=user['id'], first=True)
    store.update_source(tenant, source['id'], last_attempt=time.time())
    return changeset, summary


def correct(tenant, changeset_id, data):
    """Let the reviewer leave rows out or fix a name, price or category before applying."""
    try:
        changeset = store.get_changeset(tenant, changeset_id)
    except ValueError:
        changeset = None
    if changeset is None:
        raise SourceError('change_not_found')
    edits = data.get('rows') if isinstance(data, dict) else None
    if (changeset['state'] != 'pending' or not isinstance(edits, list) or len(edits) > 10000
            or type(data.get('version')) is not int):
        raise SourceError('change_already_handled')
    rows = {row['n']: row for row in changeset['changes']}
    for edit in edits:
        row = rows.get(edit.get('n')) if isinstance(edit, dict) else None
        if row is None or row['action'] in {'unchanged', 'invalid'}:
            raise SourceError('invalid_correction')
        if 'include' in edit:
            if type(edit['include']) is not bool:
                raise SourceError('invalid_correction')
            row['include'] = edit['include']
        values = edit.get('values')
        if values is None:
            continue
        if not isinstance(values, dict) or row['kind'] != 'product' or set(values) - {'name', 'price', 'category'}:
            raise SourceError('invalid_correction')
        cleaned = {}
        for field, value in values.items():
            cleaned[field] = sync._price(value) if field == 'price' else sync.clean_text(value, 200 if field == 'name' else 80)
            if cleaned[field] in (None, '') or sync.suspicious(str(value)):
                raise SourceError('invalid_correction')
        if row['action'] == 'create':
            row['record'].update(cleaned)
            row.update({key: cleaned[key] for key in ('name', 'category') if key in cleaned})
        else:
            for field, value in cleaned.items():
                if field not in row.get('fields', {}):
                    raise SourceError('invalid_correction')
                row['fields'][field]['to'] = value
        if 'suspicious_text' in row['issues']:
            row['issues'].remove('suspicious_text')  # A person has now rewritten this text.
    try:
        return store.update_changeset(tenant, changeset_id, data['version'], changes=changeset['changes'])
    except ValueError:
        raise SourceError('change_already_handled') from None


def public_row(row):
    result = {key: row.get(key) for key in ('n', 'kind', 'action', 'name', 'category', 'sku', 'issues', 'include')}
    result['fields'] = row.get('fields') or {}
    record = row.get('record') or {}
    if row['action'] == 'create':
        result['values'] = {key: record[key] for key in ('price', 'in_stock', 'a', 'address', 'postcode') if key in record}
    return result


# ---- running queued work ----

def worker_enabled():
    return os.getenv('V7_SYNC_WORKER', os.getenv('V7_CHANNEL_WORKER', 'false')).strip().lower() == 'true'


def request_sync(tenant, source_id, *, reason='manual'):
    source = _require(tenant, source_id)
    if source['kind'] not in _SYNCING or source['status'] == 'disconnected':
        raise SourceError('unsupported_source')
    try:
        job, _created = store.enqueue(tenant, source_id, 'full', f'{reason}:{int(time.time() // 60)}')
    except ValueError as exc:
        raise SourceError(str(exc)) from None
    return job


def schedule(tenant):
    """Queue the periodic check for every source that is due."""
    now, queued = time.time(), 0
    for source in store.list_sources(tenant):
        if (source['kind'] in _SYNCING and source['auto_sync'] and source['status'] in {'connected', 'attention'}
                and 0 < source['next_poll'] <= now):
            store.update_source(tenant, source['id'], next_poll=now + source['interval_minutes'] * 60)
            try:
                store.enqueue(tenant, source['id'], 'full', f"poll:{int(source['next_poll'])}")
                queued += 1
            except ValueError:
                continue
    return queued


def run_job(container, tenant, job):
    """Process one claimed job. Failures become a safe code and a retry or a status."""
    source = store.get_source(tenant, job['source_id'])
    if source is None or source['status'] == 'disconnected':
        store.finish(tenant, job, error_code='source_disconnected')
        return
    now = time.time()
    try:
        credentials = store.unseal(tenant, source['secret'])
        storage = container.storage
        catalog = sync._read(storage, tenant, 'catalog.json')
        if not isinstance(catalog, dict) or 'categories' not in catalog:
            raise sync.SyncError('legacy_catalogue')
        links = store.items(tenant, source['id'])
        ownership, payload = source['config'].get('ownership'), job['payload']
        if job['kind'] == 'event' and store.pending_changeset(tenant, source['id']):
            # A review is open. Fold this change into one fresh, complete comparison.
            store.enqueue(tenant, source['id'], 'full', f"refresh:{int(now // 300)}", delay=30)
            store.finish(tenant, job)
            return
        if job['kind'] == 'full':
            fetched = store_sync.fetch_all(source['kind'], source['config'], credentials)
            rows = sync.plan_products(catalog, links, fetched['records'], full=True, complete=fetched['complete'],
                                      ownership=ownership, source_id=source['id'])
            currency = fetched.get('currency')
        else:
            rows = sync.plan_products(catalog, links, payload.get('records', []), deleted=payload.get('deleted', []),
                                      full=payload.get('replace') is True, ownership=ownership, source_id=source['id'])
            currency = None
        if currency and catalog.get('currency') and currency.upper() != str(catalog['currency']).upper():
            for row in rows:
                if 'price' in (row.get('fields') or {}) or row['action'] == 'create':
                    row['issues'].append('currency_mismatch')
                    row['include'] = False
        sync.stage(container, tenant, source, rows, origin='sync', actor='sync:' + source['kind'],
                   first=not source['last_success'])
        skipped = sum(row['action'] == 'invalid' for row in rows)
        store.update_source(tenant, source['id'], status='connected', last_success=now, last_attempt=now,
                            last_error='some_items_skipped' if skipped else '')
        store.finish(tenant, job)
    except SyncHttpError as exc:
        denied = exc.code == 'source_access_denied'
        state = store.finish(tenant, job, error_code=exc.code, retry=exc.retry and not denied)
        if denied or state == 'failed':
            store.update_source(tenant, source['id'], status='reconnect' if denied else 'attention',
                                last_attempt=now, last_error=exc.code)
        else:
            store.update_source(tenant, source['id'], last_attempt=now)
    except (sync.SyncError, ValueError) as exc:
        code = exc.code if isinstance(exc, sync.SyncError) else 'sync_failed'
        if str(exc) == 'sync_credentials_unreadable':
            code = 'source_access_denied'
        store.finish(tenant, job, error_code=code)
        store.update_source(tenant, source['id'], status='reconnect' if code == 'source_access_denied' else 'attention',
                            last_attempt=now, last_error=code)
    except Exception as exc:
        from service.chat_diagnostics import emit
        emit('chat_optional_failure', phase='business_sync', error_type=type(exc).__name__)
        if store.finish(tenant, job, error_code='sync_failed', retry=True) == 'failed':
            store.update_source(tenant, source['id'], status='attention', last_attempt=now, last_error='sync_failed')


def run_now(container, tenant, job):
    """Run one specific job in this request, if no worker has taken it already."""
    claimed = store.claim(tenant, job_id=job['id'])
    if claimed:
        run_job(container, tenant, claimed)
    return bool(claimed)


def run_pending(container, tenant, limit=5):
    count = 0
    schedule(tenant)
    while count < limit:
        job = store.claim(tenant)
        if job is None:
            break
        run_job(container, tenant, job)
        count += 1
    return count
