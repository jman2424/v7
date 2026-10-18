"""Website click reports are authenticated activity, never inferred conversions."""
from unittest.mock import Mock, patch

import pytest
from flask.testing import FlaskClient

from routes import webchat_routes
from service import analytics_db
from tests.conftest import set_test_identity
from tests.test_widget_tenancy import _add_tenant


@pytest.fixture
def issued_click(app, client, monkeypatch):
    handle = Mock(return_value={'reply': 'Open the product page below.', 'intent': 'product',
                               'actions': [{'type': 'navigate', 'label': 'See products',
                                            'url': 'https://shop.example/products#catalog'}]})
    monkeypatch.setattr(app.container.for_tenant('EXAMPLE').handler, 'handle', handle)
    response = client.post('/chat_api', json={'tenant': 'EXAMPLE', 'message': 'See products',
                                             'message_id': 'show-products'})
    assert response.status_code == 200
    data = response.json
    assert data['actions'][0]['click_token']
    handle.reset_mock()
    return {'tenant': 'EXAMPLE', 'conversation_token': data['conversation_token'],
            'click_token': data['actions'][0]['click_token']}, data, handle


def _click_rows():
    with analytics_db._conn() as db:
        return [dict(row) for row in db.execute("SELECT * FROM events WHERE event_type='navigation_click'")]


def test_click_is_durable_deduplicated_and_does_not_call_ai(app, issued_click):
    payload, data, handle = issued_click
    public = FlaskClient(app)
    before = analytics_db.get_kpis(tenant='EXAMPLE', minutes=60)
    for _ in range(2):
        response = public.post('/chat/navigation-click', json=payload)
        assert response.status_code == 200 and response.json == {'ok': True}
        assert response.headers['Cache-Control'] == 'no-store'
    rows = _click_rows()
    assert len(rows) == 1
    assert rows[0]['tenant'] == 'EXAMPLE' and rows[0]['session_id'] == data['session_id']
    assert rows[0]['text'] == 'Clicked website button: See products'
    assert 'https://shop.example/products#catalog' in rows[0]['meta_json']
    assert analytics_db.get_kpis(tenant='EXAMPLE', minutes=60) == before
    handle.assert_not_called()


def test_client_cannot_replace_the_issued_label_url_or_session(client, issued_click):
    payload, data, _ = issued_click
    response = client.post('/chat/navigation-click', json={**payload, 'label': 'Paid in full',
        'url': 'https://other.example/secret', 'session_id': 'another-customer', 'event_id': 'forged'})
    assert response.status_code == 200
    row = _click_rows()[0]
    assert row['session_id'] == data['session_id']
    assert row['text'] == 'Clicked website button: See products'
    assert 'other.example' not in row['meta_json']


@pytest.mark.parametrize('field', ['conversation_token', 'click_token'])
@pytest.mark.parametrize('value', ['', None, 123, 'forged'])
def test_forged_or_missing_proofs_are_rejected(client, issued_click, field, value):
    payload, _, handle = issued_click
    assert client.post('/chat/navigation-click', json={**payload, field: value}).status_code == 403
    assert _click_rows() == []
    handle.assert_not_called()


def test_other_conversation_cannot_use_an_issued_button(client, issued_click):
    payload, _, handle = issued_click
    second = client.post('/chat_api', json={'tenant': 'EXAMPLE', 'message': 'New conversation'}).json
    handle.reset_mock()
    assert client.post('/chat/navigation-click', json={**payload,
        'conversation_token': second['conversation_token']}).status_code == 403
    assert _click_rows() == []
    handle.assert_not_called()


def test_cross_tenant_report_is_rejected(app, client, issued_click):
    _add_tenant(app)
    payload, _, handle = issued_click
    assert client.post('/chat/navigation-click', json={**payload, 'tenant': 'ALT'}).status_code == 403
    assert _click_rows() == []
    handle.assert_not_called()


def test_expired_click_proof_is_rejected(app, client, issued_click):
    payload, _, _ = issued_click
    with app.app_context():
        issued = webchat_routes._navigation_signer().loads(payload['click_token'])
        with patch('itsdangerous.timed.TimestampSigner.get_timestamp', return_value=1):
            expired = webchat_routes._navigation_signer().dumps(issued)
    response = client.post('/chat/navigation-click', json={**payload, 'click_token': expired})
    assert response.status_code == 403 and response.json['error'] == 'navigation_click_expired'
    assert _click_rows() == []


def test_click_origin_checks_are_identical_to_chat(client, issued_click):
    payload, _, _ = issued_click
    assert client.post('/chat/navigation-click', json=payload, headers={'Origin': 'https://hostile.example'}).status_code == 403
    assert _click_rows() == []
    response = client.options('/chat/navigation-click?tenant=EXAMPLE', headers={'Origin': 'http://localhost'})
    assert response.status_code == 204
    assert response.headers['Access-Control-Allow-Origin'] == 'http://localhost'


def test_failed_storage_is_visible_to_telemetry_client(client, issued_click, monkeypatch):
    payload, _, _ = issued_click
    monkeypatch.setattr(webchat_routes, 'log_navigation_click', Mock(side_effect=RuntimeError('storage unavailable')))
    response = client.post('/chat/navigation-click', json=payload)
    assert response.status_code == 503 and response.json == {'error': 'click_tracking_unavailable'}
    assert _click_rows() == []


def test_click_is_visible_only_in_authorized_tenant_conversations(app, client, issued_click):
    payload, _, _ = issued_click
    assert client.post('/chat/navigation-click', json=payload).status_code == 200
    assert client.get('/admin/api/conversations?tenant=EXAMPLE').status_code == 401
    _add_tenant(app)
    with client.session_transaction() as state:
        set_test_identity(client, state, {'id': 'owner', 'roles': ['business_owner'], 'tenant': 'EXAMPLE'})
    messages = client.get('/admin/api/conversations?tenant=EXAMPLE').json['messages']
    assert [row['text'] for row in messages if row['event_type'] == 'navigation_click'] == ['Clicked website button: See products']
    assert client.get('/admin/api/conversations?tenant=ALT').status_code == 403
