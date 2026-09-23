"""Verification mail over authenticated TLS; never log codes or credentials."""
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import parseaddr


def configured():
    return all(os.getenv(key, '').strip() for key in ('SMTP_HOST', 'SMTP_USERNAME', 'SMTP_PASSWORD', 'SMTP_FROM'))


def sender_address():
    """Expose only the public From address, never SMTP credentials."""
    if not configured():
        return None
    address = parseaddr(os.environ['SMTP_FROM'])[1]
    return address if re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', address) else None


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
