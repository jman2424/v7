"""Tenant-owned navigation targets; models select IDs, never invent URLs."""
import hashlib
import re
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from service.website_knowledge import _validate_public_https_url

FILENAME = 'website_destinations.json'


def buttonize_reply(text, destinations, actions=None):
    """Convert exact approved links after rendering, including extractive FAQs.

    Never infer a destination from a hostname or enable a disabled URL. Preserve
    unapproved links as text; only configured public targets become UI actions.
    """
    approved = {row['url']: row for row in destinations if row.get('enabled', True)}
    pattern = r'\[[^\]\n]*\]\((?P<markdown>https?://[^\s)]+)\)|(?P<bare>https?://[^\s<>\)\]]+)'
    original = [row for row in (actions or []) if isinstance(row, dict)]
    # Explicit links in the answer take precedence over extra model suggestions.
    # Otherwise three booking variants can consume every slot and leave the
    # customer's requested social destinations as bare URLs.
    result = [row for row in original if row.get('type') != 'navigate'][:3]
    for match in re.finditer(pattern, text):
        url = match.group('markdown') or match.group('bare').rstrip('.,;:!?')
        target = approved.get(url)
        if target and len(result) < 3 and not any(row.get('url') == url for row in result):
            result.append({'type': 'navigate', 'label': target['label'], 'url': url})
    for row in original:
        if len(result) < 3 and row.get('type') == 'navigate' and not any(item.get('url') == row.get('url') for item in result):
            result.append(row)

    def replace(match):
        url = match.group('markdown') or match.group('bare').rstrip('.,;:!?')
        target = approved.get(url)
        if target is None:
            return match.group(0)
        if not any(row.get('type') == 'navigate' and row.get('url') == url for row in result):
            if len(result) >= 3:
                return match.group(0)
            result.append({'type': 'navigate', 'label': target['label'], 'url': url})
        suffix = '' if match.group('markdown') else match.group('bare')[len(url):]
        return target['label'] + suffix

    text = re.sub(pattern, replace, text)
    return text, result


def validate(value):
    if not isinstance(value, list) or len(value) > 30:
        raise ValueError('Use at most 30 website destinations.')
    result, seen = [], set()
    for row in value:
        if not isinstance(row, dict) or set(row) - {'id', 'label', 'url', 'purpose', 'enabled'}:
            raise ValueError('Invalid website destination.')
        identifier = row.get('id')
        if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', identifier) or identifier in seen:
            raise ValueError('Destination IDs must be unique.')
        label, purpose, url = row.get('label'), row.get('purpose', ''), row.get('url')
        if (not isinstance(label, str) or not 1 <= len(label.strip()) <= 80
                or not isinstance(purpose, str) or len(purpose) > 400
                or type(row.get('enabled', True)) is not bool):
            raise ValueError('Invalid destination label or purpose.')
        normalized = _validate_public_https_url(url)
        parsed = urlsplit(normalized)
        if any(key.lower() in {'api_key', 'apikey', 'access_token', 'password', 'secret', 'client_secret'}
               for key, _ in parse_qsl(parsed.query)):
            raise ValueError('Website destinations must not contain credentials.')
        fragment = urlsplit(url).fragment
        result.append({'id': identifier, 'label': label.strip(), 'purpose': purpose.strip(),
                       'url': urlunsplit((*parsed[:4], fragment)), 'enabled': row.get('enabled', True)})
        seen.add(identifier)
    return result


def load(storage, tenant):
    try:
        return validate(storage.read_json(tenant, FILENAME))
    except FileNotFoundError:
        return []


def public_targets(configured, knowledge, website):
    targets = [row for row in configured if row['enabled']]
    # Explicitly disabled destinations must not return as imported suggestions.
    seen = {row['url'] for row in configured}
    host = urlsplit(website).hostname if isinstance(website, str) else None
    pages = knowledge.get('pages', []) if isinstance(knowledge, dict) else []
    for page in pages[:20] if isinstance(pages, list) else []:
        if not isinstance(page, dict):
            continue
        url = page.get('url')
        try:
            url = _validate_public_https_url(url, expected_host=host or '__unconfigured__')
        except ValueError:
            continue
        if url in seen or re.search(r'/(?:admin|console|login|logout|signout|account)(?:/|$)', urlsplit(url).path, re.I):
            continue
        targets.append({'id': 'page_' + hashlib.sha256(url.encode()).hexdigest()[:12],
                        'label': str(page.get('title') or urlsplit(url).path)[:80],
                        'url': url, 'purpose': 'Open this imported business page.', 'enabled': True})
        seen.add(url)
        if len(targets) >= 40:
            break
    return targets
