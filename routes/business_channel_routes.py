"""Signed provider intake. No inbound field can grant a role or select a tenant."""
from __future__ import annotations

from email.utils import parseaddr
import hashlib
import hmac
import json
import os
import re

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
_UUID = re.compile(r'[a-fA-F0-9-]{36}\Z')


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
    if not isinstance(data, dict) or not isinstance(data.get('email_id'), str) or not _UUID.fullmatch(data['email_id']):
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
        sender = channels.address(parseaddr(metadata.get('from', ''))[1])
        if (not isinstance(metadata.get('from'), str) or not isinstance(metadata.get('to'), list)
                or not 1 <= len(metadata['to']) <= 50 or any(not isinstance(value, str) for value in metadata['to'])):
            raise ValueError
        recipients = {channels.address(parseaddr(value)[1]) for value in metadata['to']}
    except (TypeError, ValueError):
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
    if not token or not account or not channels.bindings('phone'):
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
    tenant = channels.bindings('phone').get(called)
    if not tenant or not _SID.fullmatch(call) or not container.storage.tenant_exists(tenant):
        abort(403)
    source = request.form.get('From', '')
    if not channels.PHONE.fullmatch(source):
        source = 'anonymous'
    if not channels.active(container.storage, tenant, 'phone'):
        abort(503)
    return container, tenant, called, call, source


def _xml(response):
    return Response(str(response), content_type='application/xml; charset=utf-8')


def _gather(response, tenant, call, turn, language, prompt=None, *, silence=0, handoff=False):
    proof = _phone_signer().dumps({'tenant': tenant, 'call': call, 'turn': turn,
                                 'silence': silence, 'handoff': handoff})
    gather = response.gather(input='speech dtmf', action='/channels/phone/turn?token='+proof,
                             method='POST', language=language, speech_timeout='auto', timeout=5,
                             num_digits=1, action_on_empty_result=True)
    if prompt:
        gather.say(prompt, language=language)
    response.say(phone_copy(language, 'silent'), language=language)
    response.hangup()


@bp.post('/phone/incoming')
def phone_incoming():
    container, tenant, _, call, _ = _phone_context()
    config = channels.settings(container.storage, tenant)['phone']
    response = VoiceResponse()
    language = config['language']
    # Identification plays before Gather so barge-in cannot skip the notice.
    response.say(phone_copy(language, config['mode']), language=language)
    prompt = phone_copy(language, 'message' if config['mode'] == 'review' else 'question')
    _gather(response, tenant, call, 1, config['language'], prompt)
    return _xml(response)


def _proof(tenant, call):
    try:
        proof = _phone_signer().loads(request.args.get('token', ''), max_age=1800)
    except BadSignature:
        abort(403)
    if not isinstance(proof, dict) or proof.get('tenant') != tenant or proof.get('call') != call:
        abort(403)
    return proof


@bp.post('/phone/turn')
def phone_turn():
    container, tenant, recipient, call, source = _phone_context()
    proof = _proof(tenant, call)
    turn, text = proof.get('turn'), request.form.get('SpeechResult', '').strip()
    silence, handoff = proof.get('silence', 0), proof.get('handoff', False)
    digits = request.form.get('Digits', '')
    if (type(turn) is not int or not 1 <= turn <= 12 or len(text) > 4000 or '\x00' in text
            or type(silence) is not int or not 0 <= silence <= 1 or type(handoff) is not bool
            or digits and text):
        abort(400)
    config = channels.settings(container.storage, tenant)['phone']
    response = VoiceResponse()
    language = config['language']
    if digits == '0' and not handoff:
        _gather(response, tenant, call, turn, language, phone_copy(language, 'message'), handoff=True)
        return _xml(response)
    if not text or digits:
        if silence == 0:
            _gather(response, tenant, call, turn, language, phone_copy(language, 'retry'),
                    silence=1, handoff=handoff)
        else:
            response.say(phone_copy(language, 'silent'), language=language)
            response.hangup()
        return _xml(response)
    review = config['mode'] == 'review' or handoff
    try:
        job, _ = operations.enqueue(tenant, 'phone', call+':'+str(turn), 'phone:'+call, source,
            {'recipient': recipient, 'call': call, 'turn': turn, 'text': text,
             'mode_at_intake': 'review' if review else config['mode']},
            daily_limit=config['daily_limit'])
    except ValueError as exc:
        if str(exc) not in {'channel_daily_limit', 'channel_sender_limit', 'call_turn_limit'}:
            raise
        response.say(phone_copy(language, 'limit'), language=language)
        response.hangup()
        return _xml(response)
    channel_worker.wake()
    if review:
        response.say(phone_copy(language, 'saved'), language=language)
        response.hangup()
    else:
        poll = _phone_signer().dumps({'tenant': tenant, 'call': call, 'job': job['id'], 'turn': turn, 'poll': 0})
        response.say(phone_copy(language, 'waiting'), language=language)
        response.pause(length=1)
        response.redirect('/channels/phone/poll?token='+poll, method='POST')
    return _xml(response)


@bp.post('/phone/poll')
def phone_poll():
    container, tenant, _, call, _ = _phone_context()
    proof = _proof(tenant, call)
    try:
        job = operations.get(tenant, proof.get('job'))
    except ValueError:
        abort(403)
    if not job or job['conversation_id'] != 'phone:'+call or job['channel'] != 'phone':
        abort(403)
    response = VoiceResponse()
    config = channels.settings(container.storage, tenant)['phone']
    polls, turn = proof.get('poll'), proof.get('turn')
    if type(polls) is not int or not 0 <= polls <= 20 or type(turn) is not int or not 1 <= turn <= 12:
        abort(403)
    if job['payload'].get('call') != call or job['payload'].get('turn') != turn:
        abort(403)
    if (job['state'] == 'completed' and job['reply'] and config['mode'] == 'automatic'
            and job['payload'].get('mode_at_intake') == 'automatic'
            and job['payload'].get('phone_reply_verified') is True):
        response.say(job['reply'], language=config['language'])
        if turn < 12:
            _gather(response, tenant, call, turn+1, config['language'])
        else:
            response.say(phone_copy(config['language'], 'end'), language=config['language'])
            response.hangup()
    elif job['state'] in {'queued', 'processing'} and polls < 20:
        proof['poll'] = polls+1
        response.pause(length=1)
        response.redirect('/channels/phone/poll?token='+_phone_signer().dumps(proof), method='POST')
    else:
        if job['state'] in {'queued', 'processing'}:
            operations.expire_call_turn(tenant, job['id'])
        response.say(phone_copy(config['language'], 'followup'), language=config['language'])
        response.hangup()
    return _xml(response)
