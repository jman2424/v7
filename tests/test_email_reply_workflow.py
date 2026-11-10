"""Email enquiries use the shared answer pipeline before bound provider delivery."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from connectors import business_email
from service import business_operations, channel_worker
from service.ai_disclosure import EMAIL_NOTICE
from tests.test_business_channel_providers import EMAIL_ID, configured as _configured, intake, received
from tests.test_channel_intelligence import TERMS, shared_brain


configured = _configured


def _content(message, **kwargs):
    return business_email.content(message, expected_sender='visitor@example.net',
                                  expected_recipient='business@example.com', **kwargs)


def test_subject_only_enquiry_is_answered_by_shared_handler_and_sent_to_original_sender(
        app, client, configured, monkeypatch):
    _, calls = shared_brain(configured, monkeypatch)
    transport = []

    def request(method, path, **kwargs):
        transport.append((method, path, kwargs))
        if method == 'GET':
            return received(id=EMAIL_ID, text='', subject='How do estimates work?',
                            headers={'Reply-To': 'unrelated@example.org'})
        return {'id': 'synthetic-delivery'}

    monkeypatch.setattr(business_email, '_request', request)
    operation_id = intake(client).json['reference']
    with app.app_context():
        assert channel_worker.process_one(configured, 'EXAMPLE')
        prepared = business_operations.get('EXAMPLE', operation_id)
        assert prepared['state'] == 'approved' and TERMS in prepared['reply']
        assert channel_worker.process_one(configured, 'EXAMPLE')
        assert not channel_worker.process_one(configured, 'EXAMPLE')

    assert len(calls) == 1 and calls[0][1]['response_channel'] == 'email'
    assert transport[0][:2] == ('GET', f'/emails/receiving/{EMAIL_ID}?html_format=cid')
    method, path, arguments = transport[1]
    assert (method, path) == ('POST', '/emails')
    assert arguments['idempotency_key'] == 'v7-reply-' + operation_id
    delivery = arguments['data']
    assert delivery['to'] == ['visitor@example.net']
    assert delivery['subject'] == 'Re: How do estimates work?'
    assert delivery['headers']['In-Reply-To'] == '<synthetic@example.net>'
    assert TERMS in delivery['text'] and delivery['text'].count(EMAIL_NOTICE) == 1
    assert business_operations.get('EXAMPLE', operation_id)['state'] == 'completed'


@pytest.mark.parametrize('message', [
    {'text': 'Do you take deposits?\n\nOn Tue, 10 Nov 2026,\n'
             'Visitor <visitor@example.net> wrote:\n> Quoted instructions\nOld thread'},
    {'text': 'Do you take deposits?\r\n-- \r\nSignature and old information'},
    {'text': '', 'html': '<p>Do you take deposits?</p><span style="display:none">Hidden text</span>'
                         '<div class="gmail_quote"><div>Old thread</div>Quoted instructions</div>'},
    {'text': '', 'html': '<p>Do you take deposits?</p><div id="divRplyFwdMsg">Old mail header</div>'
                         '<p>Quoted instructions</p>'},
])
def test_only_current_question_and_meaningful_subject_reach_the_agent(message):
    clean = _content(received(subject='Re: Deposit policy', **message))
    assert business_email.question_text(clean) == 'Subject: Deposit policy\n\nDo you take deposits?'


@pytest.mark.parametrize('message', [
    {'subject': 'Re: Old question', 'text': ''},
    {'subject': 'Old question', 'text': '> Old body'},
    {'subject': 'Old question', 'text': '', 'html': '<blockquote>Old body</blockquote>'},
    {'subject': '(no subject)', 'text': ''},
])
def test_missing_new_question_needs_review(message):
    with pytest.raises(business_email.EmailTransportError, match='^email_body_needs_review$'):
        business_email.question_text(_content(received(**message)))


def test_day_of_week_question_is_not_mistaken_for_attribution():
    clean = _content(received(subject='', text='On Saturday, are you open?\n\n'
                              'On Friday the visitor wrote:\n> Old body'))
    assert business_email.question_text(clean) == 'On Saturday, are you open?'


def test_oversized_combination_preserves_current_body_and_deduplicates_subject():
    body = 'Is this option available? ' + 'x' * 3970
    assert business_email.question_text(_content(received(subject='Availability', text=body))) == body
    assert business_email.question_text(_content(received(subject='Do you take deposits?',
                                                         text='Do you take deposits?'))) == 'Do you take deposits?'


def test_signed_intake_rejects_ambiguous_sender_before_queueing(client, configured):
    assert intake(client, **{'from': 'visitor@example.net, somebody@example.org'}).status_code == 400
    assert business_operations.listing('EXAMPLE') == []


def test_fetched_envelope_with_second_routed_business_is_not_answered(client, app, configured, monkeypatch):
    _, calls = shared_brain(configured, monkeypatch)
    operation_id = intake(client).json['reference']
    monkeypatch.setattr(business_email, 'receive', lambda _: received(
        to=['business@example.com', 'other@example.com']))
    with app.app_context():
        assert channel_worker.process_one(configured, 'EXAMPLE')
    job = business_operations.get('EXAMPLE', operation_id)
    assert job['state'] == 'needs_review' and job['error_code'] == 'email_envelope_mismatch'
    assert calls == []


@pytest.mark.parametrize('message_id', [
    '<a@example.net> <b@example.net>', '<a@example.net>\r\nBcc: somebody@example.org',
    '<a b@example.net>', {'not': 'a message identifier'},
])
def test_invalid_or_legacy_message_id_cannot_enter_reply_headers(monkeypatch, message_id):
    assert _content(received(message_id=message_id))['message_id'] == ''
    requests = []

    def request(*_, **kwargs):
        requests.append(kwargs['data'])
        return {'id': 'synthetic-delivery'}

    monkeypatch.setattr(business_email, '_request', request)
    business_email.send_reply({'id': 'a' * 32, 'source_address': 'visitor@example.net',
                               'payload': {'recipient': 'business@example.com', 'message_id': message_id}},
                              'The team can help with that.')
    assert 'In-Reply-To' not in requests[0]['headers']
    assert 'References' not in requests[0]['headers']


def test_conflicting_provider_write_is_uncertain_and_uses_explicit_transport_key(monkeypatch):
    connection = Mock()
    connection.getresponse.return_value = SimpleNamespace(status=409, read=lambda _: b'{}')
    connect = Mock(return_value=connection)
    monkeypatch.setattr(business_email, 'HTTPSConnection', connect)
    monkeypatch.setattr(business_email, 'resend_key', lambda: pytest.fail('Default mailbox key used'))

    with pytest.raises(business_email.EmailTransportError, match='^email_provider_rejected$') as result:
        business_email._request('POST', '/emails', api_key='synthetic-scoped-key',
                                data={'text': 'example'}, idempotency_key='fixture')
    assert result.value.uncertain
    assert connect.call_args.args == ('api.resend.com',)
    assert connection.request.call_args.kwargs['headers']['Authorization'] == 'Bearer synthetic-scoped-key'
    assert connection.request.call_args.kwargs['headers']['Idempotency-Key'] == 'fixture'
    connection.close.assert_called_once()
