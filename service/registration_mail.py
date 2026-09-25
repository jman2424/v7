"""Verification mail over authenticated TLS; never log codes or credentials."""
import json
import os
import re
import smtplib
import ssl
from http.client import HTTPSConnection
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
    if not configured():
        raise RuntimeError('Email verification is not configured.')
    message = EmailMessage()
    message['From'] = os.environ['SMTP_FROM']
    message['To'] = email
    message['Subject'] = 'Verify your V7 account request'
    message.set_content(f'Your V7 verification code is {code}. It expires in 10 minutes.\n\n'
                        'Enter it only in the V7 signup page you opened. Do not share it. '
                        'If you did not request an account, ignore this email.')
    if _uses_resend_api():
        payload = json.dumps({'from': message['From'], 'to': [email],
                              'subject': message['Subject'], 'text': message.get_content()}).encode('utf-8')
        connection = HTTPSConnection('api.resend.com', timeout=10, context=ssl.create_default_context())
        try:
            connection.request('POST', '/emails', body=payload, headers={
                'Authorization': 'Bearer ' + os.environ['SMTP_PASSWORD'],
                'Content-Type': 'application/json',
            })
            response = connection.getresponse()
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
        finally:
            connection.close()
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
