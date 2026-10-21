"""Verification mail over authenticated TLS; never log codes or credentials."""
import json
import os
import re
import secrets
import time
import smtplib
import ssl
from http.client import HTTPSConnection, HTTPException
from email.message import EmailMessage
from email.utils import parseaddr


def _uses_resend_api():
    return (os.getenv('SMTP_HOST', '').strip().lower() == 'smtp.resend.com'
            and os.getenv('SMTP_USERNAME', '').strip().lower() == 'resend')


def configured():
    if not all(os.getenv(key, '').strip() for key in ('SMTP_HOST', 'SMTP_USERNAME', 'SMTP_PASSWORD', 'SMTP_FROM')):
        return False
    address = parseaddr(os.environ['SMTP_FROM'])[1]
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', address):
        return False
    if address.lower() == 'onboarding@resend.dev':
        return False
    reply_to = os.getenv('SMTP_REPLY_TO', '').strip()
    if reply_to and (any(character in reply_to for character in '\r\n')
                     or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', parseaddr(reply_to)[1])):
        return False
    if _uses_resend_api():
        return True
    mode = os.getenv('SMTP_TLS_MODE', 'starttls')
    if mode not in {'starttls', 'ssl'}:
        return False
    try:
        port = int(os.getenv('SMTP_PORT', '465' if mode == 'ssl' else '587'))
    except ValueError:
        return False
    return 1 <= port <= 65535


def sender_address():
    """Expose only the public From address, never SMTP credentials."""
    if not configured():
        return None
    return parseaddr(os.getenv('SMTP_FROM', ''))[1] or None


def send_code(email, code):
    _send(email, code, reset=False)


def send_reset_code(email, code):
    _send(email, code, reset=True)


def send_email_change_code(email, code):
    _send(email, code, reset=False, email_change=True)


def _send(email, code, *, reset, email_change=False):
    if not configured():
        raise RuntimeError('Email verification is not configured.')
    message = EmailMessage()
    message['From'] = os.environ['SMTP_FROM']
    message['To'] = email
    if os.getenv('SMTP_REPLY_TO', '').strip():
        message['Reply-To'] = os.environ['SMTP_REPLY_TO'].strip()
    message['Subject'] = 'Reset your V7 password' if reset else 'Verify your V7 account request'
    message.set_content((f'Your V7 password reset code is {code}. It expires in 10 minutes.\n\n'
                        'Enter it only in the V7 password reset page you opened. Do not share it. '
                        'Your authenticator will still be required after resetting your password. '
                        'If you did not request a reset, ignore this email; your password has not changed.') if reset else
                       (f'Your V7 verification code is {code}. It expires in 10 minutes.\n\n'
                        'Enter it only in the V7 signup page you opened. Do not share it. '
                        'If you did not request an account, ignore this email.'))
    if email_change:
        message.replace_header('Subject', 'Confirm your new V7 account email')
        message.set_content(f'Your V7 email change code is {code}. It expires in 10 minutes.\n\n'
                            'Enter it only in the signed-in V7 account page where you requested this change. '
                            'Do not share the code. Your password and authenticator will remain unchanged. '
                            'If you did not request this change, ignore this email.')
    if _uses_resend_api():
        content = {'from': message['From'], 'to': [email],
                   'subject': message['Subject'], 'text': message.get_content()}
        if message['Reply-To']:
            content['reply_to'] = message['Reply-To']
        payload = json.dumps(content).encode('utf-8')
        _send_resend(payload)
        return
    mode = os.getenv('SMTP_TLS_MODE', 'starttls')
    if mode not in {'starttls', 'ssl'}:
        raise RuntimeError('Invalid SMTP TLS mode.')
    port = int(os.getenv('SMTP_PORT', '465' if mode == 'ssl' else '587'))
    context = ssl.create_default_context()
    factory = smtplib.SMTP_SSL if mode == 'ssl' else smtplib.SMTP
    options = {'context': context} if mode == 'ssl' else {}
    with factory(os.environ['SMTP_HOST'], port, timeout=10, **options) as server:
        if mode == 'starttls':
            server.starttls(context=context)
        server.login(os.environ['SMTP_USERNAME'], os.environ['SMTP_PASSWORD'])
        server.send_message(message)


def _send_resend(payload):
    # Reuse the exact body/key for one bounded retry, including an uncertain
    # timeout after acceptance. Never retry certificate or permanent API errors.
    headers = {'Authorization': 'Bearer ' + os.environ['SMTP_PASSWORD'],
               'Content-Type': 'application/json', 'Idempotency-Key': secrets.token_urlsafe(32)}
    for attempt in range(2):
        if attempt:
            time.sleep(0.5)
        connection = HTTPSConnection('api.resend.com', timeout=10, context=ssl.create_default_context())
        try:
            connection.request('POST', '/emails', body=payload, headers=headers)
            response = connection.getresponse()
            if 500 <= response.status < 600 and attempt == 0:
                continue
            if not 200 <= response.status < 300:
                raise RuntimeError('Resend did not accept the verification email.')
            body = response.read(65537)
            if len(body) > 65536:
                raise RuntimeError('Resend returned an invalid email response.')
            try:
                result = json.loads(body)
            except (ValueError, UnicodeError) as exc:
                raise RuntimeError('Resend returned an invalid email response.') from exc
            if not isinstance(result, dict) or not isinstance(result.get('id'), str) or not result['id'].strip():
                raise RuntimeError('Resend returned an invalid email response.')
            return
        except ssl.SSLError:
            raise
        except (OSError, HTTPException):
            if attempt == 1:
                raise
        finally:
            connection.close()
