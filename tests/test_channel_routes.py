"""Platform-assigned numbers and addresses route to exactly one business."""
import pytest

from service import business_channels as channels, channel_routes
from service.whatsapp_configuration import recipient_routes
from tests.test_agent_modules import operator
from tests.test_business_channel_providers import configured as _configured, owner, phone

configured = _configured


@pytest.fixture(autouse=True)
def fresh_cache():
    channel_routes.invalidate()
    yield
    channel_routes.invalidate()


def _create(storage, tenant):
    from service.tenant_service import TenantService
    TenantService(storage).create_tenant(tenant, tenant)


def _get(client, tenant='EXAMPLE'):
    return client.get('/admin/api/channel-routes?tenant=' + tenant)


def _put(client, routes, tenant='EXAMPLE'):
    current = _get(client, tenant).json
    return client.put('/admin/api/channel-routes?tenant=' + tenant,
                      json={'revision': current['revision'], 'routes': routes})


def test_entries_are_validated():
    ok = channel_routes.validate({'phone': ['+447700900111'], 'email': [{'address': 'Help@Shop.example'}],
                                  'whatsapp_twilio': ['+447700900222'], 'whatsapp_meta': ['123456789012']})
    assert ok['email'] == [{'address': 'help@shop.example', 'sender': 'help@shop.example'}]
    for bad in ({'phone': ['07700900111']}, {'phone': ['+447700900111', '+447700900111']},
                {'email': [{'address': 'not-an-address'}]}, {'email': [{'address': 'a@b.example', 'password': 'x'}]},
                {'whatsapp_meta': ['abc']}, {'phone': ['+447700900111'] * 11}, {'extra': []}):
        with pytest.raises(ValueError):
            channel_routes.validate(bad)


def test_only_a_platform_admin_can_read_or_assign(client, configured):
    owner(client)
    assert _get(client).status_code == 403
    assert client.put('/admin/api/channel-routes?tenant=EXAMPLE',
                      json={'revision': '', 'routes': {'phone': ['+447700900111']}}).status_code == 403
    assert channels.bindings('phone').get('+447700900111') is None


def test_assigned_number_and_address_route_calls_and_email(client, app, configured):
    operator(client)
    saved = _put(client, {'phone': ['+447700900111'], 'email': [{'address': 'help@shop.example'}]})
    assert saved.status_code == 200, saved.json
    assert channels.bindings('phone')['+447700900111'] == 'EXAMPLE'
    assert channels.bindings('phone')['+447700900001'] == 'EXAMPLE'  # Operator route still applies.
    assert channels.email_senders()['help@shop.example'] == 'help@shop.example'
    assert 'EXAMPLE' in channels.configured_tenants()
    assert phone(client, app, To='+447700900111').status_code == 200


def test_a_number_cannot_be_given_to_a_second_business(client, app, configured):
    _create(app.container.storage, 'OTHER')
    operator(client)
    assert _put(client, {'phone': ['+447700900111']}).status_code == 200
    taken = _put(client, {'phone': ['+447700900111']}, tenant='OTHER')
    assert taken.status_code == 409 and taken.json['error'] == 'route_assigned_elsewhere'
    assert taken.json['recipients'] == ['+447700900111'] and 'EXAMPLE' not in str(taken.json)
    # An operator-set route cannot be claimed either.
    assert _put(client, {'phone': ['+447700900001']}, tenant='OTHER').status_code == 409


def test_a_double_claim_written_around_the_check_routes_to_nobody(app, configured):
    storage = app.container.storage
    _create(storage, 'OTHER')
    for tenant in ('EXAMPLE', 'OTHER'):
        storage.write_json(tenant, channel_routes.FILENAME, channel_routes.validate(
            {'phone': ['+447700900333'], 'email': [{'address': 'shared@shop.example'}]}))
    channel_routes.invalidate()
    assert '+447700900333' not in channels.bindings('phone')
    assert 'shared@shop.example' not in channels.bindings('email')


def test_one_sending_address_is_never_shared_between_businesses(app, configured):
    storage = app.container.storage
    _create(storage, 'OTHER')
    storage.write_json('EXAMPLE', channel_routes.FILENAME, channel_routes.validate(
        {'email': [{'address': 'a@shop.example', 'sender': 'support@shop.example'}]}))
    storage.write_json('OTHER', channel_routes.FILENAME, channel_routes.validate(
        {'email': [{'address': 'b@shop.example', 'sender': 'support@shop.example'}]}))
    channel_routes.invalidate()
    senders = channels.email_senders()
    assert list(senders.values()).count('support@shop.example') == 1
    assert senders.get('business@example.com') == 'business@example.com'  # Operator routes unaffected.


def test_removing_an_assignment_stops_routing(client, configured):
    operator(client)
    _put(client, {'phone': ['+447700900111']})
    assert '+447700900111' in channels.bindings('phone')
    assert _put(client, {}).status_code == 200
    assert '+447700900111' not in channels.bindings('phone')


def test_whatsapp_senders_are_assigned_per_provider(client, app, configured):
    operator(client)
    assert _put(client, {'whatsapp_twilio': ['+447700900444'], 'whatsapp_meta': ['998877665544']}).status_code == 200
    with app.app_context():
        twilio, _ = recipient_routes(app.container.settings, 'twilio')
        meta, _ = recipient_routes(app.container.settings, 'meta')
    assert twilio['447700900444'] == 'EXAMPLE' and meta['998877665544'] == 'EXAMPLE'


def test_stale_revision_is_refused(client, configured):
    operator(client)
    assert client.put('/admin/api/channel-routes?tenant=EXAMPLE',
                      json={'revision': 'stale', 'routes': {'phone': ['+447700900111']}}).status_code == 409


def test_hand_over_number_cannot_be_an_assigned_assistant_number(client, configured):
    operator(client)
    _put(client, {'phone': ['+447700900111']})
    with pytest.raises(ValueError):
        channels.validate({'phone': {'handover_number': '+447700900111'}})
