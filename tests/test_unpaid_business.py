"""An unpaid business shows no widget and tells customers how to reach it."""
from dataclasses import replace
from xml.etree import ElementTree

import pytest
from twilio.request_validator import RequestValidator

from service import tenant_access
from tests.test_business_channel_providers import configured as _configured, phone

configured = _configured
INACTIVE = {'active': False, 'status': 'awaiting_payments'}


@pytest.fixture
def unpaid(monkeypatch):
    monkeypatch.setattr(tenant_access, 'activation', lambda tenant: dict(INACTIVE))
    tenant_access._notified.clear()


def test_notice_uses_only_the_saved_name_and_a_valid_contact_email():
    notice = tenant_access.unavailable_notice({'name': '  Corner   Shop ', 'email': 'Help@Shop.example'})
    assert notice == 'This assistant is currently unavailable. Please contact Corner Shop by email at help@shop.example.'
    fallback = tenant_access.unavailable_notice({'name': '<script>', 'email': 'not an address'})
    assert fallback == 'This assistant is currently unavailable. Please contact the business directly.'
    assert 'pay' not in notice.lower() and 'subscription' not in notice.lower()
    assert tenant_access.unavailable_notice(None).endswith('contact the business directly.')


def test_notice_is_sent_to_a_sender_at_most_once_a_day():
    tenant_access._notified.clear()
    assert tenant_access.notice_due('EXAMPLE', '+447700900002', now=1000)
    assert not tenant_access.notice_due('EXAMPLE', '+447700900002', now=2000)
    assert tenant_access.notice_due('OTHER', '+447700900002', now=2000)
    assert tenant_access.notice_due('EXAMPLE', '+447700900002', now=1000 + 86400)


def test_widget_disappears_and_direct_chat_shows_the_contact_message(client, unpaid):
    script = client.get('/widget.js?tenant=EXAMPLE')
    assert script.status_code == 200 and script.mimetype == 'application/javascript'
    assert 'iframe' not in script.text and 'chat_ui' not in script.text
    page = client.get('/chat_ui?tenant=EXAMPLE')
    assert page.status_code == 403 and 'This assistant is currently unavailable.' in page.text
    assert '<form' not in page.text
    reply = client.post('/chat_api?tenant=EXAMPLE', json={'message': 'Hello'})
    assert reply.status_code == 403 and reply.json['error'] == 'business_awaiting_activation'
    assert reply.json['message'].startswith('This assistant is currently unavailable.')
    assert client.get('/widget.js?tenant=NO_SUCH_BUSINESS').status_code == 404


def test_message_handler_never_runs_the_assistant_for_an_unpaid_business(app, unpaid):
    with app.app_context():
        runtime = app.container.for_tenant('EXAMPLE')
        result = runtime.handler.handle('What do you sell?', tenant='EXAMPLE', session_id='unpaid-test')
    assert result['intent'] == 'business_inactive'
    assert result['reply'].startswith('This assistant is currently unavailable.')


def test_whatsapp_sender_is_told_once_how_to_reach_the_business(client, app, unpaid, monkeypatch):
    app.container.settings = replace(app.container.settings, WHATSAPP_PROVIDER_MODE='auto')
    monkeypatch.setenv('TWILIO_AUTH_TOKEN', 'configured-token')
    monkeypatch.setenv('TWILIO_WHATSAPP_NUMBER', 'whatsapp:+447700900999')

    def send(sid):
        form = {'Body': 'Are you open?', 'From': 'whatsapp:+447123456789', 'To': 'whatsapp:+447700900999',
                'MessageSid': sid}
        url = app.container.settings.BASE_URL + '/whatsapp/webhook'
        signature = RequestValidator('configured-token').compute_signature(url, form)
        return client.post('/whatsapp/webhook', data=form, headers={'X-Twilio-Signature': signature})

    first = send('SMunpaid-1')
    assert first.status_code == 200
    assert 'This assistant is currently unavailable.' in first.text
    second = send('SMunpaid-2')
    assert second.status_code == 200 and 'unavailable' not in second.text


def test_caller_hears_the_contact_message_and_the_call_ends(client, app, configured, unpaid):
    response = phone(client, app)
    assert response.status_code == 200
    root = ElementTree.fromstring(response.data)
    assert [node.tag for node in root] == ['Say', 'Hangup']
    assert root[0].text.startswith('This assistant is currently unavailable.')
