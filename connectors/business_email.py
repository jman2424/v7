"""Bounded Resend transport; no redirects, attachments or caller-chosen hosts."""
from __future__ import annotations

import base64
import binascii
from collections.abc import Collection
from email.errors import HeaderParseError
from email.headerregistry import HeaderRegistry
from html.parser import HTMLParser
import hashlib
import hmac
from http.client import HTTPSConnection, HTTPException
import json
import re
import ssl
import time
from typing import Any

from service.business_channels import address, resend_key, UUID
from service.ai_disclosure import email_reply


_MAILBOX_HEADER = HeaderRegistry()
_QUESTION_LIMIT = 4000
_BODY_LIMIT = 100000
_REPLY_PREFIX = re.compile(r'^(?:(?:re|fw|fwd|aw|wg|tr)\s*:\s*)+', re.I)
_FORWARDED_SEPARATOR = re.compile(r'-{2,}\s*(?:original|forwarded) message\s*-*', re.I)
_EMPTY_SUBJECTS = {'no subject', '(no subject)', '[no subject]', '<no subject>'}
_HIDDEN_TAGS = {'blockquote', 'head', 'script', 'style', 'template', 'title'}
_VOID_TAGS = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta',
              'param', 'source', 'track', 'wbr'}
_QUOTE_CLASSES = {'gmail_quote', 'gmail_attr', 'moz-cite-prefix', 'yahoo_quoted'}
_HIDDEN_STYLE = re.compile(r'(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden)\b', re.I)
_REFERENCE_ATOM = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
                            "!#$%&'*+-/=?^_`{|}~.")
_REFERENCE_DOMAIN = frozenset('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.-')


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


def _request(method, path, *, data=None, idempotency_key=None, api_key=None):
    key = resend_key() if api_key is None else api_key
    if not isinstance(key, str) or not key:
        raise EmailTransportError('email_not_configured')
    headers = {'Authorization': 'Bearer '+key, 'Content-Type': 'application/json',
               'User-Agent': 'VertexSeven/1.0 business-channels'}
    if idempotency_key:
        headers['Idempotency-Key'] = idempotency_key
    connection = HTTPSConnection('api.resend.com', timeout=10, context=ssl.create_default_context())
    try:
        connection.request(method, path, body=json.dumps(data).encode() if data is not None else None, headers=headers)
        response = connection.getresponse()
        raw = response.read(262145)
        if not 200 <= response.status < 300:
            # A conflicting write can already be in progress at Resend.
            uncertain = method != 'GET' and (response.status == 409 or response.status >= 500)
            raise EmailTransportError('email_provider_rejected', uncertain=uncertain)
        if len(raw) > 262144:
            raise EmailTransportError('email_provider_response_invalid', uncertain=method != 'GET')
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError
        return result
    except EmailTransportError:
        raise
    except (OSError, HTTPException, ValueError, UnicodeError):
        raise EmailTransportError('email_provider_unavailable', uncertain=method != 'GET') from None
    finally:
        connection.close()


def receive(email_id):
    if not isinstance(email_id, str) or not UUID.fullmatch(email_id):
        raise EmailTransportError('invalid_email_id')
    result = _request('GET', '/emails/receiving/'+email_id+'?html_format=cid')
    if result.get('id') != email_id:
        raise EmailTransportError('email_envelope_mismatch')
    return result


def receive_inbox(inbox_id, thread_id, email_id):
    if any(not isinstance(value, str) or not UUID.fullmatch(value) for value in (inbox_id, thread_id, email_id)):
        raise EmailTransportError('invalid_email_id')
    result = _request('GET', '/inboxes/'+inbox_id+'/threads/'+thread_id+'/emails/'+email_id)
    if result.get('id') != email_id or result.get('direction') != 'inbound':
        raise EmailTransportError('email_envelope_mismatch')
    # Inbox API currently documents no provider-authenticated DMARC result or
    # raw loop headers. Never invent that evidence from email-owned fields.
    return {**result, 'authentication': {}, 'headers': {}}


def thread_path(inbox_id, thread_id):
    if any(not isinstance(value, str) or not UUID.fullmatch(value) for value in (inbox_id, thread_id)):
        raise EmailTransportError('invalid_email_id')
    return '/inboxes/'+inbox_id+'/threads/'+thread_id


def thread_emails(inbox_id, thread_id):
    result = _request('GET', thread_path(inbox_id, thread_id)+'/emails?limit=100')
    if result.get('has_more') is not False or not isinstance(result.get('data'), list) or not 1 <= len(result['data']) <= 100:
        raise EmailTransportError('email_cleanup_needs_review')
    return result['data']


def restore_thread(inbox_id, thread_id):
    result = _request('PATCH', thread_path(inbox_id, thread_id), data={'folder': 'inbox'})
    if result.get('id') != thread_id or result.get('folder') != 'inbox':
        raise EmailTransportError('email_thread_restore_failed', uncertain=True)


def trash_thread(inbox_id, thread_id):
    result = _request('DELETE', thread_path(inbox_id, thread_id))
    if result.get('id') != thread_id or type(result.get('deleted')) is not bool:
        raise EmailTransportError('email_cleanup_outcome_unknown', uncertain=True)


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self.blocked_tags = []
        self.past_reply_boundary = False
        self.saw_quoted_content = False

    def handle_starttag(self, tag, attrs):
        if self.past_reply_boundary:
            return
        if self.blocked_tags:
            if tag not in _VOID_TAGS:
                self.blocked_tags.append(tag)
            return
        attributes = dict(attrs)
        if (attributes.get('id') or '').casefold() == 'divrplyfwdmsg':
            self.past_reply_boundary = True
            self.saw_quoted_content = True
            return
        classes = (attributes.get('class') or '').casefold().split()
        quoted = tag == 'blockquote' or bool(_QUOTE_CLASSES.intersection(classes))
        if quoted:
            self.saw_quoted_content = True
        if (tag in _HIDDEN_TAGS or quoted or 'hidden' in attributes
                or (attributes.get('aria-hidden') or '').casefold() == 'true'
                or _HIDDEN_STYLE.search(attributes.get('style') or '')):
            if tag not in _VOID_TAGS:
                self.blocked_tags.append(tag)
        elif tag in {'br', 'p', 'div', 'li'}:
            self.text.append('\n')

    def handle_endtag(self, tag):
        if self.blocked_tags and self.blocked_tags[-1] == tag:
            self.blocked_tags.pop()

    def handle_data(self, data):
        if not self.blocked_tags and not self.past_reply_boundary:
            self.text.append(data)


def _mailbox(value: object) -> str:
    if (not isinstance(value, str) or not 1 <= len(value) <= 512
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise EmailTransportError('email_envelope_mismatch')
    try:
        header: Any = _MAILBOX_HEADER('To', value)
        if header.defects or len(header.addresses) != 1 or any(group.display_name for group in header.groups):
            raise ValueError
        return address(header.addresses[0].addr_spec)
    except (ValueError, HeaderParseError, IndexError, RecursionError):
        raise EmailTransportError('email_envelope_mismatch') from None


def envelope(message: dict) -> tuple[str, set[str]]:
    """Normalize one sender and bounded recipients identically at intake and retrieval."""
    recipients = message.get('to')
    if not isinstance(recipients, list) or not 1 <= len(recipients) <= 50:
        raise EmailTransportError('email_envelope_mismatch')
    return _mailbox(message.get('from')), {_mailbox(value) for value in recipients}


def _message_reference(value: object) -> str:
    """Use one bounded message identifier when the provider supplies a valid one."""
    if (not isinstance(value, str) or not 5 <= len(value) <= 998
            or not value.startswith('<') or not value.endswith('>')):
        return ''
    left, separator, right = value[1:-1].partition('@')
    if (separator and all(part and not part.startswith('.') and not part.endswith('.') and '..' not in part
                          for part in (left, right)) and all(char in _REFERENCE_ATOM for char in left)
            and all(char in _REFERENCE_DOMAIN for char in right)):
        return value
    return ''


def _current_body(value: str) -> str:
    lines = value.splitlines()
    current: list[str] = []
    for position, line in enumerate(lines):
        stripped = line.strip()
        if line == '-- ' or _FORWARDED_SEPARATOR.fullmatch(stripped):
            break
        if stripped.casefold().startswith('on ') and not stripped.endswith(('?', '!')):
            if stripped.casefold().endswith('wrote:'):
                break
            for continuation in lines[position+1:position+3]:
                part = continuation.strip().casefold()
                if not part or part.startswith(('on ', '>')):
                    break
                if part.endswith('wrote:'):
                    return '\n'.join(current).strip()
        if not stripped.startswith('>'):
            current.append(line.rstrip())
    return '\n'.join(current).strip()


def question_text(clean: dict) -> str:
    """Choose the new enquiry within the shared handler's input limit."""
    body = clean['text']
    raw_subject = clean['subject'].strip()
    subject = _REPLY_PREFIX.sub('', raw_subject).strip()
    if subject.casefold() in _EMPTY_SUBJECTS or not any(char.isalnum() for char in subject):
        subject = ''
    if not body:
        if subject and subject == raw_subject and not clean.get('previous_content_only'):
            return subject
        raise EmailTransportError('email_body_needs_review')
    if len(body) > _QUESTION_LIMIT:
        raise EmailTransportError('email_body_needs_review')
    if subject and ' '.join(subject.split()).casefold() != ' '.join(body.split()).casefold():
        combined = f'Subject: {subject}\n\n{body}'
        if len(combined) <= _QUESTION_LIMIT:
            return combined
    return body


def content(message, *, expected_sender, expected_recipient, routed_recipients: Collection[str] = ()):
    """Extract a current enquiry and bind it to the signed intake envelope."""
    sender, recipients = envelope(message)
    routed = recipients.intersection(routed_recipients)
    if (sender != expected_sender or expected_recipient not in recipients
            or routed - {expected_recipient}):
        raise EmailTransportError('email_envelope_mismatch')
    headers = message.get('headers') or {}
    if not isinstance(headers, dict):
        raise EmailTransportError('invalid_email_headers')
    headers = {str(key).lower(): str(value) for key, value in headers.items()}
    automated = (headers.get('auto-submitted', 'no').lower() != 'no'
                 or bool(headers.get('list-id')) or headers.get('precedence', '').lower() in {'bulk', 'list', 'junk'}
                 or sender == expected_recipient or re.match(r'(?:mailer-daemon|postmaster|no-?reply)@', sender, re.I))
    subject = message.get('subject') or ''
    if (not isinstance(subject, str) or len(subject) > 200
            or any(ord(char) < 32 or ord(char) == 127 for char in subject)):
        raise EmailTransportError('email_subject_invalid')
    text = message.get('text')
    if not isinstance(text, str) or not text.strip():
        html = message.get('html') or ''
        if not isinstance(html, str) or len(html) > _BODY_LIMIT:
            raise EmailTransportError('email_body_too_large')
        parser = _Text()
        parser.feed(html)
        parser.close()
        text = ''.join(parser.text)
        previous_content_only = parser.saw_quoted_content and not text.strip()
    else:
        previous_content_only = False
    if len(text) > _BODY_LIMIT:
        raise EmailTransportError('email_body_too_large')
    if '\x00' in text:
        raise EmailTransportError('email_body_needs_review')
    current = _current_body(text)
    if len(current) > _QUESTION_LIMIT:
        raise EmailTransportError('email_body_needs_review')
    previous_content_only = previous_content_only or bool(text.strip() and not current)
    authentication = message.get('authentication') or {}
    clean = {'text': current, 'subject': subject, 'message_id': _message_reference(message.get('message_id')),
             'automated': bool(automated), 'attachments': bool(message.get('attachments')),
             'sender_domain_authenticated': isinstance(authentication, dict) and authentication.get('dmarc') == 'pass'}
    if previous_content_only:
        clean['previous_content_only'] = True
    return clean


def send_reply(operation, reply):
    payload = operation['payload']
    sender = address(payload.get('sending_address', payload['recipient']))
    recipient = address(operation['source_address'])
    if sender == recipient or not isinstance(reply, str) or not reply.strip() or len(reply) > 6000 or '\x00' in reply:
        raise EmailTransportError('invalid_email_reply')
    subject = payload.get('subject') or 'Your enquiry'
    if (not isinstance(subject, str) or len(subject) > 200
            or any(ord(char) < 32 or ord(char) == 127 for char in subject)):
        raise EmailTransportError('email_subject_invalid')
    subject = subject.strip() or 'Your enquiry'
    if not subject.lower().startswith('re:'):
        subject = 'Re: '+subject
    headers = {'Auto-Submitted': 'auto-replied', 'X-Auto-Response-Suppress': 'All'}
    message_id = _message_reference(payload.get('message_id'))
    if message_id:
        headers.update({'In-Reply-To': message_id, 'References': message_id})
    # Recipient, sender and headers come from verified/stored intake, never
    # from model output or the editable draft text.
    result = _request('POST', '/emails', data={'from': sender, 'to': [recipient], 'subject': subject,
        'text': email_reply(reply), 'headers': headers}, idempotency_key='v7-reply-'+operation['id'])
    identifier = result.get('id')
    if not isinstance(identifier, str) or not 1 <= len(identifier) <= 200:
        raise EmailTransportError('email_provider_response_invalid', uncertain=True)
    return identifier
