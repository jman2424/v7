"""Bounded Resend transport; no redirects, attachments or caller-chosen hosts."""
from __future__ import annotations

import base64
import binascii
from email.utils import parseaddr
from html.parser import HTMLParser
import hashlib
import hmac
from http.client import HTTPSConnection, HTTPException
import json
import re
import ssl
import time

from service.business_channels import address, resend_key


class EmailTransportError(RuntimeError):
    def __init__(self, code, *, uncertain=False):
        super().__init__(code)
        self.code, self.uncertain = code, uncertain


def verify(raw, headers, secret, *, now=None):
    """Svix raw-body HMAC, rotation signatures and five-minute replay window."""
    identifier, timestamp = headers.get('svix-id', ''), headers.get('svix-timestamp', '')
    signatures = headers.get('svix-signature', '')
    if (not isinstance(raw, bytes) or len(raw) > 65536 or not secret.startswith('whsec_')
            or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}', identifier)
            or not re.fullmatch(r'[0-9]{1,12}', timestamp) or len(signatures) > 4096):
        return False
    if abs((time.time() if now is None else now) - int(timestamp)) > 300:
        return False
    try:
        key = base64.b64decode(secret[6:] + '=' * (-len(secret[6:]) % 4), validate=True)
    except (ValueError, binascii.Error):
        return False
    if len(key) < 16:
        return False
    signed = (identifier + '.' + timestamp + '.').encode() + raw
    expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    return any(version == 'v1' and hmac.compare_digest(value, expected)
               for version, separator, value in (item.partition(',') for item in signatures.split()) if separator)


def _request(method, path, *, data=None, idempotency_key=None):
    key = resend_key()
    if not key:
        raise EmailTransportError('email_not_configured')
    headers = {'Authorization': 'Bearer '+key, 'Content-Type': 'application/json'}
    if idempotency_key:
        headers['Idempotency-Key'] = idempotency_key
    connection = HTTPSConnection('api.resend.com', timeout=10, context=ssl.create_default_context())
    try:
        connection.request(method, path, body=json.dumps(data).encode() if data is not None else None, headers=headers)
        response = connection.getresponse()
        raw = response.read(262145)
        if not 200 <= response.status < 300:
            raise EmailTransportError('email_provider_rejected', uncertain=method == 'POST' and response.status >= 500)
        if len(raw) > 262144:
            raise EmailTransportError('email_provider_response_invalid', uncertain=method == 'POST')
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError
        return result
    except EmailTransportError:
        raise
    except (OSError, HTTPException, ValueError, UnicodeError):
        raise EmailTransportError('email_provider_unavailable', uncertain=method == 'POST') from None
    finally:
        connection.close()


def receive(email_id):
    if not isinstance(email_id, str) or not re.fullmatch(r'[a-fA-F0-9-]{36}', email_id):
        raise EmailTransportError('invalid_email_id')
    return _request('GET', '/emails/receiving/'+email_id+'?html_format=cid')


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text, self.blocked = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style', 'blockquote', 'head'}:
            self.blocked += 1
        elif not self.blocked and tag in {'br', 'p', 'div', 'li'}:
            self.text.append('\n')

    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'blockquote', 'head'}:
            self.blocked = max(0, self.blocked-1)

    def handle_data(self, data):
        if not self.blocked:
            self.text.append(data)


def content(message, *, expected_sender, expected_recipient):
    """Untrusted envelope/headers do not establish account privileges or memory."""
    sender = address(parseaddr(message.get('from', ''))[1])
    recipients = message.get('to')
    if (sender != expected_sender or not isinstance(recipients, list)
            or expected_recipient not in [address(parseaddr(value)[1]) for value in recipients if isinstance(value, str)]):
        raise EmailTransportError('email_envelope_mismatch')
    headers = message.get('headers') or {}
    if not isinstance(headers, dict):
        raise EmailTransportError('invalid_email_headers')
    headers = {str(key).lower(): str(value) for key, value in headers.items()}
    automated = (headers.get('auto-submitted', 'no').lower() != 'no'
                 or bool(headers.get('list-id')) or headers.get('precedence', '').lower() in {'bulk', 'list', 'junk'}
                 or sender == expected_recipient or re.match(r'(?:mailer-daemon|postmaster|no-?reply)@', sender, re.I))
    subject = message.get('subject') or ''
    if not isinstance(subject, str) or len(subject) > 200 or any(char in subject for char in '\r\n\x00'):
        raise EmailTransportError('email_subject_invalid')
    text = message.get('text')
    if not isinstance(text, str) or not text.strip():
        html = message.get('html') or ''
        if not isinstance(html, str) or len(html) > 100000:
            raise EmailTransportError('email_body_too_large')
        parser = _Text()
        parser.feed(html)
        text = ''.join(parser.text)
    # The new reply text is the request. Quoted/forwarded instructions never
    # become trusted tool instructions or an authenticated conversation history.
    text = re.split(r'(?im)^On .{1,200}wrote:\s*$|^-{2,}\s*(?:Original|Forwarded) message\s*-*\s*$', text)[0]
    text = '\n'.join(line for line in text.splitlines() if not line.lstrip().startswith('>')).strip()
    if not text or len(text) > 4000 or '\x00' in text:
        raise EmailTransportError('email_body_needs_review')
    message_id = message.get('message_id') or ''
    if not isinstance(message_id, str) or len(message_id) > 998 or any(char in message_id for char in '\r\n\x00'):
        raise EmailTransportError('email_message_id_invalid')
    authentication = message.get('authentication') or {}
    return {'text': text, 'subject': subject, 'message_id': message_id,
            'automated': bool(automated), 'attachments': bool(message.get('attachments')),
            'sender_domain_authenticated': isinstance(authentication, dict) and authentication.get('dmarc') == 'pass'}


def send_reply(operation, reply):
    payload = operation['payload']
    sender, recipient = address(payload['recipient']), address(operation['source_address'])
    if sender == recipient or not isinstance(reply, str) or not reply.strip() or len(reply) > 6000:
        raise EmailTransportError('invalid_email_reply')
    subject = payload.get('subject') or 'Your enquiry'
    if not subject.lower().startswith('re:'):
        subject = 'Re: '+subject
    if len(subject) > 204 or any(char in subject for char in '\r\n\x00'):
        raise EmailTransportError('email_subject_invalid')
    headers = {'Auto-Submitted': 'auto-replied', 'X-Auto-Response-Suppress': 'All'}
    message_id = payload.get('message_id')
    if message_id:
        headers.update({'In-Reply-To': message_id, 'References': message_id})
    # Recipient, sender and headers come from verified/stored intake, never
    # from model output or the editable draft text.
    result = _request('POST', '/emails', data={'from': sender, 'to': [recipient], 'subject': subject,
        'text': reply, 'headers': headers}, idempotency_key='v7-reply-'+operation['id'])
    identifier = result.get('id')
    if not isinstance(identifier, str) or not 1 <= len(identifier) <= 200:
        raise EmailTransportError('email_provider_response_invalid', uncertain=True)
    return identifier
