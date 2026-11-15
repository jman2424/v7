"""Business pauses and the platform kill switch stop AI on the server, per business and per channel."""
from xml.etree import ElementTree

import pytest

from service import service_controls, tenant_access
from service.mcp_tools import BusinessError, execute
from tests.test_business_channel_providers import configured, phone  # noqa: F401
from tests.test_subscriptions import identity

NOTICE = 'This assistant is currently unavailable.'


@pytest.fixture(autouse=True)
def active(monkeypatch):
    monkeypatch.setattr(tenant_access, 'activation', lambda tenant: {'active': True, 'status': 'active'})
    service_controls.invalidate()
    yield
    service_controls.invalidate()


def _pause(client, scope, paused=True):
    return client.put('/admin/api/service-controls?tenant=EXAMPLE', json={'scope': scope, 'paused': paused})


def _platform(client, tenant=None, channel=None, paused=True, reason='Security incident under review'):
    return client.put('/admin/api/platform/service-controls',
                      json={'tenant': tenant, 'channel': channel, 'paused': paused, 'reason': reason})


def _handle(app, channel='web'):
    with app.app_context():
        runtime = app.container.for_tenant('EXAMPLE')
        return runtime.handler.handle('What do you sell?', tenant='EXAMPLE', session_id='pause-test', channel=channel)


def test_owner_pause_all_stops_every_channel_and_resume_restores_it(client, app):
    identity(client, 'business_owner')
    assert 'chat_ui' in client.get('/widget.js?tenant=EXAMPLE').text
    response = _pause(client, 'all')
    assert response.status_code == 200, response.json
    assert response.json['all_paused'] is True
    assert 'chat_ui' not in client.get('/widget.js?tenant=EXAMPLE').text
    reply = client.post('/chat_api?tenant=EXAMPLE', json={'message': 'Hello'})
    assert reply.status_code == 403 and reply.json['message'].startswith(NOTICE)
    for channel in service_controls.CHANNELS:
        assert service_controls.blocked('EXAMPLE', channel) == 'paused_by_business'
    result = _handle(app, 'whatsapp')
    assert result['intent'] == 'service_paused' and result['reply'].startswith(NOTICE)
    assert service_controls.blocked('OTHER', 'web') is None  # Another business is untouched.
    assert _pause(client, 'all', False).json['all_paused'] is False
    assert 'chat_ui' in client.get('/widget.js?tenant=EXAMPLE').text


def test_pausing_one_channel_leaves_the_others_running(client):
    identity(client, 'business_owner')
    assert _pause(client, 'web').json['channels']['web']['paused'] is True
    assert 'chat_ui' not in client.get('/widget.js?tenant=EXAMPLE').text
    assert service_controls.blocked('EXAMPLE', 'web') == 'paused_by_business'
    assert service_controls.blocked('EXAMPLE', 'whatsapp') is None


def test_only_authorised_people_can_pause_and_only_their_own_business(client):
    identity(client, 'business_staff')
    assert _pause(client, 'all').status_code == 403
    identity(client, 'business_owner', tenant='OTHER')
    assert _pause(client, 'all').status_code in {403, 404}
    assert service_controls.blocked('EXAMPLE') is None
    identity(client, 'business_owner')
    for body in [{'scope': 'everything', 'paused': True}, {'scope': 'all', 'paused': 'yes'}, {'scope': 'all'}]:
        assert client.put('/admin/api/service-controls?tenant=EXAMPLE', json=body).json == {'error': 'invalid_service_control'}
    assert client.get('/admin/api/platform/service-controls').status_code == 403
    assert _platform(client).status_code == 403


def test_platform_suspension_cannot_be_lifted_by_the_business(client, app):
    identity(client)
    assert _platform(client, reason='x').json == {'error': 'service_control_reason_required'}
    response = _platform(client, tenant='EXAMPLE')
    assert response.status_code == 200, response.json
    assert [row['scope'] for row in response.json['controls']] == ['platform:tenant:EXAMPLE']
    assert service_controls.blocked('EXAMPLE', 'web') == 'suspended_by_platform'
    identity(client, 'business_owner')
    state = client.get('/admin/api/service-controls?tenant=EXAMPLE').json
    assert state['suspended_by_platform'] is True and state['can_pause'] is True
    _pause(client, 'all', False)
    assert service_controls.blocked('EXAMPLE', 'web') == 'suspended_by_platform'
    assert _handle(app)['intent'] == 'service_paused'
    identity(client)
    assert _platform(client, tenant='EXAMPLE', paused=False, reason='').status_code == 200
    assert service_controls.blocked('EXAMPLE', 'web') is None
    assert _platform(client, tenant='NO_SUCH_BUSINESS').status_code == 404


def test_platform_can_stop_one_channel_everywhere_or_everything(client):
    identity(client)
    assert _platform(client, channel='phone').status_code == 200
    assert service_controls.blocked('EXAMPLE', 'phone') == 'suspended_by_platform'
    assert service_controls.blocked('OTHER', 'phone') == 'suspended_by_platform'
    assert service_controls.blocked('EXAMPLE', 'web') is None
    assert _platform(client).status_code == 200
    assert service_controls.blocked('OTHER', 'web') == 'suspended_by_platform'


def test_owner_tools_ignore_a_business_pause_but_not_the_platform_switch(client, app):
    identity(client, 'business_owner')
    _pause(client, 'all')
    assert service_controls.platform_blocked('EXAMPLE') is None
    identity(client)
    _platform(client, tenant='EXAMPLE')
    owner = {'id': 'owner', 'roles': ['business_owner'], 'tenant': 'EXAMPLE'}
    with app.test_request_context(), pytest.raises(BusinessError) as error:
        execute(app.container, owner, {'business:read'}, 'get_roles', {})
    assert error.value.code == 'service_suspended'


def test_unreadable_controls_stop_the_ai_rather_than_fail_open(monkeypatch):
    def broken():
        raise RuntimeError('database down')

    monkeypatch.setattr(service_controls, '_rows', broken)
    assert service_controls.blocked('EXAMPLE', 'web') == 'service_controls_unavailable'


def test_a_write_takes_effect_at_once_on_this_worker(client):
    identity(client, 'business_owner')
    assert service_controls.blocked('EXAMPLE', 'email') is None  # Fills the cache.
    _pause(client, 'email')
    assert service_controls.blocked('EXAMPLE', 'email') == 'paused_by_business'


def test_caller_to_a_paused_phone_line_hears_how_to_reach_the_business(client, app, configured):  # noqa: F811
    service_controls.set_control(service_controls.key('business', 'EXAMPLE', 'phone'), True, 'owner')
    response = phone(client, app)
    root = ElementTree.fromstring(response.data)
    assert [node.tag for node in root] == ['Say', 'Hangup']
    assert root[0].text.startswith(NOTICE)
