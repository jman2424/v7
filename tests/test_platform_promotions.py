"""Operator-owned offer controls; synthetic Stripe and isolated business storage."""
from dataclasses import replace

import pytest

from service import platform_promotions as policy, platform_offer_knowledge, referrals, subscriptions
from tests.test_subscriptions import identity, stripe as _stripe
from tests.test_billing_promotions import provider

stripe = _stripe


@pytest.fixture
def marketing(app, monkeypatch):
    app.container.settings = replace(app.container.settings, PLATFORM_MARKETING_TENANT='EXAMPLE')
    monkeypatch.setattr(subscriptions, 'internal_business', lambda tenant: tenant == 'EXAMPLE')
    return app.container.storage


def update(client, *, tenant='EXAMPLE', **changes):
    identity(client, tenant=tenant)
    path = '/admin/api/platform-promotions?tenant='+tenant
    current = client.get(path)
    assert current.status_code == 200
    data = current.json
    return client.put(path, json={
        'revision': data['revision'], 'settings': {**data['settings'], **changes}})


def test_offers_list_reports_real_billing_promotions_without_changing_catalogue_contract(client, marketing):
    identity(client)
    response = client.get('/admin/api/platform-promotions?tenant=EXAMPLE')
    assert response.json['available'] is True
    assert response.json['settings'] == policy.DEFAULTS
    assert response.headers['Cache-Control'] == 'no-store'
    assert isinstance(client.get('/admin/api/offers?tenant=EXAMPLE').json, list)
    assert response.json['referral']['enabled']


def test_only_operator_can_manage_internal_business_promotions(client, marketing):
    assert client.get('/admin/api/platform-promotions?tenant=EXAMPLE').status_code == 401
    identity(client, 'business_owner')
    assert client.get('/admin/api/platform-promotions?tenant=EXAMPLE').status_code == 403
    assert client.put('/admin/api/platform-promotions?tenant=EXAMPLE', json={}).status_code == 403
    assert client.post('/billing/referrals/program', json={'enabled': False}).status_code == 403
    assert client.get('/admin/api/platform-promotions?tenant=OTHER').status_code == 403
    assert client.put('/files/raw/platform_promotions.json?tenant=EXAMPLE', json=policy.DEFAULTS).status_code == 404


def test_unrelated_workspace_cannot_edit_global_offer_switches(client, marketing, monkeypatch):
    monkeypatch.setattr(subscriptions, 'internal_business', lambda _: False)
    identity(client)
    assert client.get('/admin/api/platform-promotions?tenant=EXAMPLE').json == {'available': False}
    assert client.put('/admin/api/platform-promotions?tenant=EXAMPLE', json={}).status_code == 404


@pytest.mark.parametrize('value', [0, 1, 'false', None, {}, []])
def test_settings_require_real_booleans_and_safe_errors(client, marketing, value):
    identity(client)
    before = client.get('/admin/api/platform-promotions?tenant=EXAMPLE').json
    response = client.put('/admin/api/platform-promotions?tenant=EXAMPLE', json={
        'revision': before['revision'], 'settings': {**policy.DEFAULTS, 'setup_enabled': value}})
    assert response.status_code == 400 and response.json == {'error': 'invalid_platform_promotions'}
    assert client.get('/admin/api/platform-promotions?tenant=EXAMPLE').json['settings'] == policy.DEFAULTS


def test_stale_revision_cannot_overwrite_another_offer_change(client, marketing):
    identity(client)
    before = client.get('/admin/api/platform-promotions?tenant=EXAMPLE').json
    assert update(client, setup_enabled=False).status_code == 200
    response = client.put('/admin/api/platform-promotions?tenant=EXAMPLE', json={
        'revision': before['revision'], 'settings': {**policy.DEFAULTS, 'highstreet_enabled': False}})
    assert response.status_code == 409
    assert client.get('/admin/api/platform-promotions?tenant=EXAMPLE').json['settings'] == {
        'setup_enabled': False, 'highstreet_enabled': True}


@pytest.mark.parametrize('code,key', [('SETUP', 'setup_enabled'), ('MHIGHSTREET', 'highstreet_enabled')])
def test_pause_blocks_new_claims_and_reenable_restores_them(client, marketing, stripe, code, key):
    assert update(client, **{key: False}).status_code == 200
    identity(client, 'business_owner')
    response = client.post('/billing/discount', json={'code': code})
    assert response.status_code == 400 and response.json['error'] == 'promotion_unavailable'
    stripe.assert_not_called()
    assert update(client, **{key: True}).status_code == 200
    identity(client, 'business_owner')
    assert client.post('/billing/discount', json={'code': code}).status_code == 200


def test_pausing_preserves_accepted_coupon_terms_and_checkout(client, app, marketing, stripe, monkeypatch):
    from service.tenant_service import TenantService
    TenantService(marketing).create_tenant('MARKETING', 'Synthetic platform')
    app.container.settings = replace(app.container.settings, PLATFORM_MARKETING_TENANT='MARKETING')
    monkeypatch.setattr(subscriptions, 'internal_business', lambda tenant: tenant == 'MARKETING')
    identity(client, 'business_owner')
    assert client.post('/billing/discount', json={'code': 'SETUP'}).status_code == 200
    assert update(client, tenant='MARKETING', setup_enabled=False).status_code == 200
    identity(client, 'business_owner')
    # Accepted claims remain idempotent and keep their original terms.
    assert client.post('/billing/discount', json={'code': 'SETUP'}).status_code == 200
    assert client.get('/billing/subscription').json['setup_discount_percent'] == 100
    stripe.side_effect = provider
    response = client.post('/billing/checkout', json={'kind': 'implementation', 'plan_id': 'starter'})
    assert response.status_code == 200, response.json
    coupon = next(call.args[2] for call in stripe.call_args_list if call.args[1] == '/v1/coupons')
    assert coupon['percent_off'] == 100 and coupon['duration'] == 'once'


def test_pause_updates_homepage_current_ai_policy_and_stale_copy(client, app, marketing):
    assert 'id="setup-offer-title"' in client.get('/').text
    assert update(client, setup_enabled=False).status_code == 200
    assert 'id="setup-offer-title"' not in client.get('/').text
    with app.app_context():
        current = platform_offer_knowledge.public_setup_policy('EXAMPLE')['answer']
        assert 'SETUP is paused for new claims.' in current
        assert 'Use SETUP for free' not in current
        text = platform_offer_knowledge.current_promotion_reply('EXAMPLE', 'Starter is £99 monthly. Use SETUP for free setup.')
        assert '£99' in text and 'paused for new claims' in text and 'Use SETUP' not in text
        assert platform_offer_knowledge.current_promotion_reply('OTHER', 'Use SETUP for free setup.') == 'Use SETUP for free setup.'
        assert platform_offer_knowledge.current_promotion_reply('EXAMPLE', text) == text
        knowledge = {'faq:old': {'answer': 'Use SETUP for free setup.'}, 'product:a': {'price': 99},
                     'policy:platform_setup': {'answer': current}}
        filtered = platform_offer_knowledge.current_promotion_knowledge('EXAMPLE', knowledge)
        assert 'faq:old' not in filtered and filtered['product:a']['price'] == 99
        assert filtered['policy:platform_setup']['answer'] == current


def test_malformed_policy_fails_closed_without_exposing_details(client, app, marketing):
    marketing.write_json('EXAMPLE', policy.FILENAME, {'setup_enabled': 'secret-token /private/customer.db'})
    identity(client)
    response = client.get('/admin/api/platform-promotions?tenant=EXAMPLE')
    assert response.status_code == 503 and response.json == {'error': 'platform_promotions_unavailable'}
    with app.app_context():
        assert policy.public_flags() == dict.fromkeys(policy.DEFAULTS, False)


def test_actual_website_chat_does_not_advertise_a_paused_code_from_a_saved_faq(client, app, marketing):
    marketing.write_json('EXAMPLE', 'faq.json', [{
        'q': 'What is the SETUP offer?', 'a': 'Use SETUP for free setup.', 'tags': ['setup', 'offer']}])
    assert update(client, setup_enabled=False).status_code == 200
    app.container.for_tenant('EXAMPLE').handler.h_v7.rewriter = None
    response = client.post('/chat_api', json={'tenant': 'EXAMPLE', 'message': 'What is the SETUP offer?'})
    assert response.status_code == 200
    assert 'SETUP is paused for new claims.' in response.json['reply']
    assert 'Use SETUP' not in response.json['reply']


def test_platform_offer_fallback_uses_live_codes_without_hijacking_setup_help(client, app, marketing, monkeypatch):
    with app.app_context():
        assert platform_offer_knowledge.automatic_setup_answer('How do I set up my widget?', 'EXAMPLE') is None
        assert platform_offer_knowledge.automatic_setup_answer('What offers do you have?', 'OTHER', all_offers=True) is None
        assert 'free unpaid one-time setup' in platform_offer_knowledge.automatic_setup_answer('Tell me about the Setup offer', 'EXAMPLE')
    assert update(client, setup_enabled=False, highstreet_enabled=False).status_code == 200
    monkeypatch.setattr(referrals, 'public_offer', lambda tenant: {'enabled': False})
    with app.app_context():
        assert 'currently paused' in platform_offer_knowledge.automatic_setup_answer('Any offers?', 'EXAMPLE', all_offers=True)
        assert 'SETUP is paused' in platform_offer_knowledge.automatic_setup_answer('is the setup code active?', 'EXAMPLE')


@pytest.mark.parametrize('extra', [{'percent': 999}, {'tenant': 'OTHER'}, {'coupon': 'forged'}])
def test_controller_rejects_attempts_to_change_fixed_terms_or_target_tenant(client, marketing, extra):
    identity(client)
    data = client.get('/admin/api/platform-promotions?tenant=EXAMPLE').json
    response = client.put('/admin/api/platform-promotions?tenant=EXAMPLE', json={
        'revision': data['revision'], 'settings': {**data['settings'], **extra}})
    assert response.status_code == 400


def test_offer_updates_remain_csrf_protected(client, marketing):
    identity(client)
    data = client.get('/admin/api/platform-promotions?tenant=EXAMPLE').json
    response = client.put('/admin/api/platform-promotions?tenant=EXAMPLE',
        json={'revision': data['revision'], 'settings': {**data['settings'], 'setup_enabled': False}},
        headers={'X-CSRF-Token': 'incorrect-synthetic-token'})
    assert response.status_code == 403


def test_policy_is_read_once_per_request_and_fresh_on_the_next_request(app, marketing, monkeypatch):
    reads = []
    original = policy.document
    def document(storage, tenant):
        reads.append(tenant)
        return original(storage, tenant)
    monkeypatch.setattr(policy, 'document', document)
    with app.test_request_context('/first'):
        assert policy.public_flags() == policy.DEFAULTS
        assert policy.public_flags() == policy.DEFAULTS
    assert reads == ['EXAMPLE']
    marketing.write_json('EXAMPLE', policy.FILENAME, {'setup_enabled': False, 'highstreet_enabled': True})
    with app.test_request_context('/second'):
        assert policy.public_flags()['setup_enabled'] is False
    assert reads == ['EXAMPLE', 'EXAMPLE']
