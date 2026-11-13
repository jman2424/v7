"""Read an uploaded CSV file or JSON bundle into plain rows; validation happens later."""
from __future__ import annotations

import csv
import io
import json

MAX_PRODUCTS, MAX_FAQS, MAX_LOCATIONS = 10000, 500, 50
_PRODUCT_COLUMNS = {
    'id': ('id', 'product id', 'external id', 'reference'),
    'name': ('name', 'title', 'product', 'product name', 'service', 'service name', 'item'),
    'price': ('price', 'regular price', 'sale price', 'amount', 'cost', 'variant price'),
    'category': ('category', 'categories', 'type', 'product type', 'collection'),
    'sku': ('sku', 'variant sku', 'code'),
    'in_stock': ('in stock', 'in_stock', 'stock', 'stock status', 'availability', 'available'),
    'stock_quantity': ('stock quantity', 'stock_quantity', 'quantity', 'qty', 'inventory', 'variant inventory qty'),
    'unit': ('unit',), 'tags': ('tags',),
}
_FAQ_COLUMNS = {'question': ('question', 'q'), 'answer': ('answer', 'a'), 'tags': ('tags', 'topics')}


class ImportFormatError(ValueError):
    """The message is a safe code shown to the person importing."""


def _columns(header, wanted):
    names = [' '.join(str(cell or '').replace('_', ' ').casefold().split()) for cell in header]
    found = {}
    for field, aliases in wanted.items():
        for alias in aliases:
            alias = alias.replace('_', ' ')
            if alias in names and field not in found:
                found[field] = names.index(alias)
    return found


def _csv(text):
    try:
        dialect = csv.Sniffer().sniff(text[:4000], delimiters=',;\t')
    except csv.Error:
        dialect = csv.excel
    rows = [row for row in csv.reader(io.StringIO(text), dialect) if any(cell.strip() for cell in row)]
    if len(rows) < 2:
        raise ImportFormatError('import_file_empty')
    if len(rows) > MAX_PRODUCTS + 1:
        raise ImportFormatError('import_too_large')
    faq = _columns(rows[0], _FAQ_COLUMNS)
    if {'question', 'answer'} <= set(faq):
        return {'faqs': [{field: row[index].strip() if index < len(row) else '' for field, index in faq.items()}
                         | ({'tags': [tag.strip() for tag in row[faq['tags']].split(',')]}
                            if 'tags' in faq and faq['tags'] < len(row) else {})
                         for row in rows[1:]]}
    product = _columns(rows[0], _PRODUCT_COLUMNS)
    if not {'name', 'price'} <= set(product):
        raise ImportFormatError('import_columns_missing')
    return {'products': [{field: row[index].strip() for field, index in product.items()
                          if index < len(row) and row[index].strip()} for row in rows[1:]]}


def parse(file_format, content):
    """Return {'products': [...], 'faqs': [...], 'locations': [...]} of untrusted raw rows."""
    if not isinstance(content, str) or not content.strip():
        raise ImportFormatError('import_file_empty')
    content = content.lstrip('﻿')
    if file_format == 'csv':
        data = _csv(content)
    elif file_format == 'json':
        try:
            data = json.loads(content)
        except ValueError:
            raise ImportFormatError('import_file_unreadable') from None
        if isinstance(data, list):
            data = {'products': data}
        if not isinstance(data, dict):
            raise ImportFormatError('import_file_unreadable')
    else:
        raise ImportFormatError('import_format_unsupported')
    result = {}
    for key, aliases, limit in (('products', ('products', 'services', 'items'), MAX_PRODUCTS),
                                ('faqs', ('faqs', 'questions', 'policies'), MAX_FAQS),
                                ('locations', ('locations', 'branches'), MAX_LOCATIONS)):
        rows = []
        for alias in aliases:
            if isinstance(data.get(alias), list):
                rows.extend(data[alias])
        if len(rows) > limit:
            raise ImportFormatError('import_too_large')
        result[key] = rows
    if not any(result.values()):
        raise ImportFormatError('import_file_empty')
    return result
