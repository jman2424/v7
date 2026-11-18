"""Public agents cannot disclose private offers or bypass assistance capacity."""
import json
from dataclasses import replace

import pytest

from service import platform_offer_knowledge as knowledge, platform_promotions as policy
from service import subscriptions
from tests.test_platform_promotions import marketing as _marketing, update
from tests.test_subscriptions import identity, stripe as _stripe
from tests.test_billing_promotions import provider

stripe = _stripe
marketing = _marketing


@pytest.fixture
def capacity(app, marketing, monkeypatch):
    from service.tenant_service import TenantService
    TenantService(marketing).create_tenant('MARKETING', 'Synthetic platform')
    app.container.settings = replace(app.container.settings, PLATFORM_MARKETING_TENANT='MARKETING')
    monkeypatch.setattr(subscriptions, 'internal_business', lambda tenant: tenant == 'MARKETING')
    return marketing


def test_existing_policy_documents_default_to_private_highstreet_and_open_assistance(client, marketing):
    marketing.write_json('EXAMPLE', policy.FILENAME, {'setup_enabled': False, 'highstreet_enabled': True})
    identity(client)
    settings = client.get('/admin/api/platform-promotions?tenant=EXAMPLE').json['settings']
    assert settings['highstreet_enabled'] and not settings['highstreet_public']
    assert settings['assistance_enabled']


def test_private_campaign_remains_redeemable_without_appearing_in_public_agent_context(client, app, marketing, stripe):
    identity(client, 'business_owner')
    assert client.post('/billing/discount', json={'code': 'MHIGHSTREET'}).status_code == 200
    with app.app_context():
        context = knowledge.public_plan_context('EXAMPLE')
        assert '£100' in context['implementation_support']
        assert 'MHIGHSTREET' not in json.dumps(context) and 'SETUP' not in json.dumps(context)
        assert '50% off the first subscription month' not in json.dumps(context)
    stripe.assert_not_called()


def test_assistance_price_fallback_uses_current_scope_without_advertising_codes(client, app, marketing):
    app.container.for_tenant('EXAMPLE').handler.h_v7.rewriter = None
    response = client.post('/chat_api', json={'tenant': 'EXAMPLE', 'message': 'how much is assitence'})
    assert response.status_code == 200
    assert '£100' in response.json['reply'] and 'one-time' in response.json['reply']
    assert 'MHIGHSTREET' not in response.json['reply'] and 'SETUP' not in response.json['reply']


@pytest.mark.parametrize('message', ['What is MHIGHSTREET?', 'muslim high street discount', 'What is the SETUP code?'])
def test_private_and_retired_code_questions_never_confirm_a_code_or_call_the_model(client, app, marketing, monkeypatch, message):
    handler = app.container.for_tenant('EXAMPLE').handler.h_v7
    def unexpected(*args, **kwargs):
        raise AssertionError('Private code questions must not reach the model')
    monkeypatch.setattr(handler, '_grounded_answer', unexpected)
    response = client.post('/chat_api', json={'tenant': 'EXAMPLE', 'message': message})
    assert response.status_code == 200
    assert 'checked privately' in response.json['reply']
    assert 'MHIGHSTREET' not in json.dumps(response.json) and 'SETUP' not in json.dumps(response.json)


def test_private_and_retired_promotions_are_removed_from_all_sources_and_old_history(app, marketing):
    with app.app_context():
        result = knowledge.current_promotion_knowledge('EXAMPLE', {
            'business': {'description': 'Use MHIGHSTREET for free help'},
            'faq:old': {'answer': 'Use SETUP for free assistance'},
            'website:old': 'muslim high street code', 'product:ordinary': {'price': 99}})
        assert result == {'product:ordinary': {'price': 99}}
        rows = [{'role': 'assistant', 'content': 'Use MHIGHSTREET'},
                {'role': 'user', 'content': 'I sell flowers'}]
        assert knowledge.current_promotion_history('EXAMPLE', rows) == rows[1:]
        assert 'checked privately' in knowledge.current_promotion_reply('EXAMPLE', 'Use mhighstreet for free help')
        assert knowledge.current_promotion_reply('OTHER', 'Use MHIGHSTREET') == 'Use MHIGHSTREET'


def test_model_receives_no_private_offer_from_business_copy_history_or_remembered_state(app, marketing, monkeypatch):
    from types import SimpleNamespace
    from handlers.handler_v7 import MessageHandlerV7
    from service import grounded_conversation
    handler = MessageHandlerV7(SimpleNamespace(rewriter=SimpleNamespace(_client=object(), _model='test-model')))
    handler.tenant_key = 'EXAMPLE'
    handler.sales_context['description'] = 'Use MHIGHSTREET for free help'
    seen = []
    def answer(*args, **kwargs):
        seen.append(json.dumps([args[3], args[4], {key: value for key, value in kwargs.items() if key != 'agent_state'}]))
        return None
    monkeypatch.setattr(grounded_conversation, 'answer', answer)
    with app.app_context():
        handler._grounded_answer('What does it include?', {
            'conversation_history': [{'role': 'assistant', 'content': 'Use MHIGHSTREET'},
                                     {'role': 'user', 'content': 'I have MHIGHSTREET'}],
            'sales_agent': {'summary': 'SETUP was free'},
            'conversation_customer_statements': ['MHIGHSTREET is free']})
    assert seen and 'MHIGHSTREET' not in seen[0] and 'SETUP' not in seen[0]


def test_visibility_can_be_changed_without_disabling_the_campaign(client, app, marketing):
    assert update(client, highstreet_public=True).status_code == 200
    with app.app_context():
        assert 'MHIGHSTREET' in knowledge.setup_support()
    assert update(client, highstreet_public=False).status_code == 200
    with app.app_context():
        assert 'MHIGHSTREET' not in knowledge.setup_support()
        from service.billing_promotions import HIGHSTREET
        assert policy.enabled(HIGHSTREET)


def test_referral_agent_visibility_does_not_disable_redemption_programme(client, app, marketing):
    assert update(client, referrals_public=False).status_code == 200
    with app.app_context():
        assert knowledge.public_knowledge('EXAMPLE') is None
        assert 'referral' not in knowledge.automatic_setup_answer('Any offers?', 'EXAMPLE', all_offers=True).lower()
    identity(client)
    assert client.get('/admin/api/platform-promotions?tenant=EXAMPLE').json['referral']['enabled']


@pytest.mark.parametrize('code', ['', 'MHIGHSTREET'])
def test_capacity_pause_blocks_paid_and_free_assistance_before_stripe_but_not_subscription(client, app, capacity, stripe, code):
    assert update(client, tenant='MARKETING', assistance_enabled=False).status_code == 200
    identity(client, 'business_owner')
    if code:
        assert client.post('/billing/discount', json={'code': code}).status_code == 200
    response = client.post('/billing/checkout', json={'kind': 'implementation', 'plan_id': 'starter'})
    assert response.status_code == 400 and response.json['error'] == 'setup_assistance_paused'
    stripe.assert_not_called()
    assert client.get('/billing/subscription').json['setup_assistance_available'] is False
    assert 'New setup assistance is temporarily paused.' in client.get('/pricing').text
    with app.app_context():
        assert 'temporarily paused' in knowledge.setup_support()
    stripe.side_effect = provider
    response = client.post('/billing/checkout', json={'kind': 'platform', 'plan_id': 'starter'})
    assert response.status_code == 200, response.json


def test_capacity_resume_restores_assistance_and_never_rewrites_paid_entitlements(client, capacity, stripe):
    assert update(client, tenant='MARKETING', assistance_enabled=False).status_code == 200
    subscriptions._contract('EXAMPLE', 'platform')
    with subscriptions.connection('EXAMPLE') as db:
        db.execute("UPDATE billing_contracts SET implementation_paid=1 WHERE tenant='EXAMPLE' AND kind='platform'")
    identity(client, 'business_owner')
    report = client.get('/billing/subscription').json
    assert any(row['implementation_paid'] for row in report['contracts'])
    assert update(client, tenant='MARKETING', assistance_enabled=True).status_code == 200
    identity(client, 'business_owner')
    assert client.get('/billing/subscription').json['setup_assistance_available'] is True
    stripe.assert_not_called()


def test_catalogue_private_offer_survives_management_but_not_customer_chat(client, app):
    identity(client)
    private = {'id': 'invitation', 'title': 'Invitation savings', 'description': 'Thirty percent off.',
               'code': 'INVITE30', 'active': True, 'agent_visible': False}
    public = {'id': 'public', 'title': 'Public saving', 'description': 'Ten percent off.', 'active': True}
    assert client.put('/admin/api/offers?tenant=EXAMPLE', json=[private, public]).status_code == 200
    assert client.get('/admin/api/offers?tenant=EXAMPLE').json == [private, public]
    response = app.container.handler.handle('Any offers?', tenant='EXAMPLE', channel='web', session_id='private-offers')
    encoded = json.dumps(response)
    assert 'INVITE30' not in encoded and 'Invitation savings' not in encoded
    assert 'Public saving' in encoded
    with app.app_context():
        assert knowledge.current_promotion_knowledge('EXAMPLE', {'faq:stale': 'Use INVITE30', 'faq:normal': 'Open Monday'}) == {'faq:normal': 'Open Monday'}


@pytest.mark.parametrize('value', [None, 0, 1, 'false'])
def test_catalogue_visibility_requires_a_boolean(client, value):
    identity(client)
    response = client.put('/admin/api/offers?tenant=EXAMPLE', json=[{
        'id': 'offer', 'title': 'Offer', 'description': 'Details', 'active': True, 'agent_visible': value}])
    assert response.status_code == 400
