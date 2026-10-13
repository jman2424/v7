"""Offline checks for the real verification-mail adapter and provider failures."""
import json
import secrets
import ssl
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from service import registration_mail


@pytest.fixture
def resend_config(monkeypatch):
    key = secrets.token_urlsafe(24)
    for name, value in {
        'SMTP_HOST': 'smtp.resend.com', 'SMTP_USERNAME': 'resend',
        'SMTP_PASSWORD': key, 'SMTP_FROM': 'V7 <verify@example.test>',
    }.items():
        monkeypatch.setenv(name, value)
    return key


def provider_response(monkeypatch, status=200, body=b'{"id":"offline-email-id"}'):
    connection = Mock()
    connection.getresponse.return_value = SimpleNamespace(status=status, read=Mock(return_value=body))
    factory = Mock(return_value=connection)
    monkeypatch.setattr(registration_mail, 'HTTPSConnection', factory)
    return factory, connection


@pytest.mark.parametrize('missing', ['SMTP_HOST', 'SMTP_USERNAME', 'SMTP_PASSWORD', 'SMTP_FROM'])
def test_missing_configuration_disables_signup_and_prevents_mail(resend_config, monkeypatch, missing):
    monkeypatch.delenv(missing)
    factory = Mock(side_effect=AssertionError('Network must not be used'))
    monkeypatch.setattr(registration_mail, 'HTTPSConnection', factory)
    assert registration_mail.configured() is False
    assert registration_mail.sender_address() is None
    with pytest.raises(RuntimeError, match='Email verification is not configured'):
        registration_mail.send_code('applicant@example.test', '123456')
    factory.assert_not_called()


@pytest.mark.parametrize('sender', ['onboarding@resend.dev', 'V7 <onboarding@resend.dev>'])
def test_resend_test_sender_cannot_enable_public_signup(resend_config, monkeypatch, sender):
    monkeypatch.setenv('SMTP_FROM', sender)
    assert registration_mail.configured() is False
    assert registration_mail.sender_address() is None


def test_configured_sender_uses_authenticated_https_and_requires_accepted_email_id(resend_config, monkeypatch):
    factory, connection = provider_response(monkeypatch)
    # Render's Resend path must remain usable without an outbound SMTP port.
    monkeypatch.setattr(registration_mail.smtplib, 'SMTP', Mock(side_effect=AssertionError('SMTP must not be used')))
    monkeypatch.setattr(registration_mail.smtplib, 'SMTP_SSL', Mock(side_effect=AssertionError('SMTP must not be used')))
    assert registration_mail.configured() is True
    assert registration_mail.sender_address() == 'verify@example.test'
    registration_mail.send_code('applicant@example.test', '123456')
    args, options = factory.call_args
    assert args == ('api.resend.com',)
    assert options['timeout'] > 0
    assert options['context'].verify_mode == ssl.CERT_REQUIRED
    assert options['context'].check_hostname is True
    args, options = connection.request.call_args
    assert args == ('POST', '/emails')
    assert options['headers']['Authorization'] == 'Bearer ' + resend_config
    assert options['headers']['Content-Type'] == 'application/json'
    payload = json.loads(options['body'])
    assert payload['from'] == 'V7 <verify@example.test>'
    assert payload['to'] == ['applicant@example.test']
    assert '123456' in payload['text'] and '10 minutes' in payload['text']
    connection.close.assert_called_once_with()


@pytest.mark.parametrize('status,body', [
    (403, b'{"message":"private provider error"}'),
    (200, b'not-json'),
    (200, b'[]'),
    (200, b'{}'),
    (200, b'{"id":""}'),
    (200, b'{"id":" "}'),
    (200, b'{"id":123}'),
    (200, b'x' * 65537),
], ids=['rejected', 'malformed-json', 'non-object', 'missing-id', 'empty-id',
        'blank-id', 'non-string-id', 'oversized-response'])
def test_unaccepted_or_invalid_provider_response_fails_and_closes(resend_config, monkeypatch, status, body):
    _, connection = provider_response(monkeypatch, status, body)
    with pytest.raises(RuntimeError) as rejected:
        registration_mail.send_code('applicant@example.test', '123456')
    assert 'private provider error' not in str(rejected.value)
    connection.close.assert_called_once_with()


def test_connection_is_closed_after_transport_failure(resend_config, monkeypatch):
    _, connection = provider_response(monkeypatch)
    connection.request.side_effect = TimeoutError('Offline connection failure')
    with pytest.raises(TimeoutError):
        registration_mail.send_code('applicant@example.test', '123456')
    assert connection.close.call_count == 2
    keys = [call.kwargs['headers']['Idempotency-Key'] for call in connection.request.call_args_list]
    assert len(keys) == 2 and keys[0] == keys[1]


@pytest.mark.parametrize('sender,subject', [
    (registration_mail.send_reset_code, 'Reset your V7 password'),
    (registration_mail.send_email_change_code, 'Confirm your new V7 account email'),
])
def test_security_mail_uses_correct_recipient_purpose_and_expiry(resend_config, monkeypatch, sender, subject):
    _, connection = provider_response(monkeypatch)
    sender('account@example.test', '654321')
    payload = json.loads(connection.request.call_args.kwargs['body'])
    assert payload['to'] == ['account@example.test'] and payload['subject'] == subject
    assert '654321' in payload['text'] and '10 minutes' in payload['text']
    assert 'Do not share' in payload['text'] and 'authenticator' in payload['text']
    assert '654321' not in json.dumps(connection.request.call_args.kwargs['headers'])


@pytest.mark.parametrize('failure', ['server','timeout'])
def test_transient_failure_retries_identical_email_and_idempotency_key(resend_config, monkeypatch, failure):
    first, second = Mock(), Mock()
    if failure == 'timeout':
        first.request.side_effect = TimeoutError('offline transport detail')
    else:
        first.getresponse.return_value = SimpleNamespace(status=503)
    second.getresponse.return_value = SimpleNamespace(status=200,read=Mock(return_value=b'{"id":"offline-email-id"}'))
    factory = Mock(side_effect=[first,second])
    monkeypatch.setattr(registration_mail,'HTTPSConnection',factory)
    sleep = Mock()
    monkeypatch.setattr(registration_mail.time,'sleep',sleep)
    registration_mail.send_reset_code('account@example.test','654321')
    assert first.request.call_args == second.request.call_args
    assert factory.call_count == 2
    first.close.assert_called_once();second.close.assert_called_once()
    sleep.assert_called_once_with(0.5)


def test_certificate_failure_is_not_retried(resend_config, monkeypatch):
    factory, connection = provider_response(monkeypatch)
    connection.request.side_effect = ssl.SSLCertVerificationError('offline certificate check')
    with pytest.raises(ssl.SSLCertVerificationError):
        registration_mail.send_reset_code('account@example.test','654321')
    factory.assert_called_once();connection.close.assert_called_once()


@pytest.mark.parametrize('status',[401,403,422,429])
def test_permanent_errors_and_rate_limits_are_not_immediately_retried(resend_config, monkeypatch, status):
    factory, connection = provider_response(monkeypatch,status=status)
    with pytest.raises(RuntimeError):
        registration_mail.send_email_change_code('account@example.test','654321')
    factory.assert_called_once();connection.close.assert_called_once()
