"""Plan, review, apply and undo business-information changes from imports and connected sources.

One rule decides every product field: a source value is applied only when the
source changed it and nobody edited the V7 value since the last sync. A manual
V7 edit is never overwritten silently; it becomes a conflict for a person.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import html
import math
import re

from service import sync_store as store
from service.business_management import revision

TERMS_VERSION = 'data-import-sync-terms-2026-11-draft-1'
PRODUCT_FIELDS = ('name', 'price', 'category', 'in_stock', 'stock_quantity')
OWNERSHIP_GROUP = {'name': 'names', 'price': 'prices', 'category': 'categories',
                   'in_stock': 'availability', 'stock_quantity': 'availability'}
DEFAULT_OWNERSHIP = {'names': 'source', 'prices': 'source', 'categories': 'source', 'availability': 'source'}
DAYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
SCHEMAS = {'catalog.json': 'catalog.schema.json', 'faq.json': 'faq.schema.json', 'branches.json': 'branches.schema.json'}
_MISSING = object()
_TAG = re.compile(r'<[^>]{0,2000}>')
_CONTROL = re.compile(r'[\x00-\x1f\x7f​-‏‪-‮⁠-⁤﻿]')
# Imported text is data for customers, never instructions for the assistant.
_INSTRUCTION = re.compile(
    r'ignore (?:all |any |the )?(?:previous|prior|above|earlier)|disregard (?:all|any|the|your|previous)|'
    r'system prompt|new instructions|you are now|you must now|as an ai\b|act as (?:a|an|the)\b|'
    r'\b(?:assistant|system|developer)\s*:|reveal (?:your|the) (?:prompt|instructions)|'
    r'<\s*/?\s*(?:system|instructions?|script)\b', re.I)


class SyncError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


# ---- cleaning and validating incoming records ----

def clean_text(value, limit):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ''
    text = html.unescape(_TAG.sub(' ', str(value)))
    return ' '.join(_CONTROL.sub(' ', text).split())[:limit].strip()


def suspicious(*values):
    return any(isinstance(value, str) and _INSTRUCTION.search(value) for value in values)


def _key(text):
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', str(text).casefold()).split())


def _slug(text, fallback='item'):
    return re.sub(r'[^a-z0-9]+', '_', str(text).casefold()).strip('_')[:60] or fallback


def _price(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        match = re.fullmatch(r'\s*[£$€]?\s*(\d{1,9}(?:,\d{3})*(?:\.\d{1,4})?|\d{1,9},\d{2})\s*(?:GBP|USD|EUR)?\s*', value, re.I)
        if not match:
            return None
        text = match.group(1)
        value = text.replace(',', '.') if re.fullmatch(r'\d+,\d{2}', text) else text.replace(',', '')
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 2) if math.isfinite(number) and 0 <= number <= 1_000_000_000 else None


def _flag(value, default=True):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, str):
        text = _key(value)
        if text in {'yes', 'true', '1', 'in stock', 'instock', 'available', 'y'}:
            return True
        if text in {'no', 'false', '0', 'out of stock', 'outofstock', 'unavailable', 'sold out', 'n'}:
            return False
    return default


def _timestamp(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0:
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            moment = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
        except ValueError:
            return 0.0
        return (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)).timestamp()
    return 0.0


def normalise_product(raw):
    """Return (record, issues). A record of None cannot be imported."""
    if not isinstance(raw, dict):
        return None, ['invalid_row']
    issues = []
    name = clean_text(raw.get('name'), 200)
    identifier = raw.get('id')
    if isinstance(identifier, bool) or not isinstance(identifier, (str, int)) or not str(identifier).strip():
        identifier = 'name:' + _slug(name)
    external_id = clean_text(str(identifier), 120)
    price = _price(raw.get('price'))
    if not name:
        issues.append('missing_name')
    if price is None:
        issues.append('invalid_price')
    category = clean_text(raw.get('category'), 80) or 'Products'
    if suspicious(str(raw.get('name') or ''), str(raw.get('category') or ''), name, category):
        issues.append('suspicious_text')
    quantity = raw.get('stock_quantity')
    if isinstance(quantity, str) and quantity.strip().isdecimal():
        quantity = int(quantity)
    if (isinstance(quantity, bool) or not isinstance(quantity, (int, float)) or not math.isfinite(quantity)
            or not 0 <= quantity <= 1_000_000_000):
        quantity = None
    # A counted quantity decides availability, as it does in the console editor.
    in_stock = quantity > 0 if quantity is not None else _flag(raw.get('in_stock'))
    tags = raw.get('tags')
    if isinstance(tags, str):
        tags = tags.split(',')
    tags = [text for text in (clean_text(tag, 40) for tag in (tags if isinstance(tags, list) else [])[:20]) if text]
    record = {
        'external_id': external_id, 'name': name, 'price': price, 'category': category, 'in_stock': in_stock,
        'stock_quantity': quantity, 'sku': clean_text(raw.get('sku'), 80), 'unit': clean_text(raw.get('unit'), 40),
        'tags': [] if suspicious(*tags) else tags, 'active': raw.get('active', True) is not False,
        'source_updated': _timestamp(raw.get('updated_at')),
    }
    if 'missing_name' in issues or 'invalid_price' in issues:
        return None, issues
    return record, issues


def _catalog_index(catalog):
    return {item['sku']: (category, item) for category in catalog.get('categories', []) for item in category['items']}


def _current(category, item):
    return {'name': item['name'], 'price': item['price'], 'category': category['name'],
            'in_stock': item.get('in_stock', True), 'stock_quantity': item.get('stock_quantity')}


def _same(left, right):
    if isinstance(left, (int, float)) and isinstance(right, (int, float)) and not isinstance(left, bool) and not isinstance(right, bool):
        return abs(left - right) < 0.005
    if isinstance(left, str) and isinstance(right, str):
        return left.strip() == right.strip()
    return left == right


# ---- planning ----

def plan_products(catalog, links, records, *, deleted=(), full=False, complete=True, ownership=None, source_id=''):
    """Compare source products with the catalogue. Returns preview rows; writes nothing."""
    owners = {**DEFAULT_OWNERSHIP, **(ownership or {})}
    index = _catalog_index(catalog)
    by_name = {}
    for sku, (_category, item) in index.items():
        by_name.setdefault(_key(item['name']), []).append(sku)
    linked = {link['local_ref'] for link in links.values() if not link['removed']}
    rows, seen = [], set()

    def add(action, external_id, **extra):
        row = {'n': len(rows), 'kind': 'product', 'action': action, 'external_id': external_id,
               'issues': [], 'include': action in {'create', 'update', 'remove'}, **extra}
        rows.append(row)
        return row

    for raw in records:
        record, issues = normalise_product(raw)
        if record is None:
            add('invalid', '', name=clean_text(raw.get('name') if isinstance(raw, dict) else '', 200), issues=issues)
            continue
        external_id = record['external_id']
        if external_id in seen:
            add('invalid', external_id, name=record['name'], issues=['duplicate_in_source'])
            continue
        seen.add(external_id)
        link = links.get(external_id)
        if (link and not full and record['source_updated'] and link['source_updated']
                and record['source_updated'] < link['source_updated']):
            continue  # A delayed, older notification must not undo a newer value.
        values = {field: record[field] for field in PRODUCT_FIELDS}
        common = {'name': record['name'], 'category': record['category'], 'baseline': values,
                  'source_updated': record['source_updated']}
        present = bool(link) and not link['removed'] and link['local_ref'] in index
        if not record['active']:
            if present:
                add('remove', external_id, sku=link['local_ref'], name=index[link['local_ref']][1]['name'],
                    category=index[link['local_ref']][0]['name'], issues=['unpublished_at_source'], baseline=values,
                    source_updated=record['source_updated'])
            continue
        if present:
            category, item = index[link['local_ref']]
            current, changes, conflict = _current(category, item), {}, False
            for field in PRODUCT_FIELDS:
                new, last, now = values[field], link['fields'].get(field, _MISSING), current[field]
                if owners[OWNERSHIP_GROUP[field]] != 'source' or (last is not _MISSING and _same(new, last)):
                    continue  # V7 owns this field, or the source did not change it.
                if _same(new, now) or (field == 'stock_quantity' and new is None):
                    continue
                changes[field] = {'from': now, 'to': new}
                conflict = conflict or (last is not _MISSING and not _same(now, last))
            if not changes:
                add('unchanged', external_id, sku=link['local_ref'], baseline=values, source_updated=record['source_updated'])
                continue
            row = add('conflict' if conflict else 'update', external_id, sku=link['local_ref'], fields=changes, **common)
            row['issues'] = issues + (['edited_in_v7'] if conflict else [])
            old = changes.get('price', {}).get('from')
            if 'price' in changes and isinstance(old, (int, float)) and old > 0 and not 0.5 < changes['price']['to'] / old < 3:
                row['issues'].append('large_price_change')
            continue
        if link and link['removed'] and link['local_ref'] in index:
            continue  # The owner kept this record after the source dropped it: V7 owns it now.
        if link and link['fields'].get('_declined'):
            if all(_same(values[field], link['fields'].get(field)) for field in PRODUCT_FIELDS):
                continue  # The owner already said no to exactly this record.
            row = add('create', external_id, sku=_new_sku(source_id, external_id, index), record=record, **common)
            row['issues'], row['include'] = issues + ['previously_declined'], False
            continue
        if link and not link['removed']:
            # It was removed in V7 by a person. Respect that until the source changes it.
            if all(_same(values[field], link['fields'].get(field)) for field in PRODUCT_FIELDS):
                continue
            row = add('create', external_id, sku=link['local_ref'], record=record, **common)
            row['issues'], row['include'] = issues + ['removed_in_v7'], False
            continue
        match = None
        if link is None:
            if record['sku'] and record['sku'] in index and record['sku'] not in linked:
                match = record['sku']
            else:
                candidates = [sku for sku in by_name.get(_key(record['name']), []) if sku not in linked]
                match = candidates[0] if len(candidates) == 1 else None
        if match:
            category, item = index[match]
            current = _current(category, item)
            changes = {field: {'from': current[field], 'to': values[field]} for field in PRODUCT_FIELDS
                       if owners[OWNERSHIP_GROUP[field]] == 'source' and not _same(values[field], current[field])
                       and not (field == 'stock_quantity' and values[field] is None)}
            linked.add(match)
            if changes:
                row = add('update', external_id, sku=match, fields=changes, **common)
                row['issues'] = issues + ['matched_existing']
            else:
                add('unchanged', external_id, sku=match, baseline=values, source_updated=record['source_updated'])
            continue
        sku = link['local_ref'] if link else _new_sku(source_id, external_id, index)
        row = add('create', external_id, sku=sku, record=record, **common)
        row['issues'] = issues
        index.setdefault(sku, ({'name': record['category']}, {'name': record['name']}))

    def removal(external_id, issue):
        link = links.get(external_id)
        if link and not link['removed'] and link['local_ref'] in index and external_id not in seen:
            category, item = index[link['local_ref']]
            row = add('remove', external_id, sku=link['local_ref'], name=item['name'], category=category['name'])
            row['issues'] = [issue]
            seen.add(external_id)

    for identifier in deleted:
        if isinstance(identifier, (str, int)) and not isinstance(identifier, bool):
            removal(clean_text(str(identifier), 120), 'deleted_at_source')
    if full and complete:
        for external_id in list(links):
            removal(external_id, 'missing_from_source')
    return rows


def _new_sku(source_id, external_id, index):
    base = 'src_' + source_id[:6] + '_' + _slug(external_id)
    sku, counter = base, 2
    while sku in index:
        sku, counter = f'{base}_{counter}', counter + 1
    return sku


def plan_faqs(faqs, links, records):
    existing = {_key(row['q']): row for row in faqs if isinstance(row, dict) and isinstance(row.get('q'), str)}
    rows, seen = [], set()
    for raw in records:
        question = clean_text(raw.get('question', raw.get('q')) if isinstance(raw, dict) else '', 300)
        answer = clean_text(raw.get('answer', raw.get('a')) if isinstance(raw, dict) else '', 2000)
        key = _key(question)
        row = {'n': len(rows), 'kind': 'faq', 'external_id': key[:120], 'name': question, 'issues': [], 'include': True}
        rows.append(row)
        if not key or not answer or key in seen:
            row.update(action='invalid', include=False, issues=['duplicate_in_source' if key in seen else 'missing_answer'])
            continue
        seen.add(key)
        if suspicious(question, answer, str(raw.get('answer', raw.get('a')) or '')):
            row['issues'].append('suspicious_text')
        tags = raw.get('tags')
        tags = [text for text in (clean_text(tag, 40) for tag in (tags if isinstance(tags, list) else [])[:10]) if text]
        row.update(record={'q': question, 'a': answer, 'tags': tags}, baseline={'a': answer})
        current, link = existing.get(key), links.get(key[:120])
        if current is None:
            row['action'] = 'create'
        elif current['a'].strip() == answer:
            row.update(action='unchanged', include=False)
        elif link and current['a'].strip() == str(link['fields'].get('a', '')).strip():
            row.update(action='update', fields={'answer': {'from': current['a'], 'to': answer}})
        else:
            # A hand-written answer stays unless the owner chooses the imported one.
            row.update(action='conflict', include=False, fields={'answer': {'from': current['a'], 'to': answer}},
                       issues=row['issues'] + ['edited_in_v7'])
    return rows


def plan_locations(branches, records):
    existing = {_key(row['name']): row for row in branches if isinstance(row, dict) and isinstance(row.get('name'), str)}
    rows, seen = [], set()
    for raw in records:
        raw = raw if isinstance(raw, dict) else {}
        name = clean_text(raw.get('name'), 120)
        key = _key(name)
        row = {'n': len(rows), 'kind': 'location', 'external_id': key[:120], 'name': name, 'issues': [], 'include': True}
        rows.append(row)
        hours = raw.get('hours') if isinstance(raw.get('hours'), dict) else {}
        hours = {day: clean_text(hours[day], 40) for day in DAYS if clean_text(hours.get(day), 40)}
        record = {'name': name, 'address': clean_text(raw.get('address'), 300), 'postcode': clean_text(raw.get('postcode'), 12),
                  'phone': clean_text(raw.get('phone'), 40), 'hours': hours}
        if not key or key in seen:
            row.update(action='invalid', include=False, issues=['duplicate_in_source' if key in seen else 'missing_name'])
            continue
        seen.add(key)
        if suspicious(name, record['address'], *hours.values()):
            row['issues'].append('suspicious_text')
        current = existing.get(key)
        if current is None:
            if len(record['postcode']) < 2:
                row.update(action='invalid', include=False, issues=['missing_postcode'])
                continue
            row.update(action='create', record=record)
            continue
        changes = {field: {'from': current.get(field, {} if field == 'hours' else ''), 'to': record[field]}
                   for field in ('address', 'postcode', 'phone', 'hours')
                   if record[field] and record[field] != current.get(field)}
        row.update(action='update' if changes else 'unchanged', include=bool(changes), fields=changes, record=record)
        if changes:
            row['issues'].append('matched_existing')
    return rows


def review_reasons(rows, *, first, auto_apply, linked_count):
    """Why a person must look before anything is written. Empty means safe to apply."""
    reasons = []
    if first:
        reasons.append('first_import')
    if not auto_apply:
        reasons.append('approval_required')
    actions = [row['action'] for row in rows]
    issues = {issue for row in rows for issue in row['issues']}
    if 'conflict' in actions:
        reasons.append('conflicting_edits')
    for issue in ('suspicious_text', 'large_price_change', 'matched_existing', 'removed_in_v7',
                  'previously_declined', 'currency_mismatch'):
        if issue in issues:
            reasons.append(issue)
    missing = [row for row in rows if row['action'] == 'remove' and 'missing_from_source' in row['issues']]
    if missing:
        active = sum(action in {'create', 'update', 'unchanged', 'conflict'} for action in actions)
        reason = 'empty_source' if not active else 'many_removals' if len(missing) > max(3, linked_count * 0.2) else ''
        if reason:
            reasons.append(reason)
            for row in missing:
                row['include'] = False  # Never empty a catalogue because a source looked empty.
    for row in rows:
        if 'suspicious_text' in row['issues']:
            row['include'] = False
    return reasons


def summarise(rows, reasons=(), **extra):
    counts = {}
    for row in rows:
        counts[row['action']] = counts.get(row['action'], 0) + 1
    return {'counts': counts, 'reasons': list(reasons), **extra}


# ---- applying ----

def _read(storage, tenant, filename):
    try:
        return storage.read_json(tenant, filename)
    except FileNotFoundError:
        return {'version': 1, 'categories': []} if filename == 'catalog.json' else []


def _category(catalog, name):
    for category in catalog['categories']:
        if _key(category['name']) == _key(name):
            return category
    used = {category['id'] for category in catalog['categories']}
    base = identifier = _slug(name, 'category')
    counter = 2
    while identifier in used:
        identifier, counter = f'{base}_{counter}', counter + 1
    category = {'id': identifier, 'name': name, 'items': []}
    catalog['categories'].append(category)
    return category


def _apply_product(catalog, row, outcome):
    index = _catalog_index(catalog)
    sku, found = row['sku'], index.get(row['sku'])
    if row['action'] == 'remove':
        if found:
            found[0]['items'].remove(found[1])
        return
    if row['action'] == 'create' and not found:
        record = row['record']
        item = {'sku': sku, 'name': record['name'], 'price': record['price'], 'in_stock': record['in_stock']}
        if record['stock_quantity'] is not None:
            item['stock_quantity'] = record['stock_quantity']
        if record['unit']:
            item['unit'] = record['unit']
        if record['tags']:
            item['tags'] = record['tags']
        _category(catalog, record['category'])['items'].append(item)
        return
    if not found:
        outcome[row['n']] = 'missing_in_v7'
        return
    category, item = found
    changes = row.get('fields') or {field: {'from': _MISSING, 'to': row['record'][field]} for field in PRODUCT_FIELDS}
    current = _current(category, item)
    for field, change in changes.items():
        if change['from'] is not _MISSING and not _same(current[field], change['from']) and not _same(current[field], change['to']):
            outcome[row['n']] = 'changed_since_preview'
            continue
        if field == 'category':
            category['items'].remove(item)
            category = _category(catalog, change['to'])
            category['items'].append(item)
        elif field == 'stock_quantity':
            if change['to'] is not None:
                item['stock_quantity'] = change['to']
        else:
            item[field] = change['to']


def apply_rows(storage, tenant, rows):
    """Write the included rows atomically per document. Returns (before, after_revisions, outcome)."""
    wanted = [row for row in rows if row.get('include') and row['action'] in {'create', 'update', 'conflict', 'remove'}]
    before, after, outcome = {}, {}, {}
    if not wanted:
        return before, after, outcome
    with storage.write_lock(tenant):
        documents = {}
        for row in wanted:
            filename = {'product': 'catalog.json', 'faq': 'faq.json', 'location': 'branches.json'}[row['kind']]
            if filename not in documents:
                original = _read(storage, tenant, filename)
                if filename == 'catalog.json' and (not isinstance(original, dict) or 'categories' not in original):
                    raise SyncError('legacy_catalogue')
                documents[filename] = (original, copy.deepcopy(original))
            document = documents[filename][1]
            if row['kind'] == 'product':
                _apply_product(document, row, outcome)
            elif row['kind'] == 'faq':
                match = next((item for item in document if _key(item.get('q', '')) == _key(row['record']['q'])), None)
                if match is None:
                    document.append({key: value for key, value in row['record'].items() if value or key != 'tags'})
                else:
                    match['a'] = row['record']['a']
            else:
                record = {key: value for key, value in row['record'].items() if value}
                match = next((item for item in document if _key(item.get('name', '')) == _key(record['name'])), None)
                if match is None:
                    used = {item.get('id') for item in document}
                    base = identifier = _slug(record['name'], 'location')
                    counter = 2
                    while identifier in used:
                        identifier, counter = f'{base}_{counter}', counter + 1
                    document.append({'id': identifier, 'lat': None, 'lon': None, **record})
                else:
                    match.update(record)
        for filename, (original, document) in documents.items():
            if filename == 'catalog.json':
                document['categories'] = [category for category in document['categories'] if category['items']]
                skus = [item['sku'] for category in document['categories'] for item in category['items']]
                if len(skus) != len(set(skus)):
                    raise SyncError('duplicate_product_reference')
                if isinstance(document.get('version'), int):
                    document['version'] += 1
            if revision(document) == revision(original):
                continue
            storage._validate_json(document, storage._schema_path(SCHEMAS[filename]))
            before[filename] = original
        try:
            for filename in before:
                storage._write_json(tenant, filename, documents[filename][1], schema=SCHEMAS[filename])
                after[filename] = revision(documents[filename][1])
        except ValueError as exc:
            raise SyncError('location_limit_reached' if str(exc) == 'location_limit_reached' else 'invalid_business_data') from None
    if 'catalog.json' in before:
        try:
            from service.product_metrics import record_inventory
            record_inventory(tenant, before['catalog.json'], documents['catalog.json'][1])
        except Exception:
            pass  # Stock history is optional reporting, never a reason to fail a sync.
    return before, after, outcome


def record_links(tenant, source_id, rows, outcome=None):
    """Remember what each source record last said, including choices to decline it."""
    outcome, saved = outcome or {}, []
    for row in rows:
        if row['action'] == 'invalid' or not row.get('external_id') or outcome.get(row['n']):
            continue
        included, baseline = bool(row.get('include')), dict(row.get('baseline') or {})
        item = {'kind': row['kind'], 'external_id': row['external_id'], 'local_ref': row.get('sku') or row['external_id'],
                'fields': baseline, 'source_updated': row.get('source_updated') or 0, 'removed': False}
        if row['action'] == 'remove':
            item['removed'] = True  # Removed, or kept here as a V7-only record from now on.
        elif row['action'] == 'create' and not included:
            item['fields'] = {**baseline, '_declined': True}
        elif row['kind'] != 'product' and not included and row['action'] != 'unchanged':
            continue
        saved.append(item)
    if saved:
        store.save_items(tenant, source_id, saved)


def apply_changeset(container, tenant, changeset_id, *, actor, expected_version=None):
    changeset = store.get_changeset(tenant, changeset_id)
    if changeset is None:
        raise SyncError('change_not_found')
    if changeset['state'] != 'pending' or (expected_version is not None and changeset['version'] != expected_version):
        raise SyncError('change_already_handled')
    before, after, outcome = apply_rows(container.storage, tenant, changeset['changes'])
    record_links(tenant, changeset['source_id'], changeset['changes'], outcome)
    summary = {**changeset['summary'], 'skipped': len(outcome),
               'applied': sum(1 for row in changeset['changes']
                              if row.get('include') and row['action'] in {'create', 'update', 'conflict', 'remove'}
                              and row['n'] not in outcome)}
    result = store.update_changeset(tenant, changeset_id, changeset['version'], state='applied', summary=summary,
                                    before_docs=before or '', after_revisions=after or '', actor=actor)
    if before:
        container.invalidate_tenant(tenant)
    _audit(tenant, 'sync.apply', changeset_id, actor, {name: {'before': revision(doc), 'after': after[name]}
                                                       for name, doc in before.items()})
    return result


def reject_changeset(tenant, changeset_id, *, actor, expected_version=None):
    changeset = store.get_changeset(tenant, changeset_id)
    if changeset is None:
        raise SyncError('change_not_found')
    if changeset['state'] != 'pending' or (expected_version is not None and changeset['version'] != expected_version):
        raise SyncError('change_already_handled')
    # Declining is remembered, so the same proposal is not raised again each sync.
    record_links(tenant, changeset['source_id'], [{**row, 'include': False} for row in changeset['changes']
                                                  if row['action'] != 'unchanged'])
    _audit(tenant, 'sync.reject', changeset_id, actor, {})
    return store.update_changeset(tenant, changeset_id, changeset['version'], state='rejected', actor=actor)


def rollback(container, tenant, changeset_id, *, actor):
    """Restore the documents exactly as they were, only if nothing changed since."""
    changeset = store.get_changeset(tenant, changeset_id, with_docs=True)
    if changeset is None:
        raise SyncError('change_not_found')
    if changeset['state'] != 'applied' or not changeset['before_docs']:
        raise SyncError('undo_unavailable')
    storage = container.storage
    with storage.write_lock(tenant):
        for filename, expected in changeset['after_revisions'].items():
            if revision(_read(storage, tenant, filename)) != expected:
                raise SyncError('changed_since_import')
        for filename, document in changeset['before_docs'].items():
            storage._write_json(tenant, filename, document, schema=SCHEMAS[filename])
    container.invalidate_tenant(tenant)
    _audit(tenant, 'sync.undo', changeset_id, actor, {})
    return store.update_changeset(tenant, changeset_id, changeset['version'], state='rolled_back', before_docs='', actor=actor)


def _audit(tenant, action, target, actor, details):
    from service.audit import AuditService
    AuditService().record(user=str(actor), role='data_source', ip='', action=action, target=f'{tenant}/{target}',
                          extra={'tenant': tenant, 'source': 'Business Sync', 'result': 'success', 'documents': details})


def stage(container, tenant, source, rows, *, origin, actor, first, extra=None):
    """Store a plan, and apply it at once when no person needs to look."""
    links = store.items(tenant, source['id'])
    reasons = review_reasons(rows, first=first, auto_apply=source['auto_apply'],
                             linked_count=sum(not link['removed'] for link in links.values()))
    actionable = [row for row in rows if row['action'] not in {'unchanged', 'invalid'}]
    if not actionable:
        record_links(tenant, source['id'], rows)
        return None, summarise(rows, **(extra or {}))
    fingerprint = hashlib.sha256(repr(sorted(
        (row['kind'], row['external_id'], row['action'], repr(row.get('fields')), repr(row.get('baseline')))
        for row in actionable)).encode()).hexdigest()[:16]
    summary = summarise(rows, reasons, source_label=source['label'], source_kind=source['kind'],
                        fingerprint=fingerprint, **(extra or {}))
    pending = store.pending_changeset(tenant, source['id'])
    if pending and reasons:
        waiting = store.get_changeset(tenant, pending)
        if waiting['summary'].get('fingerprint') == fingerprint:
            return waiting, waiting['summary']  # Same proposal: keep the review a person may have open.
    changeset = store.create_changeset(tenant, source['id'], origin, summary, rows, actor=actor)
    if not reasons:
        changeset = apply_changeset(container, tenant, changeset['id'], actor=actor)
    return changeset, summary
