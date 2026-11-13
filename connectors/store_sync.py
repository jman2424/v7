"""Read-only product adapters for WooCommerce, Shopify and custom JSON feeds.

Every adapter returns the same plain product rows. Nothing here writes to a
store, follows a redirect or leaves the single host the owner authorised.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import time
from urllib.parse import urlencode, urlsplit

from service.sync_http import SyncHttpError, public_host, request_json

MAX_PRODUCTS = 10000
_SHOPIFY_HOST = re.compile(r'[a-z0-9][a-z0-9-]{0,60}\.myshopify\.com\Z')
_SHOPIFY_VERSION = re.compile(r'20\d\d-(01|04|07|10)\Z')
_SHOPIFY_QUERY = '''query($cursor:String){products(first:100,after:$cursor,sortKey:ID){
pageInfo{hasNextPage endCursor} nodes{legacyResourceId title status productType updatedAt
totalInventory tracksInventory priceRangeV2{minVariantPrice{amount currencyCode}}
variants(first:1){nodes{sku}}}}}'''


class ConnectionError_(ValueError):
    """Owner-correctable connection details; the message is a safe code."""


def _text(data, key, limit, *, required=True):
    value = data.get(key, '')
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ConnectionError_('invalid_connection_details')
    return value.strip()


def prepare(kind, data):
    """Validate owner-supplied connection details. Returns (config, credentials)."""
    if not isinstance(data, dict):
        raise ConnectionError_('invalid_connection_details')
    if kind == 'woocommerce':
        try:
            host = public_host(_text(data, 'store_url', 500))
        except SyncHttpError:
            raise ConnectionError_('invalid_store_address') from None
        return {'host': host}, {'consumer_key': _text(data, 'consumer_key', 200),
                                'consumer_secret': _text(data, 'consumer_secret', 200),
                                'webhook_secret': secrets.token_urlsafe(32)}
    if kind == 'shopify':
        host = _text(data, 'shop_domain', 200).lower().removeprefix('https://').strip('/')
        if not _SHOPIFY_HOST.fullmatch(host):
            raise ConnectionError_('invalid_store_address')
        version = os.getenv('V7_SHOPIFY_API_VERSION', '2026-07').strip()
        if not _SHOPIFY_VERSION.fullmatch(version):
            raise ConnectionError_('invalid_connection_details')
        token = _text(data, 'access_token', 300, required=False)
        client_id = _text(data, 'client_id', 200, required=False)
        client_secret = _text(data, 'client_secret', 300, required=False)
        if not token and not (client_id and client_secret):
            raise ConnectionError_('invalid_connection_details')
        credentials = {'access_token': token} if token else {'client_id': client_id, 'client_secret': client_secret}
        # Shopify signs webhooks with the app's secret key.
        credentials['webhook_secret'] = client_secret or _text(data, 'api_secret', 300, required=False)
        return {'host': host, 'api_version': version}, credentials
    if kind == 'custom_feed':
        url = _text(data, 'feed_url', 1000)
        try:
            host = public_host(url)
        except SyncHttpError:
            raise ConnectionError_('invalid_store_address') from None
        parts = urlsplit(url)
        if parts.query or parts.fragment:
            raise ConnectionError_('invalid_store_address')
        return ({'host': host, 'path': parts.path or '/'},
                {'token': _text(data, 'access_token', 500, required=False),
                 'webhook_secret': secrets.token_urlsafe(32)})
    raise ConnectionError_('unsupported_source')


# ---- fetching the whole product list ----

def _woo_row(product):
    categories = product.get('categories') or []
    return {
        'id': product.get('id'), 'name': product.get('name'), 'price': product.get('price'),
        'sku': product.get('sku') or '',
        'category': categories[0].get('name') if categories and isinstance(categories[0], dict) else '',
        'in_stock': product.get('stock_status') in {'instock', 'onbackorder'},
        'stock_quantity': product.get('stock_quantity') if product.get('manage_stock') is True else None,
        'active': product.get('status') == 'publish' and product.get('catalog_visibility', 'visible') != 'hidden',
        'updated_at': (product.get('date_modified_gmt') or '') + ('Z' if product.get('date_modified_gmt') else ''),
    }


def _fetch_woocommerce(config, credentials):
    basic = base64.b64encode(f"{credentials['consumer_key']}:{credentials['consumer_secret']}".encode()).decode()
    rows, page = [], 1
    while len(rows) < MAX_PRODUCTS:
        query = urlencode({'per_page': 50, 'page': page, 'orderby': 'id', 'order': 'asc', 'status': 'any'})
        data, headers = request_json(f"https://{config['host']}/wp-json/wc/v3/products?{query}",
                                     host=config['host'], headers={'Authorization': 'Basic ' + basic})
        if not isinstance(data, list):
            raise SyncHttpError('source_invalid_response')
        rows.extend(_woo_row(item) for item in data if isinstance(item, dict))
        total = headers.get('x-wp-totalpages', '')
        if len(data) < 50 or (total.isdecimal() and page >= int(total)):
            return {'records': rows, 'complete': True}
        page += 1
    return {'records': rows, 'complete': False}


def _shopify_token(config, credentials):
    if credentials.get('access_token'):
        return credentials['access_token']
    data, _ = request_json(f"https://{config['host']}/admin/oauth/access_token", host=config['host'], body={
        'client_id': credentials['client_id'], 'client_secret': credentials['client_secret'],
        'grant_type': 'client_credentials'})
    token = data.get('access_token') if isinstance(data, dict) else None
    if not isinstance(token, str) or not token:
        raise SyncHttpError('source_access_denied')
    return token


def _fetch_shopify(config, credentials):
    token, rows, cursor, currency = _shopify_token(config, credentials), [], None, ''
    url = f"https://{config['host']}/admin/api/{config['api_version']}/graphql.json"
    for _ in range(MAX_PRODUCTS // 100):
        data, _headers = request_json(url, host=config['host'], headers={'X-Shopify-Access-Token': token},
                                      body={'query': _SHOPIFY_QUERY, 'variables': {'cursor': cursor}})
        try:
            if data.get('errors'):
                throttled = any((error.get('extensions') or {}).get('code') == 'THROTTLED' for error in data['errors'])
                raise SyncHttpError('source_unavailable', retry=throttled)
            products = data['data']['products']
            for node in products['nodes']:
                minimum = node['priceRangeV2']['minVariantPrice']
                currency = minimum.get('currencyCode') or currency
                variants = (node.get('variants') or {}).get('nodes') or []
                rows.append({
                    'id': node['legacyResourceId'], 'name': node.get('title'), 'price': minimum.get('amount'),
                    'sku': (variants[0].get('sku') or '') if variants else '',
                    'category': node.get('productType') or '',
                    'in_stock': not node.get('tracksInventory') or (node.get('totalInventory') or 0) > 0,
                    'stock_quantity': node.get('totalInventory') if node.get('tracksInventory') else None,
                    'active': node.get('status') == 'ACTIVE', 'updated_at': node.get('updatedAt') or '',
                })
            if not products['pageInfo']['hasNextPage']:
                return {'records': rows, 'complete': True, 'currency': currency}
            cursor = products['pageInfo']['endCursor']
        except (KeyError, TypeError, AttributeError):
            raise SyncHttpError('source_invalid_response') from None
    return {'records': rows, 'complete': False, 'currency': currency}


def _fetch_custom(config, credentials):
    headers = {'Authorization': 'Bearer ' + credentials['token']} if credentials.get('token') else {}
    data, _ = request_json(f"https://{config['host']}{config['path']}", host=config['host'], headers=headers)
    products = data.get('products') if isinstance(data, dict) else data
    if not isinstance(products, list) or len(products) > MAX_PRODUCTS:
        raise SyncHttpError('source_invalid_response')
    currency = data.get('currency', '') if isinstance(data, dict) else ''
    return {'records': [row for row in products if isinstance(row, dict)], 'complete': True,
            'currency': currency if isinstance(currency, str) else ''}


def fetch_all(kind, config, credentials):
    """Return {'records': [...], 'complete': bool}. Raises SyncHttpError."""
    fetcher = {'woocommerce': _fetch_woocommerce, 'shopify': _fetch_shopify, 'custom_feed': _fetch_custom}.get(kind)
    if fetcher is None:
        raise SyncHttpError('unsupported_source')
    return fetcher(config, credentials)


# ---- signed change notifications (webhooks) ----

def _hmac_base64(secret, raw):
    return base64.b64encode(hmac.new(secret.encode(), raw, hashlib.sha256).digest())


def verify_webhook(kind, config, credentials, headers, raw):
    """True only for a body signed with this source's own secret."""
    secret = credentials.get('webhook_secret') or ''
    if not secret or not isinstance(raw, bytes):
        return False
    if kind == 'woocommerce':
        return hmac.compare_digest(_hmac_base64(secret, raw), headers.get('X-WC-Webhook-Signature', '').encode())
    if kind == 'shopify':
        return (headers.get('X-Shopify-Shop-Domain', '').lower() == config.get('host')
                and hmac.compare_digest(_hmac_base64(secret, raw), headers.get('X-Shopify-Hmac-Sha256', '').encode()))
    if kind == 'custom_feed':
        parts = dict(part.strip().split('=', 1) for part in headers.get('X-V7-Signature', '').split(',') if '=' in part)
        timestamp, supplied = parts.get('t', ''), parts.get('s', '')
        if not timestamp.isascii() or not timestamp.isdecimal() or len(timestamp) > 12 or abs(time.time() - int(timestamp)) > 300:
            return False
        expected = hmac.new(secret.encode(), timestamp.encode() + b'.' + raw, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected.encode(), supplied.encode())
    return False


def _shopify_webhook_row(product):
    variants = [row for row in product.get('variants') or [] if isinstance(row, dict)]
    prices = []
    for row in variants:
        try:
            prices.append(float(row.get('price')))
        except (TypeError, ValueError):
            continue
    tracked = [row for row in variants if row.get('inventory_management')]
    return {
        'id': product.get('id'), 'name': product.get('title'), 'price': min(prices) if prices else None,
        'sku': (variants[0].get('sku') or '') if variants else '', 'category': product.get('product_type') or '',
        'in_stock': not tracked or any((row.get('inventory_quantity') or 0) > 0 or row.get('inventory_policy') == 'continue'
                                       for row in variants),
        'stock_quantity': sum(row.get('inventory_quantity') or 0 for row in tracked) if tracked else None,
        'active': product.get('status') == 'active', 'updated_at': product.get('updated_at') or '',
    }


def parse_webhook(kind, headers, payload, raw):
    """Return {'event_id', 'records', 'deleted', 'replace'} or None when the topic is not about products."""
    if not isinstance(payload, dict):
        return None
    digest = hashlib.sha256(raw).hexdigest()
    if kind == 'woocommerce':
        topic = headers.get('X-WC-Webhook-Topic', '')
        if topic not in {'product.created', 'product.updated', 'product.restored', 'product.deleted'}:
            return None
        event = headers.get('X-WC-Webhook-Delivery-ID') or digest
        if topic == 'product.deleted':
            return {'event_id': event, 'records': [], 'deleted': [payload.get('id')]}
        return {'event_id': event, 'records': [_woo_row(payload)], 'deleted': []}
    if kind == 'shopify':
        topic = headers.get('X-Shopify-Topic', '')
        if topic not in {'products/create', 'products/update', 'products/delete'}:
            return None
        event = headers.get('X-Shopify-Event-Id') or headers.get('X-Shopify-Webhook-Id') or digest
        if topic == 'products/delete':
            return {'event_id': event, 'records': [], 'deleted': [payload.get('id')]}
        return {'event_id': event, 'records': [_shopify_webhook_row(payload)], 'deleted': []}
    if kind == 'custom_feed':
        records = payload.get('products', [])
        deleted = payload.get('deleted_ids', [])
        if (not isinstance(records, list) or not isinstance(deleted, list)
                or len(records) + len(deleted) > 2000 or payload.get('event') not in {'changed', 'replace'}):
            return None
        return {'event_id': digest, 'records': [row for row in records if isinstance(row, dict)],
                'deleted': deleted, 'replace': payload['event'] == 'replace'}
    return None
