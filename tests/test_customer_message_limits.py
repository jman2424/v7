"""Businesses cap how many messages one customer can send per day by website chat and WhatsApp."""
from dataclasses import replace

import pytest
from twilio.request_validator import RequestValidator

from service import customer_message_limits as limits, tenant_access
from tests.conftest import set_test_identity
from tests.test_subscriptions import identity

DAY = 86400


@pytest.fixture(autouse=True)
def active(monkeypatch):
    monkeypatch.setattr(tenant_access, 'activation', lambda tenant: {'active': True, 'status': 'active'})


def _set(client, channel, limit):
    return client.put('/admin/api/message-limits?tenant=EXAMPLE', json={'channel': channel, 'limit': limit})


def test_every_business_starts_at_40_a_day_and_can_choose_a_number_or_unlimited(client, app):
    identity(client, 'business_owner')
    state = client.get('/admin/api/message-limits?tenant=EXAMPLE').json
    assert state == {'limits': {'web': 40, 'whatsapp': 40}, 'default': 40, 'minimum': 5, 'maximum': 200}
    assert _set(client, 'web', 25).json['limits'] == {'web': 25, 'whatsapp': 40}
    assert _set(client, 'whatsapp', None).json['limits'] == {'web': 25, 'whatsapp': None}
    with app.app_context():
        assert limits.limits('OTHER') == {'web': 40, 'whatsapp': 40}  # Another business is untouched.


@pytest.mark.parametrize('body', [{'channel': 'web', 'limit': 4}, {'channel': 'web', 'limit': 201},
                                  {'channel': 'web', 'limit': 40.0}, {'channel': 'web', 'limit': True},
                                  {'channel': 'web', 'limit': '40'}, {'channel': 'email', 'limit': 40},
                                  {'channel': 'web'}, {'channel': 'web', 'limit': 40, 'tenant': 'OTHER'}])
def test_only_whole_numbers_in_range_for_known_channels_are_accepted(client, body):
    identity(client, 'business_owner')
    response = client.put('/admin/api/message-limits?tenant=EXAMPLE', json=body)
    assert response.status_code == 400 and response.json == {'error': 'invalid_message_limit'}


def test_only_people_who_manage_settings_can_change_limits_and_only_for_their_business(client, app):
    with client.session_transaction() as state:
        set_test_identity(client, state, {'id': 'limits-staff', 'roles': ['business_staff'], 'tenant': 'EXAMPLE',
                                          'permissions': ['business_settings.read']})
    assert client.get('/admin/api/message-limits?tenant=EXAMPLE').status_code == 200
    assert _set(client, 'web', 10).status_code == 403
    identity(client, 'business_owner', tenant='OTHER')
    assert _set(client, 'web', 10).status_code in {403, 404}
    with app.app_context():
        assert limits.limits('EXAMPLE')['web'] == 40


def test_website_visitor_is_stopped_at_the_limit_even_after_restarting_the_chat(client, app):
    identity(client, 'business_owner')
    _set(client, 'web', 5)
    visitor = app.test_client()
    token = None
    for _ in range(5):
        reply = visitor.post('/chat_api', json={'tenant': 'EXAMPLE', 'message': 'Hello', 'conversation_token': token})
        assert reply.status_code == 200, reply.json
        token = reply.json['conversation_token']
    refused = visitor.post('/chat_api', json={'tenant': 'EXAMPLE', 'message': 'Hello', 'conversation_token': token})
    assert refused.status_code == 429 and refused.json['error'] == 'message_limit_reached'
    assert refused.json['reply'].startswith("You've reached today's message limit")
    # A new chat from the same connection is a new visitor, up to five visitors' worth.
    assert visitor.post('/chat_api', json={'tenant': 'EXAMPLE', 'message': 'Hello'}).status_code == 200


def test_one_connection_cannot_get_round_the_limit_with_endless_new_chats(app):
    with app.test_request_context():
        limits.save('EXAMPLE', 'web', 5, 'owner')
        connection = limits.subject('ip', '192.0.2.7')
        allowed = sum(limits.allow('EXAMPLE', 'web', [(limits.subject('session', str(n)), 1), (connection, 5)])
                      for n in range(40))
        assert allowed == 25
        # Another connection, and another business, are not affected.
        assert limits.allow('EXAMPLE', 'web', [(limits.subject('session', 'x'), 1), (limits.subject('ip', '192.0.2.8'), 5)])
        assert limits.allow('OTHER', 'web', [(limits.subject('session', '0'), 1), (connection, 5)])


def test_counts_reset_each_day_and_unlimited_never_refuses(app):
    with app.test_request_context():
        limits.save('EXAMPLE', 'whatsapp', 5, 'owner')
        customer = [(limits.subject('whatsapp', '447123456789'), 1)]
        today = 1_800_000_000
        assert [limits.allow('EXAMPLE', 'whatsapp', customer, now=today) for _ in range(6)] == [True] * 5 + [False]
        assert limits.allow('EXAMPLE', 'whatsapp', customer, now=today + DAY)
        limits.save('EXAMPLE', 'whatsapp', None, 'owner')
        assert all(limits.allow('EXAMPLE', 'whatsapp', customer, now=today) for _ in range(50))


def test_raw_phone_numbers_and_addresses_are_never_stored(app):
    with app.test_request_context():
        assert '447123456789' not in limits.subject('whatsapp', '447123456789')
        assert '192.0.2.7' not in limits.subject('ip', '192.0.2.7')


def test_a_broken_counter_does_not_cut_every_customer_off(app, monkeypatch):
    def broken(tenant):
        raise RuntimeError('database down')
    monkeypatch.setattr(limits, 'limits', broken)
    with app.test_request_context():
        assert limits.allow('EXAMPLE', 'web', [(limits.subject('session', 'a'), 1)])


def test_whatsapp_customer_over_the_limit_is_told_once_and_no_ai_runs(client, app, monkeypatch):
    from routes import whatsapp_routes
    app.container.settings = replace(app.container.settings, WHATSAPP_PROVIDER_MODE='auto')
    monkeypatch.setenv('TWILIO_AUTH_TOKEN', 'configured-token')
    monkeypatch.setenv('TWILIO_WHATSAPP_NUMBER', 'whatsapp:+447700900999')
    monkeypatch.setattr('service.subscriptions.whatsapp_enabled', lambda tenant: True)
    monkeypatch.setattr('service.plan_usage.use_resource', lambda *args: True)
    answered = []
    monkeypatch.setattr(whatsapp_routes, '_reply', lambda c, event, source: answered.append(1) or 'Agent reply')
    with app.test_request_context():
        limits.save('EXAMPLE', 'whatsapp', 5, 'owner')

    def send(sid):
        form = {'Body': 'Are you open?', 'From': 'whatsapp:+447700900123', 'To': 'whatsapp:+447700900999',
                'MessageSid': sid}
        url = app.container.settings.BASE_URL + '/whatsapp/webhook'
        signature = RequestValidator('configured-token').compute_signature(url, form)
        return client.post('/whatsapp/webhook', data=form, headers={'X-Twilio-Signature': signature})

    for number in range(5):
        assert 'Agent reply' in send(f'SMlimit-{number}').text
    told = send('SMlimit-5')
    assert told.status_code == 200 and "reached today's message limit" in told.text
    quiet = send('SMlimit-6')
    assert quiet.status_code == 200 and 'limit' not in quiet.text and 'Agent reply' not in quiet.text
    assert len(answered) == 5
