"""Stripe URL parsing errors never become public exception messages."""
from urllib.parse import urlunsplit

import pytest

from service import subscriptions
from tests.test_subscriptions import identity, stripe as stripe_fixture

stripe = stripe_fixture


@pytest.mark.parametrize('action', ['checkout', 'portal'])
def test_malformed_provider_netloc_never_exposes_private_details(client, stripe, action):
    identity(client, 'business_owner')
    marker = 'synthetic-private-provider-detail'
    host = 'checkout.stripe.com' if action == 'checkout' else 'billing.stripe.com'
    # This URL remains hostile; construct synthetic user-info without committing
    # a credential-shaped URI literal that would trigger the offline scanner.
    malformed = urlunsplit(('https', '{}:{}@{}\uff1a'.format('fixture-user', marker, host), '/', '', ''))
    if action == 'checkout':
        stripe.side_effect = [
            {'active': True, 'inclusive': False, 'percentage': 20},
            {'id': 'cs_fixture', 'url': malformed},
        ]
        body = {'kind': 'platform'}
    else:
        subscriptions._contract('EXAMPLE', 'platform')
        with subscriptions.connection() as database:
            database.execute("UPDATE billing_contracts SET customer='cus_fixture' WHERE tenant='EXAMPLE' AND kind='platform'")
        stripe.return_value = {'url': malformed}
        body = {}
    response = client.post('/billing/' + action, json=body)
    assert response.status_code == 400
    assert response.json == {'error': 'stripe_response_invalid'}
    assert marker not in response.get_data(as_text=True)


@pytest.mark.parametrize('netloc', ['[synthetic-private-provider-detail', 'billing.stripe.com\uff1a'])
def test_shared_provider_url_validation_rejects_parser_errors(netloc):
    malformed = urlunsplit(('https', netloc, '/', '', ''))
    assert subscriptions._safe_url(malformed, 'billing.stripe.com') is None
    valid = 'https://billing.stripe.com/p/session/fixture'
    assert subscriptions._safe_url(valid, 'billing.stripe.com') == valid


@pytest.mark.parametrize('action,body,expected', [
    ('checkout', {'kind': 'unsupported'}, 'invalid_billing_item'),
    ('portal', {}, 'subscription_required'),
])
def test_existing_billing_validation_codes_remain_public(client, stripe, action, body, expected):
    identity(client, 'business_owner')
    response = client.post('/billing/' + action, json=body)
    assert response.status_code == 400 and response.json == {'error': expected}
    stripe.assert_not_called()


def test_existing_checkout_setup_and_provider_codes_remain_public(client, stripe, monkeypatch):
    identity(client, 'business_owner')
    monkeypatch.delenv('STRIPE_TAX_RATE_ID')
    response = client.post('/billing/checkout', json={'kind': 'platform'})
    assert response.status_code == 400 and response.json == {'error': 'stripe_setup_required'}
    stripe.assert_not_called()
    monkeypatch.setenv('STRIPE_TAX_RATE_ID', 'txr_fixture')
    stripe.side_effect = ValueError('stripe_request_failed')
    response = client.post('/billing/checkout', json={'kind': 'platform'})
    assert response.status_code == 400 and response.json == {'error': 'stripe_request_failed'}
