"""Signed call continuations, live mode changes and bounded waiting."""
import json
from xml.etree import ElementTree

from routes.business_channel_routes import _phone_signer
from service import business_channels as channels, business_operations as operations, channel_worker
from service.ai_disclosure import phone_copy
from tests.test_business_channel_providers import CALL, configured as _configured, fake_answer, phone

configured = _configured


def _next_path(response, node):
    element = ElementTree.fromstring(response.data).find(node)
    assert element is not None
    return element.attrib['action'] if node == 'Gather' else element.text


def _change_mode(configured, mode):
    settings = channels.settings(configured.storage, 'EXAMPLE')
    settings['phone']['mode'] = mode
    configured.storage.write_json('EXAMPLE', channels.FILENAME, settings)


def _start_question(client, app):
    gather = _next_path(phone(client, app), 'Gather')
    return _next_path(phone(client, app, gather, SpeechResult='When do you open?'), 'Redirect')


def test_review_disclosure_cannot_turn_into_automatic_processing_mid_call(client, app, configured, monkeypatch):
    _change_mode(configured, 'review')
    incoming = phone(client, app)
    assert ElementTree.fromstring(incoming.data)[0].text == phone_copy('en-GB', 'review')
    _change_mode(configured, 'automatic')
    answer = phone(client, app, _next_path(incoming, 'Gather'), SpeechResult='When do you open?')
    assert phone_copy('en-GB', 'saved') in answer.text

    def unexpected_answer(*args):
        raise AssertionError('review-only call invoked AI')

    monkeypatch.setattr(channel_worker, '_answer', unexpected_answer)
    assert channel_worker.process_one(configured, 'EXAMPLE')
    job, = operations.listing('EXAMPLE')
    assert job['payload']['mode_at_intake'] == 'review'
    assert job['error_code'] == 'call_message_received'


def test_legacy_turn_without_a_signed_mode_is_review_only(client, app, configured):
    with app.app_context():
        token = _phone_signer().dumps({
            'tenant': 'EXAMPLE', 'call': CALL, 'turn': 1, 'silence': 0, 'handoff': False, 'unclear': 0,
        })

    result = phone(client, app, '/channels/phone/turn?token='+token, SpeechResult='When do you open?')

    assert result.status_code == 200
    assert phone_copy('en-GB', 'saved') in result.text
    job, = operations.listing('EXAMPLE')
    assert job['payload']['mode_at_intake'] == 'review'


def test_legacy_poll_uses_the_saved_automatic_mode(client, app, configured):
    payload = {
        'recipient': '+447700900001', 'call': CALL, 'turn': 1, 'text': 'When do you open?',
        'mode_at_intake': 'automatic', 'transcript_needs_review': False,
    }
    job, _ = operations.enqueue('EXAMPLE', 'phone', CALL+':1', 'phone:'+CALL, '+447700900002',
                                payload, daily_limit=20)
    leased = operations.claim('EXAMPLE')
    assert operations.finish('EXAMPLE', job['id'], leased['lease'], 'completed', reply='We open at ten.',
                             payload={**payload, 'phone_reply_verified': True})
    with app.app_context():
        token = _phone_signer().dumps({'tenant': 'EXAMPLE', 'call': CALL, 'job': job['id'], 'turn': 1, 'poll': 0})

    result = phone(client, app, '/channels/phone/poll?token='+token)

    assert result.status_code == 200
    assert 'We open at ten.' in result.text


def test_transcript_that_exceeds_the_queue_limit_gets_a_safe_handoff(client, app, configured):
    gather = _next_path(phone(client, app), 'Gather')

    result = phone(client, app, gather, SpeechResult='é'*3900)

    assert result.status_code == 200
    assert phone_copy('en-GB', 'unavailable') in result.text
    assert phone_copy('en-GB', 'saved') not in result.text
    assert ElementTree.fromstring(result.data).find('Hangup') is not None
    assert not operations.listing('EXAMPLE')


def test_duplicate_turn_with_a_different_caller_is_rejected(client, app, configured):
    gather = _next_path(phone(client, app), 'Gather')
    assert phone(client, app, gather, SpeechResult='When do you open?').status_code == 200

    replay = phone(client, app, gather, From='+447700900008', SpeechResult='Another question')

    assert replay.status_code == 403
    job, = operations.listing('EXAMPLE')
    assert job['source_address'] == '+447700900002'
    assert job['payload']['text'] == 'When do you open?'


def test_signed_continuations_are_bound_to_the_original_business_number(client, app, configured, monkeypatch):
    other_number = '+447700900009'
    monkeypatch.setenv('V7_PHONE_ROUTES_JSON',
                       json.dumps({'+447700900001': 'EXAMPLE', other_number: 'EXAMPLE'}))
    gather = _next_path(phone(client, app), 'Gather')
    other_turn = phone(client, app, gather, To=other_number, SpeechResult='Opening hours?')
    assert other_turn.status_code == 403
    assert not operations.listing('EXAMPLE')
    poll = _next_path(phone(client, app, gather, SpeechResult='Opening hours?'), 'Redirect')
    assert phone(client, app, poll, To=other_number).status_code == 403
    assert phone(client, app, poll, From='+447700900008').status_code == 403


def test_replayed_turn_cannot_reinterpret_a_saved_review_message(client, app, configured):
    gather = _next_path(phone(client, app), 'Gather')
    retry = phone(client, app, gather, SpeechResult='Hard to hear', Confidence='0.2')
    gather = _next_path(retry, 'Gather')
    first = phone(client, app, gather, SpeechResult='Please call me', Confidence='0.3')
    replay = phone(client, app, gather, SpeechResult='Opening hours?', Confidence='0.9')
    assert phone_copy('en-GB', 'saved') in first.text and first.data == replay.data
    job, = operations.listing('EXAMPLE')
    assert job['payload']['text'] == 'Please call me'
    assert job['payload']['mode_at_intake'] == 'review'


def test_wait_uses_the_original_job_deadline_on_provider_retry(client, app, configured):
    poll = _start_question(client, app)
    job, = operations.listing('EXAMPLE')
    with operations.connection('EXAMPLE', write=True) as db:
        db.execute('UPDATE business_operations SET created=? WHERE tenant=? AND id=?',
                   (job['created']-25, 'EXAMPLE', job['id']))
    result = phone(client, app, poll)
    assert phone_copy('en-GB', 'followup') in result.text
    assert ElementTree.fromstring(result.data).find('Redirect') is None
    assert phone(client, app, poll).data == result.data
    assert operations.get('EXAMPLE', job['id'])['error_code'] == 'call_reply_timed_out'
    assert not channel_worker.process_one(configured, 'EXAMPLE')


def test_answer_completed_during_timeout_is_played_once_ready(client, app, configured, monkeypatch):
    poll = _start_question(client, app)
    job, = operations.listing('EXAMPLE')
    with operations.connection('EXAMPLE', write=True) as db:
        db.execute('UPDATE business_operations SET created=? WHERE tenant=? AND id=?',
                   (job['created']-25, 'EXAMPLE', job['id']))

    def finish_before_review(tenant, identifier, *, reason):
        assert reason == 'call_reply_timed_out'
        leased = operations.claim(tenant)
        assert leased['id'] == identifier
        assert operations.finish(tenant, identifier, leased['lease'], 'completed', reply='We open at ten.',
                                 payload={**leased['payload'], 'phone_reply_verified': True})
        return False

    monkeypatch.setattr(operations, 'expire_call_turn', finish_before_review)
    response = phone(client, app, poll)
    assert 'We open at ten.' in response.text
    assert phone_copy('en-GB', 'followup') not in response.text


def test_switch_to_review_blocks_an_unheard_reply_even_after_manual_completion(client, app, configured, monkeypatch):
    poll = _start_question(client, app)
    fake_answer(monkeypatch, configured)
    channel_worker.process_one(configured, 'EXAMPLE')
    job, = operations.listing('EXAMPLE')
    assert job['state'] == 'completed'

    _change_mode(configured, 'review')
    result = phone(client, app, poll)
    assert phone_copy('en-GB', 'followup') in result.text
    assert job['reply'] not in result.text
    review = operations.get('EXAMPLE', job['id'])
    assert review['state'] == 'needs_review'
    assert review['error_code'] == 'call_review_mode_changed'

    operations.decide('EXAMPLE', job['id'], review['version'], 'complete', reply='Private team note')
    _change_mode(configured, 'automatic')
    replay = phone(client, app, poll)
    assert 'Private team note' not in replay.text
    assert phone_copy('en-GB', 'unavailable') in replay.text


def test_spoken_answer_invites_another_question_or_keypad_exit(client, app, configured, monkeypatch):
    poll = _start_question(client, app)
    fake_answer(monkeypatch, configured)
    channel_worker.process_one(configured, 'EXAMPLE')
    spoken = phone(client, app, poll)
    assert phone_copy('en-GB', 'anything_else') in spoken.text
    end = phone(client, app, _next_path(spoken, 'Gather'), Digits='9')
    assert phone_copy('en-GB', 'goodbye') in end.text
    assert ElementTree.fromstring(end.data).find('Hangup') is not None
    assert len(operations.listing('EXAMPLE')) == 1


def test_silence_after_a_spoken_answer_uses_the_normal_close(client, app, configured, monkeypatch):
    poll = _start_question(client, app)
    fake_answer(monkeypatch, configured)
    channel_worker.process_one(configured, 'EXAMPLE')
    spoken = phone(client, app, poll)
    retry = phone(client, app, _next_path(spoken, 'Gather'))
    end = phone(client, app, _next_path(retry, 'Gather'))
    assert phone_copy('en-GB', 'end') in end.text
    assert phone_copy('en-GB', 'silent') not in end.text
