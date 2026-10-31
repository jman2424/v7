"""Client-owned setup requests; mailbox authority stays with verified routing."""
from service import business_channels as channels
from service.business_management import revision
import sqlite3

FILENAME = 'business_email_setup.json'
PROVIDERS = ('google_workspace', 'microsoft_365', 'hosted_email', 'resend_inbox')
DEFAULTS = {'address': '', 'provider': 'hosted_email', 'purpose': 'support'}


def validate(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULTS):
        raise ValueError('invalid_email_setup')
    if (not isinstance(value['provider'], str) or value['provider'] not in PROVIDERS
            or value['purpose'] != 'support'):
        raise ValueError('invalid_email_setup')
    return {**value, 'address': channels.address(value['address'])}


def status(container, tenant):
    try:
        raw = container.storage.read_json(tenant, FILENAME)
    except FileNotFoundError:
        raw = None
    settings = validate(raw) if raw is not None else DEFAULTS.copy()
    ready = channels.readiness(container, tenant)
    configured = bool(settings['address'] and settings['address'] in ready['channels']['email']['sending_addresses'])
    from service.business_operations import cleanup_counts
    try:
        counts = cleanup_counts(tenant)
    except (RuntimeError, sqlite3.OperationalError):
        counts = None
    return {'settings': settings, 'revision': revision(raw),
            'state': 'routing_configured' if configured else 'requested' if settings['address'] else 'not_started',
            'can_enable': configured and ready['channels']['email']['configured']
                          and ready['channels']['email']['granted'] and ready['worker_enabled'] and counts is not None,
            'connection_method': 'operator_verified_forwarding',
            'forward_to': [recipient for recipient in ready['channels']['email']['recipients']
                           if recipient != settings['address'] and channels.email_senders().get(recipient) == settings['address']],
            'native_oauth_available': False,
            'storage_available': counts is not None, 'cleanup_counts': counts,
            'provider_cleanup_available': any(
                channels.bindings('email').get(recipient) == tenant
                and channels.email_senders().get(recipient) == settings['address']
                for recipient in channels.inbox_bindings().values())}
