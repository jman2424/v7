"""Signed provider intake. No inbound field can grant a role or select a tenant."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import math
import os
import re
import time

from flask import Blueprint, Response, abort, current_app, jsonify, request
from itsdangerous import BadSignature, URLSafeTimedSerializer
from twilio.request_validator import RequestValidator
from twilio.twiml.voice_response import VoiceResponse

from connectors import business_email
from routes import get_container
from service import business_channels as channels, business_operations as operations, channel_worker
from service.ai_disclosure import phone_copy

bp = Blueprint('business_channels', __name__, url_prefix='/channels')
_SID = re.compile(r'CA[a-fA-F0-9]{32}\Z')
_MAX_CALL_TURNS = 12
_MAX_CALL_POLLS = 20


@dataclass(frozen=True)
class _PhoneCall:
    tenant: str
    recipient: str
    sid: str
    source: str

    def proof(self, **state):
        return _phone_signer().dumps({
            'tenant': self.tenant, 'recipient': self.recipient, 'call': self.sid, **state,
        })


def _phone_signer():
    return URLSafeTimedSerializer(current_app.secret_key, salt='v7-phone-turn-v1')


@bp.post('/email/webhook')
def email_webhook():
    secret = os.getenv('V7_EMAIL_WEBHOOK_SECRET', '')
    if not secret or not channels.resend_key():
        abort(503)
    raw = request.get_data()
    if not business_email.verify(raw, request.headers, secret):
        abort(403)
    try:
        event = json.loads(raw)
    except (ValueError, UnicodeError):
        abort(400)
    if not isinstance(event, dict):
        abort(400)
    if event.get('type') not in {'email.received', 'inbox.email.received'}:
        return jsonify(ok=True, ignored=True)
    data = event.get('data')
    if (not isinstance(data, dict) or not isinstance(data.get('email_id'), str)
            or not channels.UUID.fullmatch(data['email_id'])):
        abort(400)
    metadata, extras = data, {}
    inbox_recipient = None
    if event['type'] == 'inbox.email.received':
        if any(not isinstance(data.get(key), str) or not channels.UUID.fullmatch(data[key])
               for key in ('inbox_id', 'thread_id')):
            abort(400)
        inbox_recipient = channels.inbox_bindings().get(data['inbox_id'])
        metadata = data.get('email')
        thread = data.get('thread')
        if (not inbox_recipient or not isinstance(metadata, dict) or metadata.get('id') != data['email_id']
                or metadata.get('direction') != 'inbound'
                or isinstance(thread, dict) and thread.get('folder') == 'spam'):
            return jsonify(ok=True, ignored=True)
        extras = {'inbox_id': data['inbox_id'], 'thread_id': data['thread_id']}
    try:
        sender, recipients = business_email.envelope(metadata)
    except business_email.EmailTransportError:
        abort(400)
    routes = channels.bindings('email')
    matched = [(recipient, routes[recipient]) for recipient in recipients if recipient in routes]
    # A multi-tenant email cannot inherit one tenant's context by list order.
    if len(matched) != 1:
        return jsonify(ok=True, ignored=True)
    recipient, tenant = matched[0]
    if (inbox_recipient and inbox_recipient != recipient
            or not inbox_recipient and recipient in channels.inbox_bindings().values()):
        # Subscribe to the Inbox event for configured inboxes, never both
        # delivery products for one address, even if provider IDs differ.
        return jsonify(ok=True, ignored=True)
    container = get_container()
    if not container.storage.tenant_exists(tenant) or not channels.active(container.storage, tenant, 'email'):
        return jsonify(ok=True, ignored=True)
    if inbox_recipient and isinstance(data.get('thread'), dict) and data['thread'].get('folder') == 'trash':
        if not operations.previously_trashed(tenant, data['inbox_id'], data['thread_id']):
            return jsonify(ok=True, ignored=True)
        extras['restore_thread'] = True
    config = channels.settings(container.storage, tenant)['email']
    sending_address = channels.email_senders().get(recipient)
    if not sending_address:
        abort(503)
    try:
        job, created = operations.enqueue(tenant, 'email', data['email_id'],
            'email:'+hashlib.sha256((tenant+'\0'+data['email_id']).encode()).hexdigest(), sender,
            {'email_id': data['email_id'], 'recipient': recipient, 'sending_address': sending_address,
             'mode_at_intake': config['mode'], **extras},
            daily_limit=config['daily_limit'])
    except ValueError as exc:
        if str(exc) in {'channel_daily_limit', 'channel_sender_limit'}:
            return jsonify(ok=True, limited=True)
        abort(400)
    channel_worker.wake()
    return jsonify(ok=True, queued=created, reference=job['id'])


def _phone_context():
    container = get_container()
    token, account = os.getenv('V7_PHONE_AUTH_TOKEN', ''), os.getenv('V7_PHONE_ACCOUNT_SID', '')
    bindings = channels.bindings('phone')
    if not token or not account or not bindings:
        abort(503)
    if request.mimetype != 'application/x-www-form-urlencoded':
        abort(415)
    if any(len(request.form.getlist(key)) != 1 for key in request.form):
        abort(400)
    url = container.settings.BASE_URL.rstrip('/') + request.full_path.rstrip('?')
    if not RequestValidator(token).validate(url, request.form, request.headers.get('X-Twilio-Signature', '')):
        abort(403)
    if not hmac.compare_digest(account, request.form.get('AccountSid', '')):
        abort(403)
    if request.form.get('Direction') != 'inbound':
        abort(403)
    called, call = request.form.get('To', ''), request.form.get('CallSid', '')
    tenant = bindings.get(called)
    if not tenant or not _SID.fullmatch(call) or not container.storage.tenant_exists(tenant):
        abort(403)
    source = request.form.get('From', '')
    if not channels.PHONE.fullmatch(source):
        source = 'anonymous'
    if not channels.active(container.storage, tenant, 'phone'):
        abort(503)
    return container, _PhoneCall(tenant, called, call, source)


def _xml(response):
    return Response(str(response), content_type='application/xml; charset=utf-8')


def _gather(response, call, turn, language, prompt, *, call_mode, silence=0, handoff=False, unclear=0):
    proof = call.proof(turn=turn, call_mode=call_mode, silence=silence, handoff=handoff, unclear=unclear)
    gather = response.gather(input='speech dtmf', action='/channels/phone/turn?token='+proof,
                             method='POST', language=language, speech_timeout='auto', timeout=5,
                             num_digits=1, action_on_empty_result=True)
    gather.say(prompt, language=language)
    response.say(phone_copy(language, 'silent' if turn == 1 else 'end'), language=language)
    response.hangup()


@bp.post('/phone/incoming')
def phone_incoming():
    container, call = _phone_context()
    config = channels.settings(container.storage, call.tenant)['phone']
    response = VoiceResponse()
    language = config['language']
    # Identification plays before Gather so barge-in cannot skip the notice.
    response.say(phone_copy(language, config['mode']), language=language)
    prompt = phone_copy(language, 'message' if config['mode'] == 'review' else 'question')
    _gather(response, call, 1, language, prompt, call_mode=config['mode'])
    return _xml(response)


def _proof(call):
    tokens = request.args.getlist('token')
    if len(tokens) != 1:
        abort(403)
    try:
        proof = _phone_signer().loads(tokens[0], max_age=1800)
    except BadSignature:
        abort(403)
    # Existing signed continuations remain valid during a rolling release.
    if (not isinstance(proof, dict) or proof.get('tenant') != call.tenant or proof.get('call') != call.sid
            or proof.get('recipient', call.recipient) != call.recipient):
        abort(403)
    return proof


def _end_call(response, language, key):
    response.say(phone_copy(language, key), language=language)
    response.hangup()
    return _xml(response)


def _reply_to_phone_job(response, call, job, turn, config, *, polls=0, announce=False):
    language, mode = config['language'], config['mode']
    if not job or job['state'] == 'expired':
        return _end_call(response, language, 'unavailable')

    payload = job['payload']
    automatic_intake = payload.get('mode_at_intake') == 'automatic'
    pending = job['state'] in {'queued', 'processing'}
    mode_changed = automatic_intake and mode == 'review'
    remaining = operations.PHONE_REPLY_WINDOW - (time.time() - job['created'])
    timed_out = pending and automatic_intake and (polls >= _MAX_CALL_POLLS or remaining <= 0)
    if mode_changed or timed_out:
        reason = 'call_review_mode_changed' if mode_changed else 'call_reply_timed_out'
        if operations.expire_call_turn(call.tenant, job['id'], reason=reason):
            return _end_call(response, language, 'followup')
        # Generation or a manual review may have won the race with deferral.
        job = operations.get(call.tenant, job['id'])
        if not job or job['state'] == 'expired':
            return _end_call(response, language, 'unavailable')
        payload = job['payload']
        pending = job['state'] in {'queued', 'processing'}

    if (job['state'] == 'completed' and job['reply'] and not job['error_code']
            and mode == 'automatic' and automatic_intake and payload.get('phone_reply_verified') is True):
        response.say(job['reply'], language=language)
        if turn < _MAX_CALL_TURNS:
            _gather(response, call, turn+1, language, phone_copy(language, 'anything_else'), call_mode='automatic')
            return _xml(response)
        return _end_call(response, language, 'end')

    if pending and automatic_intake and mode == 'automatic' and not timed_out:
        if announce:
            response.say(phone_copy(language, 'waiting'), language=language)
        delay = min(1 if polls < 3 else 2, max(1, math.ceil(remaining)))
        response.pause(length=delay)
        token = call.proof(job=job['id'], turn=turn, poll=polls if announce else polls+1)
        response.redirect('/channels/phone/poll?token='+token, method='POST')
        return _xml(response)

    if not automatic_intake and (pending or job['state'] == 'needs_review'):
        return _end_call(response, language, 'saved')
    if job['state'] == 'needs_review':
        return _end_call(response, language, 'followup')
    return _end_call(response, language, 'unavailable')


@bp.post('/phone/turn')
def phone_turn():
    container, call = _phone_context()
    proof = _proof(call)
    turn, text = proof.get('turn'), request.form.get('SpeechResult', '').strip()
    silence, handoff = proof.get('silence', 0), proof.get('handoff', False)
    unclear = proof.get('unclear', 0)
    confidence = request.form.get('Confidence', '')
    # Optional provider signal, never proof of identity or business correctness.
    # Missing scores are supported; malformed/non-finite scores fail closed.
    score = None
    if confidence:
        try:
            if len(confidence) > 24:
                raise ValueError
            score = float(confidence)
            if not math.isfinite(score) or not 0 <= score <= 1:
                raise ValueError
        except ValueError:
            abort(400)
    digits = request.form.get('Digits', '')
    if (type(turn) is not int or not 1 <= turn <= _MAX_CALL_TURNS or len(text) > 4000 or '\x00' in text
            or type(silence) is not int or not 0 <= silence <= 1 or type(handoff) is not bool
            or type(unclear) is not int or not 0 <= unclear <= 1
            or digits and text):
        abort(400)
    config = channels.settings(container.storage, call.tenant)['phone']
    # A legacy turn proof cannot establish that the caller heard the automatic-mode notice.
    call_mode = proof.get('call_mode', 'review')
    if call_mode not in ('automatic', 'review'):
        abort(400)
    response = VoiceResponse()
    language = config['language']
    if digits == '9':
        return _end_call(response, language, 'goodbye')
    if digits == '0' and not handoff:
        _gather(response, call, turn, language, phone_copy(language, 'message'), call_mode=call_mode, handoff=True)
        return _xml(response)
    if not text or digits:
        if silence == 0:
            _gather(response, call, turn, language, phone_copy(language, 'retry'),
                    call_mode=call_mode, silence=1, handoff=handoff, unclear=unclear)
            return _xml(response)
        return _end_call(response, language, 'silent' if turn == 1 else 'end')
    low_confidence = score is not None and score < 0.5
    if low_confidence and unclear == 0:
        _gather(response, call, turn, language, phone_copy(language, 'unclear'),
                call_mode=call_mode, handoff=handoff, unclear=1)
        return _xml(response)
    review = 'review' in (call_mode, config['mode']) or handoff or low_confidence
    try:
        job, _ = operations.enqueue(call.tenant, 'phone', call.sid+':'+str(turn), 'phone:'+call.sid, call.source,
            {'recipient': call.recipient, 'call': call.sid, 'turn': turn, 'text': text,
             'language': language,
             'mode_at_intake': 'review' if review else 'automatic',
             'transcript_needs_review': low_confidence},
            daily_limit=config['daily_limit'])
    except ValueError as exc:
        code = str(exc)
        if code in {'channel_daily_limit', 'channel_sender_limit', 'call_turn_limit'}:
            return _end_call(response, language, 'limit')
        if code == 'operation_event_conflict':
            abort(403)
        if code == 'operation_too_large':
            return _end_call(response, language, 'unavailable')
        raise
    if job['state'] in {'queued', 'processing'}:
        channel_worker.wake()
    return _reply_to_phone_job(response, call, job, turn, config, announce=True)


@bp.post('/phone/poll')
def phone_poll():
    container, call = _phone_context()
    proof = _proof(call)
    polls, turn = proof.get('poll'), proof.get('turn')
    if (type(polls) is not int or not 0 <= polls <= _MAX_CALL_POLLS
            or type(turn) is not int or not 1 <= turn <= _MAX_CALL_TURNS):
        abort(403)
    try:
        job = operations.get(call.tenant, proof.get('job'))
    except ValueError:
        abort(403)
    if not job or job['conversation_id'] != 'phone:'+call.sid or job['channel'] != 'phone':
        abort(403)
    if job['state'] == 'expired':
        config = channels.settings(container.storage, call.tenant)['phone']
        return _end_call(VoiceResponse(), config['language'], 'unavailable')
    payload = job['payload']
    if (job['source_address'] != call.source or payload.get('recipient') != call.recipient
            or payload.get('call') != call.sid or payload.get('turn') != turn):
        abort(403)
    config = channels.settings(container.storage, call.tenant)['phone']
    return _reply_to_phone_job(VoiceResponse(), call, job, turn, config, polls=polls)
