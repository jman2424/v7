"""Pressing 0 passes a caller to the business's own number, with a message fallback."""
from urllib.parse import parse_qs, urlsplit
from xml.etree import ElementTree

import pytest
from twilio.request_validator import RequestValidator

from service import business_channels as channels, business_operations as operations
from service.ai_disclosure import phone_copy
from tests.test_business_channel_providers import ACCOUNT, CALL, configured as _configured, phone

configured = _configured
TEAM = '+447700900555'


def _set(configured, **values):
    prefs = channels.settings(configured.storage, 'EXAMPLE')
    prefs['phone'].update(values)
    configured.storage.write_json('EXAMPLE', channels.FILENAME, channels.validate(prefs))


def _gather_path(response):
    return ElementTree.fromstring(response.data).find('Gather').attrib['action']


def _post(client, app, path, **values):
    data = {'AccountSid': ACCOUNT, 'CallSid': CALL, 'To': '+447700900001', 'From': '+447700900002',
            'Direction': 'inbound', **values}
    url = app.container.settings.BASE_URL.rstrip('/') + path
    signed = RequestValidator('synthetic-phone-token').compute_signature(url, data)
    return client.post(path, data=data, headers={'X-Twilio-Signature': signed})


def test_hand_over_number_is_validated(configured, monkeypatch):
    for bad in ('07700900555', '+44 7700 900555', 'tel:+447700900555', 7700900555):
        with pytest.raises(ValueError):
            channels.validate({'phone': {'handover_number': bad}})
    # The assistant's own routed number would loop the call back to the assistant.
    with pytest.raises(ValueError):
        channels.validate({'phone': {'handover_number': '+447700900001'}})
    assert channels.validate({'phone': {'handover_number': TEAM}})['phone']['handover_number'] == TEAM
    assert channels.validate({})['phone']['handover_number'] == ''


def test_without_a_number_pressing_0_still_takes_a_message(client, app, configured):
    incoming = phone(client, app)
    assert phone_copy('en-GB', 'question') in incoming.text
    response = phone(client, app, _gather_path(incoming), Digits='0')
    assert '<Dial' not in response.text
    assert phone_copy('en-GB', 'message') in response.text


def test_pressing_0_dials_the_saved_number_and_records_it(client, app, configured):
    _set(configured, handover_number=TEAM)
    incoming = phone(client, app)
    assert phone_copy('en-GB', 'question', handover=True) in incoming.text
    response = phone(client, app, _gather_path(incoming), Digits='0')
    root = ElementTree.fromstring(response.data)
    dial = root.find('Dial')
    assert dial is not None and dial.find('Number').text == TEAM
    assert dial.attrib['timeout'] == '20' and dial.attrib['timeLimit'] == '900'
    assert 'callerId' not in dial.attrib
    assert phone_copy('en-GB', 'connecting', handover=True) in response.text
    job, = operations.listing('EXAMPLE')
    assert job['payload']['handover'] is True and job['payload']['text'] == ''


def test_missed_transfer_falls_back_to_a_message_and_answered_call_ends(client, app, configured):
    _set(configured, handover_number=TEAM)
    response = phone(client, app, _gather_path(phone(client, app)), Digits='0')
    action = ElementTree.fromstring(response.data).find('Dial').attrib['action']
    missed = _post(client, app, action, DialCallStatus='no-answer')
    assert missed.status_code == 200
    assert phone_copy('en-GB', 'no_answer', handover=True) in missed.text
    assert phone_copy('en-GB', 'message') in missed.text
    # The fallback cannot offer the transfer again.
    again = _post(client, app, _gather_path(missed), Digits='0')
    assert '<Dial' not in again.text
    answered = _post(client, app, action, DialCallStatus='completed')
    assert [node.tag for node in ElementTree.fromstring(answered.data)] == ['Hangup']


def test_transfer_result_reaches_the_route_without_a_browser_session(client, app, configured):
    """Twilio posts the transfer result with no cookie or CSRF token; its signature is the proof."""
    from flask.testing import FlaskClient
    _set(configured, handover_number=TEAM)
    response = phone(client, app, _gather_path(phone(client, app)), Digits='0')
    action = ElementTree.fromstring(response.data).find('Dial').attrib['action']
    provider = FlaskClient(app, app.response_class, use_cookies=False)
    missed = _post(provider, app, action, DialCallStatus='no-answer')
    assert missed.status_code == 200
    assert phone_copy('en-GB', 'no_answer', handover=True) in missed.text
    assert _post(provider, app, '/channels/phone/handover?token=forged', DialCallStatus='no-answer').status_code == 403


def test_transfer_result_needs_a_valid_signed_proof(client, app, configured):
    _set(configured, handover_number=TEAM)
    response = phone(client, app, _gather_path(phone(client, app)), Digits='0')
    action = ElementTree.fromstring(response.data).find('Dial').attrib['action']
    assert _post(client, app, '/channels/phone/handover?token=forged', DialCallStatus='no-answer').status_code == 403
    # A normal turn proof cannot be replayed as a transfer result.
    turn_proof = _gather_path(phone(client, app))
    token = parse_qs(urlsplit(turn_proof).query)['token'][0]
    assert _post(client, app, '/channels/phone/handover?token=' + token, DialCallStatus='no-answer').status_code == 403
    assert _post(client, app, action, DialCallStatus='no-answer', CallSid='CA' + '9' * 32).status_code == 403


def test_daily_limit_still_applies_to_transfers(client, app, configured):
    _set(configured, handover_number=TEAM, daily_limit=1)
    incoming = phone(client, app)
    phone(client, app, _gather_path(incoming), SpeechResult='Are you open today?')
    response = phone(client, app, _gather_path(incoming), Digits='0')
    assert '<Dial' not in response.text
    assert phone_copy('en-GB', 'limit') in response.text


def test_automatic_handoff_attempts_owner_then_backup_once(client, app, configured):
    backup = '+447700900556'
    _set(configured, handover_number=TEAM, backup_number=backup, auto_transfer=True)
    question = _post(client, app, _gather_path(phone(client, app)), SpeechResult='Can you make an exception?')
    poll = ElementTree.fromstring(question.data).find('Redirect').text
    job = operations.claim('EXAMPLE')
    assert operations.finish('EXAMPLE', job['id'], job['lease'], 'needs_review', error_code='call_followup_required')
    primary = ElementTree.fromstring(_post(client, app, poll).data).find('Dial')
    assert primary.find('Number').text == TEAM
    secondary = ElementTree.fromstring(_post(client, app, primary.attrib['action'], DialCallStatus='busy').data).find('Dial')
    assert secondary.find('Number').text == backup
    fallback = _post(client, app, secondary.attrib['action'], DialCallStatus='no-answer')
    assert '<Gather' in fallback.text and '<Dial' not in fallback.text
