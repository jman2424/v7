"""Synchronised business information reaches every assistant channel and MCP, for the right business only."""
import json

import pytest
import test_business_sync as helpers
from tests.test_mcp import call, data, issue, mcp  # noqa: F401
from werkzeug.security import generate_password_hash

platform = helpers.platform
CHANNELS = ('web', 'whatsapp', 'email', 'phone')


def ask(app, tenant, channel, text):
    """The same call the website, WhatsApp, email and phone handlers make."""
    with app.app_context():
        runtime = app.container.for_tenant(tenant)
        result = runtime.handler.handle(text, tenant=tenant, session_id=f'{channel}:sync-check', channel=channel,
                                        metadata={'request_id': 'sync-check', 'source': 'business_channel'})
    return str(result.get('reply') or '')


def test_every_channel_answers_from_the_synchronised_catalogue(platform, monkeypatch):
    app, client, csrf, remote, source_id, _ = helpers.connected(platform, monkeypatch)
    for channel in CHANNELS:
        assert '120.00' in ask(app, 'ALPHA', channel, 'How much is the Oak desk?')
    remote.products[1]['price'] = '135.00'
    del remote.products[2]
    helpers.run_sync(app, source_id)
    for channel in CHANNELS:
        reply = ask(app, 'ALPHA', channel, 'How much is the Oak desk?')
        assert '135.00' in reply and '120.00' not in reply, (channel, reply)
        # A product deleted at the source is no longer offered on any channel.
        assert 'desk lamp' not in ask(app, 'ALPHA', channel, 'Do you sell a desk lamp?').lower(), channel
    # The other business's assistant knows nothing about it.
    for channel in CHANNELS:
        reply = ask(app, 'BETA', channel, 'How much is the Oak desk?')
        assert '135' not in reply and 'Oak desk is' not in reply, (channel, reply)
    # The public website chat endpoint gives the same answer as the internal call.
    chat = app.test_client().post('/chat_api', json={'tenant': 'ALPHA', 'message': 'How much is the Oak desk?'})
    assert chat.status_code == 200 and '135.00' in chat.json['reply']


def test_queued_email_and_phone_replies_use_current_information(platform, monkeypatch):
    """Drive the real channel worker's answer step, as a queued email or call turn would."""
    from service import channel_worker
    app, client, csrf, remote, source_id, _ = helpers.connected(platform, monkeypatch)
    remote.products[1]['price'] = '142.00'
    helpers.run_sync(app, source_id)
    with app.app_context():
        for channel in ('email', 'phone'):
            job = {'tenant': 'ALPHA', 'channel': channel, 'conversation_id': channel + ':synthetic', 'payload': {'language': 'en'}}
            answer, _routine = channel_worker._answer(app.container, job, 'How much is the Oak desk?')
            assert '142.00' in answer, (channel, answer)


def test_mcp_and_rest_read_synchronised_data_and_two_businesses_stay_separate(mcp, monkeypatch):  # noqa: F811
    app, registry, _ = mcp
    records = json.loads(registry.read_text())
    records['users'].append({'email': 'beta-owner@example.test', 'role': 'business_owner', 'tenant': 'BETA',
                             'password_hash': generate_password_hash('Test-only-password-42!')})
    registry.write_text(json.dumps(records))
    _app, client, csrf, remote, source_id, _ = helpers.connected(mcp, monkeypatch)
    remote.products[1]['price'] = '135.00'
    remote.products[3] = {'id': 3, 'name': 'Bookshelf', 'price': '75', 'category': 'Furniture'}
    helpers.run_sync(app, source_id)
    alpha = issue(client)[0]['access_token']
    beta_client = app.test_client()
    beta = issue(beta_client, email='beta-owner@example.test')[0]['access_token']

    listed = {row['name']: row for row in data(client, alpha, 'get_catalog', {'limit': 50})['items']}
    assert listed['Oak desk']['price'] == 135.0 and listed['Bookshelf']['price'] == 75.0
    assert data(client, alpha, 'search_catalog', {'query': 'Bookshelf'})['items'][0]['name'] == 'Bookshelf'
    rest = client.get('/api/v1/catalog?limit=50', headers={'Authorization': 'Bearer ' + alpha})
    assert rest.status_code == 200 and {row['name'] for row in rest.json['items']} == set(listed)

    # Business B, with its own valid token, sees only its own catalogue ...
    other = {row['name'] for row in data(beta_client, beta, 'get_catalog', {'limit': 50})['items']}
    assert other == {'Beta tablet'}
    # ... and cannot change Business A's synchronised product, even by naming it exactly.
    revision = data(beta_client, beta, 'get_catalog')['revision']
    attempt = call(beta_client, beta, 'update_catalog_item', {
        'category': 'Furniture', 'name': 'Oak desk', 'changes': {'price': 1}, 'expected_revision': revision})
    assert attempt['isError']
    assert helpers.catalog(app)['Oak desk']['price'] == 135.0
    # A token for A used from B's browser session is still A's scope, never B's.
    assert {row['name'] for row in data(beta_client, alpha, 'get_catalog', {'limit': 50})['items']} == set(listed)

    # A permitted update made through MCP is a manual edit: the next sync does not undo it,
    # and a later source change asks a person instead of overwriting it.
    revision = data(client, alpha, 'get_catalog')['revision']
    changed = data(client, alpha, 'update_catalog_item', {
        'category': 'Furniture', 'name': 'Oak desk', 'changes': {'price': 130}, 'expected_revision': revision})
    assert changed['item']['price'] == 130
    helpers.run_sync(app, source_id)
    assert helpers.catalog(app)['Oak desk']['price'] == 130 and helpers.pending(app, source_id) is None
    remote.products[1]['price'] = '139.00'
    helpers.run_sync(app, source_id)
    assert helpers.catalog(app)['Oak desk']['price'] == 130
    assert 'conflicting_edits' in helpers.pending(app, source_id)['summary']['reasons']
