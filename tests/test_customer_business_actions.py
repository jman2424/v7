"""Real customer action routes against isolated tenant data, no external sends."""
from datetime import datetime, timedelta, timezone

import pytest

from service.conversion_actions import list_action_requests
from tests.test_widget_tenancy import _add_tenant


@pytest.fixture
def actions(app):
    config = {'consultation': {'enabled': True, 'slots': [{
        'id':'review', 'start_at':(datetime.now(timezone.utc)+timedelta(days=2)).isoformat(),
        'label':'Business review'}]}, 'quote':{'enabled':True}, 'callback':{'enabled':True}}
    app.container.storage.write_json('EXAMPLE', 'sales_actions.json', config)
    return config


@pytest.mark.parametrize('action', ['consultation', 'quote', 'callback'])
def test_customer_can_submit_enabled_action_with_real_chat_identity(app, client, actions, action):
    chat = client.post('/chat_api', json={'tenant':'EXAMPLE','message':'hello'}).json
    payload = {'tenant':'EXAMPLE','conversation_token':chat['conversation_token'], 'action':action,
               'name':'Synthetic customer','contact':'synthetic@example.test','details':'Isolated workflow test',
               'consent':True,'idempotency_key':'action-'+action}
    if action == 'consultation':
        payload['slot_id'] = 'review'
    if action == 'callback':
        payload['contact'] = '+447700900123'
    first = client.post('/chat/actions', json=payload)
    assert first.status_code == 200
    assert first.json['status'] == ('confirmed' if action == 'consultation' else 'requested')
    assert client.post('/chat/actions', json=payload).json == first.json
    rows = list_action_requests('EXAMPLE')
    assert len(rows) == 1 and rows[0]['action'] == action
    conflict = client.post('/chat/actions', json={**payload,'details':'Changed details'})
    assert conflict.status_code == 409


def test_actions_reject_disabled_missing_consent_cross_tenant_and_bad_origin(app, client, actions):
    _add_tenant(app)
    token = client.post('/chat_api', json={'tenant':'EXAMPLE','message':'hello'}).json['conversation_token']
    payload = {'tenant':'EXAMPLE','conversation_token':token,'action':'callback',
               'name':'Synthetic customer','contact':'+447700900123','details':'Test','consent':True}
    assert client.post('/chat/actions', json={**payload,'tenant':'ALT'}).status_code == 403
    assert client.post('/chat/actions', json=payload,headers={'Origin':'https://unapproved.example'}).status_code == 403
    assert client.post('/chat/actions', json={**payload,'consent':False}).status_code == 400
    assert client.post('/chat/actions', json={**payload,'action':'refund'}).status_code == 400
    actions['callback']['enabled'] = False
    app.container.storage.write_json('EXAMPLE','sales_actions.json',actions)
    assert client.post('/chat/actions', json=payload).status_code == 409
    assert list_action_requests('EXAMPLE') == []
