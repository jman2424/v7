"""Synthetic channel delivery checks; no paid models, real mail or calls."""
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree

import pytest

from connectors import business_email as email
from routes.business_channel_routes import _phone_signer
from service import business_channels as channels, business_operations as operations, channel_worker
from service.ai_disclosure import AI_LABEL, EMAIL_NOTICE, MESSAGE_LABEL, WEB_NOTICE, email_reply, message_reply, phone_copy
from tests.test_business_channel_providers import configured as _configured, phone, CALL

configured = _configured


@pytest.mark.parametrize('language', channels.LANGUAGES)
@pytest.mark.parametrize('mode', ['automatic', 'review'])
def test_phone_identification_precedes_input_collection(client, app, configured, language, mode):
    saved = channels.settings(configured.storage, 'EXAMPLE')
    saved['phone'].update(language=language, mode=mode)
    configured.storage.write_json('EXAMPLE', channels.FILENAME, saved)
    document = ElementTree.fromstring(phone(client, app).data)
    assert document[0].tag == 'Say'
    assert document[0].text == phone_copy(language, mode)
    assert document[0].attrib['language'] == language
    assert document.find('Gather').attrib['actionOnEmptyResult'] == 'true'
    assert document.find('Gather').attrib['input'] == 'speech dtmf'
    assert document.find('Record') is None


def test_silent_call_gets_one_retry_without_a_false_saved_message(client, app, configured):
    first = ElementTree.fromstring(phone(client, app).data).find('Gather').attrib['action']
    retry = phone(client, app, first)
    assert retry.status_code == 200
    gather = ElementTree.fromstring(retry.data).find('Gather')
    assert gather is not None
    assert 'did not hear' in gather.find('Say').text
    ended = phone(client, app, gather.attrib['action'])
    assert ended.status_code == 200
    assert ElementTree.fromstring(ended.data).find('Gather') is None
    assert 'No enquiry was received or saved' in ended.text
    assert operations.listing('EXAMPLE') == []


def test_press_zero_takes_one_team_message_without_using_ai(client, app, configured, monkeypatch):
    monkeypatch.setattr(channel_worker, '_answer', lambda *_: pytest.fail('Review message must not call AI'))
    first = ElementTree.fromstring(phone(client, app).data).find('Gather').attrib['action']
    review = phone(client, app, first, Digits='0')
    path = ElementTree.fromstring(review.data).find('Gather').attrib['action']
    assert operations.listing('EXAMPLE') == []
    response = phone(client, app, path, SpeechResult='Please have the team call me about detailing.')
    assert response.status_code == 200 and 'saved for the team' in response.text
    assert phone(client, app, path, SpeechResult='Please have the team call me about detailing.').status_code == 200
    assert len(operations.listing('EXAMPLE')) == 1
    assert channel_worker.process_one(configured, 'EXAMPLE')
    job = operations.listing('EXAMPLE')[0]
    assert job['state'] == 'needs_review'
    assert job['payload']['mode_at_intake'] == 'review'
    assert not job['payload'].get('phone_reply_verified')
    assert not operations.listing('OTHER')


def test_review_mode_at_intake_cannot_be_upgraded_afterwards(client, app, configured, monkeypatch):
    saved = channels.settings(configured.storage, 'EXAMPLE')
    saved['phone']['mode'] = 'review'
    configured.storage.write_json('EXAMPLE', channels.FILENAME, saved)
    path = ElementTree.fromstring(phone(client, app).data).find('Gather').attrib['action']
    phone(client, app, path, SpeechResult='Please contact me.')
    saved['phone']['mode'] = 'automatic'
    configured.storage.write_json('EXAMPLE', channels.FILENAME, saved)
    monkeypatch.setattr(channel_worker, '_answer', lambda *_: pytest.fail('Intake requested human review'))
    channel_worker.process_one(configured, 'EXAMPLE')
    assert operations.listing('EXAMPLE')[0]['state'] == 'needs_review'


def test_phone_turn_rejects_conflicting_input_and_invalid_signed_retry_state(client, app, configured):
    path = ElementTree.fromstring(phone(client, app).data).find('Gather').attrib['action']
    assert phone(client, app, path, Digits='0', SpeechResult='Conflicting input').status_code == 400
    with app.app_context():
        invalid = _phone_signer().dumps({'tenant': 'EXAMPLE', 'call': CALL, 'turn': 1, 'silence': True})
    assert phone(client, app, '/channels/phone/turn?token='+invalid).status_code == 400
    assert operations.listing('EXAMPLE') == []


def test_phone_poll_cannot_substitute_a_different_turn(client, app, configured):
    path = ElementTree.fromstring(phone(client, app).data).find('Gather').attrib['action']
    turn = phone(client, app, path, SpeechResult='Opening hours?')
    poll = ElementTree.fromstring(turn.data).find('Redirect').text
    with app.app_context():
        proof = _phone_signer().loads(parse_qs(urlparse(poll).query)['token'][0])
        proof['turn'] = 2
        wrong_turn = _phone_signer().dumps(proof)
    assert phone(client, app, '/channels/phone/poll?token='+wrong_turn).status_code == 403


def test_email_footer_is_enforced_on_edited_drafts_without_changing_envelope(monkeypatch):
    sent = []
    monkeypatch.setattr(email, '_request', lambda *args, **kwargs: sent.append(kwargs) or {'id': 'accepted'})
    job = {'id': 'a'*32, 'source_address': 'visitor@example.net',
           'payload': {'recipient': 'business@example.com', 'subject': 'Prices'}}
    answer = 'The estimate starts at £100.\n\nPlease confirm your vehicle.'
    assert email.send_reply(job, answer) == 'accepted'
    assert sent[0]['data']['text'] == answer + '\n\n---\n' + EMAIL_NOTICE
    assert sent[0]['data']['to'] == ['visitor@example.net']
    assert sent[0]['idempotency_key'] == 'v7-reply-' + job['id']
    assert email_reply(email_reply(answer)) == email_reply(answer)


def test_message_disclosure_preserves_answer_and_is_not_duplicated():
    answer = 'Small £100\nMedium £150\nLarge £200'
    labelled = message_reply(answer)
    assert labelled == MESSAGE_LABEL + '\n\n' + answer
    assert message_reply(labelled) == labelled
    assert message_reply('') == ''


def test_custom_widget_branding_cannot_remove_ai_identification(client, app):
    branding = app.container.storage.read_json('EXAMPLE', 'branding.json')
    branding.setdefault('widget', {}).update(assistant_name='Alex', chat_title='Your concierge')
    app.container.storage.write_json('EXAMPLE', 'branding.json', branding)
    response = client.get('/chat_ui?tenant=EXAMPLE')
    assert response.status_code == 200
    assert 'widget__ai-label">AI assistant</span>' in response.text
    assert WEB_NOTICE in response.text


@pytest.mark.parametrize('accept', ['application/json', 'text/event-stream'])
def test_chat_api_discloses_ai_without_rewriting_the_reply(client, app, monkeypatch, accept):
    monkeypatch.setattr(app.container.for_tenant('EXAMPLE').handler, 'handle',
                        lambda *args, **kwargs: {'reply': 'Hello there.', 'intent': 'greeting'})
    response = client.post('/chat_api', json={'tenant': 'EXAMPLE', 'message': 'Hello'}, headers={'Accept': accept})
    assert response.status_code == 200
    result = response.json if accept == 'application/json' else json.loads(response.text.split('event: complete\ndata: ')[1])
    assert result['reply'] == 'Hello there.'
    assert result['ai_disclosure'] == {'label': AI_LABEL, 'notice': WEB_NOTICE}


def test_console_disclosure_translations_cover_supported_languages():
    messages = json.loads((Path(__file__).parents[1]/'dashboard/static/i18n/subscription.json').read_text(encoding='utf-8'))
    for language in ('en', 'es', 'fr', 'ar'):
        assert messages[language]['AI assistant. '+WEB_NOTICE]
