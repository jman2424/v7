"""Each plan includes a fixed set of customer channels, enforced on the server."""
import pytest

from service import agent_modules as modules, plan_catalog
from tests.test_agent_modules import policy
from tests.test_business_channel_providers import configured as _configured, owner

configured = _configured


@pytest.fixture(autouse=True)
def policy_environment(monkeypatch):
    monkeypatch.setenv('V7_AGENT_MODULE_POLICY_JSON', '{}')


def test_catalogue_lists_the_channels_of_each_plan():
    assert plan_catalog.get_plan('starter')['channels'] == ('web',)
    assert plan_catalog.get_plan('business')['channels'] == ('web', 'email')
    assert plan_catalog.get_plan('scale')['channels'] == ('web', 'email', 'whatsapp', 'phone')


def test_a_business_without_a_tiered_plan_keeps_its_existing_channels():
    assert plan_catalog.includes_channel(None, 'phone')
    assert not plan_catalog.includes_channel({'id': 'starter'}, 'email')
    assert not plan_catalog.includes_channel({'id': 'unknown'}, 'email')


@pytest.mark.parametrize('plan,email,phone', [('starter', False, False), ('business', True, False), ('scale', True, True)])
def test_email_and_phone_follow_the_plan_even_when_granted_and_enabled(configured, monkeypatch, plan, email, phone):
    storage = configured.storage
    policy(storage)
    monkeypatch.setattr('service.subscriptions.configured_plan', lambda _: plan_catalog.get_plan(plan))
    decisions = modules.decisions(storage, 'EXAMPLE', ('email', 'phone', 'quote'))
    assert decisions['email']['allowed'] is email and decisions['phone']['allowed'] is phone
    assert decisions['quote']['allowed']
    if not phone:
        assert decisions['phone']['reason'] == 'plan_not_allowed'


def test_deployment_policy_can_restrict_but_never_widen_a_plan(configured, monkeypatch):
    storage = configured.storage
    policy(storage)
    monkeypatch.setenv('V7_AGENT_MODULE_POLICY_JSON', '{"plans":{"phone":["starter","business","scale"]}}')
    monkeypatch.setattr('service.subscriptions.configured_plan', lambda _: plan_catalog.get_plan('starter'))
    assert not modules.allowed(storage, 'EXAMPLE', 'phone')


def test_owner_cannot_enable_a_channel_outside_the_plan(client, configured, monkeypatch):
    from service import business_channels as channels
    owner(client)
    monkeypatch.setattr('service.subscriptions.configured_plan', lambda _: plan_catalog.get_plan('starter'))
    ready = client.get('/admin/api/business-channels?tenant=EXAMPLE').json
    assert ready['channels']['email']['in_plan'] is False and ready['channels']['phone']['in_plan'] is False
    prefs = channels.settings(configured.storage, 'EXAMPLE')
    prefs['email'].update(enabled=True, privacy_confirmed=True)
    response = client.put('/admin/api/business-channels?tenant=EXAMPLE', json={'settings': prefs})
    assert response.status_code == 403 and response.json['error'] == 'channel_not_in_plan'
    assert not channels.active(configured.storage, 'EXAMPLE', 'email')


def test_whatsapp_status_explains_a_plan_without_whatsapp(client, configured, monkeypatch):
    from service import whatsapp_configuration as whatsapp
    billing = {'kind': 'tiered', 'plan': {'id': 'business'}, 'allowance': None, 'ai_processing_paused': False}
    monkeypatch.setattr(whatsapp, 'setup_billing', lambda *args, **kwargs: billing)
    with client.application.app_context():
        codes = [row['code'] for row in whatsapp.setup_status(configured, 'EXAMPLE')['blockers']]
    assert 'whatsapp_not_in_plan' in codes and 'whatsapp_subscription_inactive' not in codes
