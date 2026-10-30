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
    if event.get('type') != 'email.received':
        return jsonify(ok=True, ignored=True)
    data = event.get('data')
    if not isinstance(data, dict) or not isinstance(data.get('email_id'), str) or not _UUID.fullmatch(data['email_id']):
        abort(400)
    try:
        sender = channels.address(parseaddr(data.get('from', ''))[1])
        if (not isinstance(data.get('from'), str) or not isinstance(data.get('to'), list)
                or not 1 <= len(data['to']) <= 50 or any(not isinstance(value, str) for value in data['to'])):
            raise ValueError
        recipients = {channels.address(parseaddr(value)[1]) for value in data['to']}
    except (TypeError, ValueError):
        abort(400)
    routes = channels.bindings('email')
    matched = [(recipient, routes[recipient]) for recipient in recipients if recipient in routes]
    # A multi-tenant email cannot inherit one tenant's context by list order.
    if len(matched) != 1:
        return jsonify(ok=True, ignored=True)
    recipient, tenant = matched[0]
    container = get_container()
    if not container.storage.tenant_exists(tenant) or not channels.active(container.storage, tenant, 'email'):
        return jsonify(ok=True, ignored=True)
    config = channels.settings(container.storage, tenant)['email']
    try:
        job, created = operations.enqueue(tenant, 'email', data['email_id'],
            'email:'+hashlib.sha256((tenant+'\0'+data['email_id']).encode()).hexdigest(), sender,
            {'email_id': data['email_id'], 'recipient': recipient, 'mode_at_intake': config['mode']},
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


def _gather(response, tenant, call, turn, language, prompt=None):
    proof = _phone_signer().dumps({'tenant': tenant, 'call': call, 'turn': turn})
    gather = response.gather(input='speech', action='/channels/phone/turn?token='+proof,
                             method='POST', language=language, speech_timeout='auto', timeout=5)
    if prompt:
        gather.say(prompt, language=language)
    response.say('No input was received. Please contact the business using its website.', language=language)
    response.hangup()


@bp.post('/phone/incoming')
def phone_incoming():
    container, tenant, _, call, _ = _phone_context()
    config = channels.settings(container.storage, tenant)['phone']
    response = VoiceResponse()
    prompt = ('You are speaking to an AI assistant. Your words are transcribed and saved for this business. '
              'Please do not share passwords or payment information. How can we help?')
    if config['mode'] == 'review':
        prompt = ('This is an AI message-taking service. Your message will be transcribed and saved for the team. '
                  'Please say your enquiry and how you would like the team to contact you. Do not share passwords or payment information.')
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
    if type(turn) is not int or not 1 <= turn <= 12 or not text or len(text) > 4000 or '\x00' in text:
        abort(400)
    config = channels.settings(container.storage, tenant)['phone']
    response = VoiceResponse()
    try:
        job, _ = operations.enqueue(tenant, 'phone', call+':'+str(turn), 'phone:'+call, source,
            {'recipient': recipient, 'call': call, 'turn': turn, 'text': text, 'mode_at_intake': config['mode']},
            daily_limit=config['daily_limit'])
    except ValueError as exc:
        if str(exc) not in {'channel_daily_limit', 'channel_sender_limit', 'call_turn_limit'}:
            raise
        response.say('The automated service has reached its limit. Please contact the business using its website.', language=config['language'])
        response.hangup()
        return _xml(response)
    channel_worker.wake()
    if config['mode'] == 'review':
        response.say('Your message has been saved for the team to review. No booking or account change has been made. Thank you.', language=config['language'])
        response.hangup()
    else:
        poll = _phone_signer().dumps({'tenant': tenant, 'call': call, 'job': job['id'], 'turn': turn, 'poll': 0})
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
    if (job['state'] == 'completed' and job['reply'] and config['mode'] == 'automatic'
            and job['payload'].get('phone_reply_verified') is True):
        response.say(job['reply'], language=config['language'])
        if turn < 12:
            _gather(response, tenant, call, turn+1, config['language'])
        else:
            response.say('Please contact the team if you need further help.', language=config['language'])
            response.hangup()
    elif job['state'] in {'queued', 'processing'} and polls < 20:
        proof['poll'] = polls+1
        response.pause(length=1)
        response.redirect('/channels/phone/poll?token='+_phone_signer().dumps(proof), method='POST')
    else:
        if job['state'] in {'queued', 'processing'}:
            operations.expire_call_turn(tenant, job['id'])
        response.say('Your enquiry has been saved for the team to review. No booking or account change has been made.', language=config['language'])
        response.hangup()
    return _xml(response)
