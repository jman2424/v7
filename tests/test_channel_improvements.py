"""Channel preflight and unclear speech: synthetic providers, no calls or sends."""
from xml.etree import ElementTree

import pytest

from service import business_channels as channels, business_operations as operations, channel_worker
from service.ai_disclosure import EMAIL_NOTICE, phone_copy
from tests.test_business_channel_providers import configured as _configured, phone, intake, owner, fake_answer, received

configured = _configured


def gather_path(response):
    return ElementTree.fromstring(response.data).find('Gather').attrib['action']


def test_unclear_speech_retries_once_then_saves_for_review_without_ai(client, app, configured, monkeypatch):
    path = gather_path(phone(client, app))
    retry = phone(client, app, path, SpeechResult='Unclear first words', Confidence='0.21')
    assert phone_copy('en-GB', 'unclear') in retry.text
    assert not operations.listing('EXAMPLE')
    path = gather_path(retry)
    response = phone(client, app, path, SpeechResult='Unclear second words', Confidence='0.3')
    assert 'saved for the team' in response.text
    monkeypatch.setattr(channel_worker, '_answer', lambda *_: pytest.fail('Unclear speech must not invoke AI'))
    channel_worker.process_one(configured, 'EXAMPLE')
    job = operations.listing('EXAMPLE')[0]
    assert job['state'] == 'needs_review'
    assert job['error_code'] == 'call_transcript_unclear'
    assert job['payload']['text'] == 'Unclear second words'
    assert not job['payload'].get('phone_reply_verified')
    # A provider retry is acknowledged without creating a second operation.
    phone(client, app, path, SpeechResult='Unclear second words', Confidence='0.3')
    assert len(operations.listing('EXAMPLE')) == 1
    assert not operations.listing('OTHER')


@pytest.mark.parametrize('confidence', ['', '0.5', '0.95', '1'])
def test_missing_or_usable_score_preserves_normal_answer_path(client, app, configured, confidence):
    path = gather_path(phone(client, app))
    result = phone(client, app, path, SpeechResult='When do you open?', Confidence=confidence)
    assert ElementTree.fromstring(result.data).find('Redirect') is not None
    assert operations.listing('EXAMPLE')[0]['payload']['mode_at_intake'] == 'automatic'


@pytest.mark.parametrize('confidence', ['nan', 'inf', '-0.1', '1.1', 'not a number', '0'*100])
def test_invalid_speech_score_fails_before_storage(client, app, configured, confidence):
    path = gather_path(phone(client, app))
    assert phone(client, app, path, SpeechResult='Hello', Confidence=confidence).status_code == 400
    assert not operations.listing('EXAMPLE')


def test_retried_clear_speech_and_keypad_handoff_remain_available(client, app, configured):
    path = gather_path(phone(client, app))
    retry = phone(client, app, path, SpeechResult='Unclear', Confidence='0.2')
    handoff = phone(client, app, gather_path(retry), Digits='0')
    result = phone(client, app, gather_path(handoff), SpeechResult='Please call me tomorrow', Confidence='0.9')
    assert 'saved for the team' in result.text
    assert operations.listing('EXAMPLE')[0]['payload']['mode_at_intake'] == 'review'


def test_clear_repeat_can_continue_automatic_conversation(client, app, configured):
    path = gather_path(phone(client, app))
    retry = phone(client, app, path, SpeechResult='Unclear', Confidence='0.2')
    result = phone(client, app, gather_path(retry), SpeechResult='What are your opening hours?', Confidence='0.8')
    assert ElementTree.fromstring(result.data).find('Redirect') is not None
    job = operations.listing('EXAMPLE')[0]
    assert job['payload']['mode_at_intake'] == 'automatic'
    assert job['payload']['transcript_needs_review'] is False


@pytest.mark.parametrize('unclear', [True, 2, '1'])
def test_invalid_signed_retry_state_cannot_bypass_validation(client, app, configured, unclear):
    from routes.business_channel_routes import _phone_signer
    from tests.test_business_channel_providers import CALL
    with app.app_context():
        token = _phone_signer().dumps({'tenant': 'EXAMPLE', 'call': CALL, 'turn': 1, 'unclear': unclear})
    assert phone(client, app, '/channels/phone/turn?token='+token, SpeechResult='Hello').status_code == 400
    assert not operations.listing('EXAMPLE')


@pytest.mark.parametrize('language', channels.LANGUAGES)
def test_unclear_prompt_is_available_for_every_call_language(language):
    assert phone_copy(language, 'unclear')


def test_preflight_reports_configured_not_live_verified_and_is_scoped(client, configured, monkeypatch):
    owner(client)
    data = client.get('/admin/api/business-channels?tenant=EXAMPLE').json
    assert data['email_notice'] == EMAIL_NOTICE
    assert all(data['channels']['phone']['checks'].values())
    assert 'other@example.com' not in str(data)
    monkeypatch.setenv('V7_CHANNEL_WORKER', 'false')
    data = channels.readiness(configured, 'EXAMPLE')
    assert data['channels']['phone']['checks']['worker'] is False
    monkeypatch.setattr('service.tenant_access.activation', lambda _: {'active': False})
    assert channels.readiness(configured, 'EXAMPLE')['channels']['phone']['checks']['business_active'] is False
    assert client.get('/admin/api/business-channels?tenant=OTHER').status_code == 403


def test_preflight_does_not_treat_legacy_grant_as_managed_policy_permission(configured):
    from service import agent_modules
    config = agent_modules.update_grants(configured.storage, 'EXAMPLE', {name: False for name in agent_modules.REGISTRY})
    configured.storage.write_json('EXAMPLE', agent_modules.FILENAME, config)
    assert channels.readiness(configured, 'EXAMPLE')['channels']['email']['checks']['permission'] is False


@pytest.mark.parametrize('failure,code', [
    (ValueError('channel_unapproved_link'), 'channel_unapproved_link'),
    (ValueError('channel_invalid_answer'), 'channel_invalid_answer'),
    (ValueError('private-token customer text /private/db'), 'channel_processing_failed'),
    (RuntimeError('channel_unapproved_link'), 'channel_processing_failed'),
])
def test_worker_exposes_only_allowlisted_failure_codes(client, configured, monkeypatch, failure, code):
    from connectors import business_email
    intake(client)
    monkeypatch.setattr(business_email, 'receive', lambda _: received())
    fake_answer(monkeypatch, configured, error=failure)
    channel_worker.process_one(configured, 'EXAMPLE')
    job = operations.listing('EXAMPLE')[0]
    assert job['state'] == 'needs_review'
    assert job['error_code'] == code
    assert job['reply'] == ''
