"""Business-owned channel preferences beneath explicit platform grants.

Addresses/numbers and credentials are bound by the platform, never by inbound
messages or a tenant-editable environment-variable name.
"""
from __future__ import annotations

import copy
import json
import os
import re

CHANNELS = ('email', 'phone')
FILENAME = 'business_channels.json'
GRANTS_FILE = 'business_channel_grants.json'
DEFAULTS = {channel: {'enabled': False, 'mode': 'review', 'daily_limit': 50,
                      'retention_days': 30, 'privacy_confirmed': False, 'language': 'en-GB'} for channel in CHANNELS}
LANGUAGES = ('en-GB', 'en-US', 'fr-FR', 'es-ES', 'de-DE')
PHONE = re.compile(r'\+[1-9][0-9]{7,14}\Z')
UUID = re.compile(r'[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}\Z')
_LOCAL = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!#$%&'*+/=?^_`{|}~.-")
_HOST = frozenset('abcdefghijklmnopqrstuvwxyz0123456789-')


def address(value):
    if not isinstance(value, str) or len(value) > 254 or value.count('@') != 1:
        raise ValueError('invalid_channel_address')
    local, domain = value.split('@')
    labels = domain.lower().split('.')
    if (not 1 <= len(local) <= 64 or local.startswith('.') or local.endswith('.') or '..' in local
            or any(char not in _LOCAL for char in local) or len(labels) < 2
            or not 2 <= len(labels[-1]) <= 63 or not labels[-1].isascii() or not labels[-1].isalpha()
            or any(not 1 <= len(label) <= 63 or label.startswith('-') or label.endswith('-')
                   or any(char not in _HOST for char in label) for label in labels)):
        raise ValueError('invalid_channel_address')
    return value.lower()


def validate(value):
    if not isinstance(value, dict) or set(value) - set(CHANNELS):
        raise ValueError('invalid_channel_settings')
    result = copy.deepcopy(DEFAULTS)
    for channel, raw in value.items():
        if not isinstance(raw, dict) or set(raw) - (set(DEFAULTS[channel]) | {'language'}):
            raise ValueError('invalid_channel_settings')
        row = result[channel]
        row.update(raw)
        if (type(row['enabled']) is not bool or type(row['privacy_confirmed']) is not bool
                or not isinstance(row['mode'], str) or row['mode'] not in {'review', 'automatic'}
                or type(row['daily_limit']) is not int or not 1 <= row['daily_limit'] <= 1000
                or type(row['retention_days']) is not int or not 1 <= row['retention_days'] <= 90
                or not isinstance(row.get('language'), str) or row['language'] not in LANGUAGES):
            raise ValueError('invalid_channel_settings')
        row['language'] = row.get('language', 'en-GB')
        if row['enabled'] and not row['privacy_confirmed']:
            raise ValueError('channel_privacy_confirmation_required')
    return result


def validate_grants(value):
    if (not isinstance(value, dict) or set(value) != set(CHANNELS)
            or any(type(value[channel]) is not bool for channel in CHANNELS)):
        raise ValueError('invalid_channel_grants')
    return value.copy()


def _read(storage, tenant, filename, default):
    try:
        return storage.read_json(tenant, filename)
    except FileNotFoundError:
        return copy.deepcopy(default)


def settings(storage, tenant):
    return validate(_read(storage, tenant, FILENAME, {}))


def grants(storage, tenant):
    return validate_grants(_read(storage, tenant, GRANTS_FILE, {channel: False for channel in CHANNELS}))


def bindings(channel):
    name = {'email': 'V7_EMAIL_ROUTES_JSON', 'phone': 'V7_PHONE_ROUTES_JSON'}[channel]
    try:
        value = json.loads(os.getenv(name, '{}'))
        from retrieval.storage import Storage
        if not isinstance(value, dict) or len(value) > 1000:
            raise ValueError
        result = {}
        for recipient, tenant in value.items():
            normalized = address(recipient) if channel == 'email' else recipient
            if channel == 'phone' and (not isinstance(recipient, str) or not PHONE.fullmatch(recipient)):
                raise ValueError
            key = Storage.validate_tenant_key(tenant)
            if normalized in result:
                raise ValueError
            result[normalized] = key
        return result
    except (ValueError, TypeError, RecursionError):
        return {}  # Malformed global routing cannot select a default tenant.


def active(storage, tenant, channel):
    from service.tenant_access import activation
    return (channel in CHANNELS and grants(storage, tenant)[channel]
            and settings(storage, tenant)[channel]['enabled'] and activation(tenant)['active'])


def configured_tenants():
    """Worker authority comes from operator-owned routes, never an admin cookie."""
    return sorted({tenant for channel in CHANNELS for tenant in bindings(channel).values()})


def inbox_bindings():
    """An inbox ID must be explicitly bound to an already routed address."""
    try:
        value = json.loads(os.getenv('V7_EMAIL_INBOX_ROUTES_JSON', '{}'))
        if not isinstance(value, dict) or len(value) > 1000:
            return {}
        routes, result = bindings('email'), {}
        for identifier, recipient in value.items():
            recipient = address(recipient)
            if not UUID.fullmatch(identifier) or recipient not in routes:
                return {}
            result[identifier] = recipient
        return result
    except (ValueError, TypeError, RecursionError):
        return {}


def resend_key():
    # Preserve existing account-email settings; these variables are never edited
    # by a business owner or returned in channel setup responses.
    value = os.getenv('V7_CHANNEL_RESEND_API_KEY', '')
    if not value and os.getenv('SMTP_HOST', '').lower() == 'smtp.resend.com':
        value = os.getenv('SMTP_PASSWORD', '')
    return value if value.startswith('re_') else ''


def readiness(container, tenant):
    current, allowed = settings(container.storage, tenant), grants(container.storage, tenant)
    state = {}
    for channel in CHANNELS:
        recipients = [recipient for recipient, key in bindings(channel).items() if key == tenant]
        ready = bool(recipients and (resend_key() and os.getenv('V7_EMAIL_WEBHOOK_SECRET') if channel == 'email'
                                   else os.getenv('V7_PHONE_AUTH_TOKEN') and os.getenv('V7_PHONE_ACCOUNT_SID')))
        state[channel] = {'granted': allowed[channel], 'configured': ready, 'recipients': recipients,
                          'enabled': current[channel]['enabled'], 'mode': current[channel]['mode']}
    return {'settings': current, 'grants': allowed, 'channels': state,
            'worker_enabled': os.getenv('V7_CHANNEL_WORKER', 'false') == 'true'}
