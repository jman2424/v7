"""Durable transactional application notices; never send private review notes."""
import atexit
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from html import escape
from threading import Event, Thread
from urllib.parse import urlencode

from service import business_applications as applications, registration_mail, session_store

_stop = Event()
_thread = None
_pid = None
SUBJECTS = {'PENDING_REVIEW': 'Your Vertex Seven Application',
            'APPROVED': 'Your Vertex Seven Application Has Been Approved',
            'NEEDS_INFORMATION': 'More information for your Vertex Seven application',
            'REJECTED': 'Your Vertex Seven application update',
            'EXPIRED': 'Your Vertex Seven application update'}


def render(payload, base_url, platform_tenant):
    owner = payload['owner']
    stage = payload['stage']
    url = base_url.rstrip('/') + '/console/' + ('applications?' if owner else 'application?') + urlencode(
        {'tenant': platform_tenant, 'application': payload['tenant']} if owner else {'tenant': payload['tenant']})
    if owner:
        subject = 'New Vertex Seven business application'
        submitted = datetime.fromtimestamp(payload['submitted'], timezone.utc).strftime('%d %b %Y, %H:%M UTC')
        body = (f"{payload['business_name']} has applied.\nWebsite: {payload['website'] or 'Not provided'}\n"
                f"Plan: {payload['plan_id'].title()}\nSubmitted: {submitted}\n\n"
                'Sign in to review the application. No decision has been made and no payment has been taken.')
    else:
        subject = SUBJECTS[stage]
        body = {
            'PENDING_REVIEW': "Thank you for applying to Vertex Seven. Your business application has been received and is awaiting review. We'll email you when there's an update.",
            'APPROVED': 'Your business has been approved to join Vertex Seven. You can now complete your subscription and set up your AI assistant. AI usage credit is separate.',
            'NEEDS_INFORMATION': 'Please provide the following business information through your signed-in application page:\n\n' + payload['public_message'],
            'REJECTED': 'We cannot offer services to your business under the current activity-based eligibility policy. You can correct your information or request reconsideration from your application page.',
            'EXPIRED': 'Your application is no longer current. Sign in to correct your information or request reconsideration.',
        }[stage]
    label = 'Review application' if owner else 'View your application'
    text = body + '\n\n' + label + ': ' + url + '\n\nVertex Seven\nSign-in and authenticator verification are required.\n'
    html = ('<!doctype html><html lang="en"><body style="margin:0;background:#f3f5f4;color:#18392f;font-family:Arial,sans-serif">'
            '<main style="max-width:560px;margin:24px auto;padding:24px;background:white;border-radius:12px">'
            '<p style="font-weight:bold">Vertex Seven</p><h1 style="font-size:23px">' + escape(subject) + '</h1>' +
            ''.join('<p style="line-height:1.6;white-space:pre-line">' + escape(part) + '</p>' for part in body.split('\n\n')) +
            '<p><a style="display:inline-block;background:#164536;color:white;padding:14px 18px;border-radius:8px" href="' +
            escape(url, quote=True) + '">' + label + '</a></p><p style="font-size:13px">Sign-in and authenticator verification are required.</p></main></body></html>')
    return subject, text, html


def process_one(container):
    now = time.time()
    with applications.database(write=True) as db:
        suffix = ' FOR UPDATE SKIP LOCKED' if session_store._using_postgres() else ''
        row = applications._one(applications._execute(db, "SELECT * FROM business_application_notifications "
            "WHERE state IN ('pending','processing') AND available<=? ORDER BY created,id LIMIT 1" + suffix, (now,)))
        if not row:
            return False
        # Resend keys expire after 24h. Never blindly re-send an uncertain mail
        # beyond that boundary; retain it for the operator to investigate.
        if row['attempts'] >= 8 or (row['attempts'] and row['created'] < now - 23 * 3600):
            applications._execute(db, "UPDATE business_application_notifications SET state='needs_review' WHERE id=?", (row['id'],))
            return True
        lease = now + 120
        applications._execute(db, "UPDATE business_application_notifications SET state='processing',attempts=attempts+1,available=? WHERE id=?", (lease, row['id']))
    try:
        payload = json.loads(row['payload'])
        if payload.get('task') == 'research':
            from service.application_research import process
            process(container, row['tenant'], payload['revision'])
        else:
            with applications.database(row['tenant']) as db:
                current = applications._one(applications._execute(db, 'SELECT revision FROM business_applications WHERE tenant=?', (row['tenant'],)))
            if not current or (not payload['owner'] and current['revision'] != payload['revision']):
                with applications.database(write=True) as db:
                    applications._execute(db, "UPDATE business_application_notifications SET state='superseded' WHERE id=? AND available=?", (row['id'], lease))
                return True
            subject, text, html = render(payload, container.settings.BASE_URL, container.settings.BUSINESS_KEY)
            registration_mail.send_transactional(payload['email'], subject, text, html,
                idempotency_key='v7-application-' + hashlib.sha256(row['id'].encode()).hexdigest())
        target, available = 'sent', now
    except Exception as exc:
        # Error class only; no email addresses, content, provider bodies or keys.
        from flask import current_app
        current_app.logger.warning('Application notification failed error_type=%s', type(exc).__name__)
        target, available = 'pending', now + min(3600, 30 * 2 ** row['attempts'])
    with applications.database(write=True) as db:
        applications._execute(db, 'UPDATE business_application_notifications SET state=?,available=? '
                              "WHERE id=? AND state='processing' AND available=?", (target, available, row['id'], lease))
    return True


def retention_once():
    from service import tenant_access
    with tenant_access._database() as db:
        tenant_access._schema(db)
        tenants = [row[0] for row in tenant_access._execute(db, 'SELECT tenant FROM managed_businesses')]
    for tenant in tenants:
        try:
            applications.purge_closed(tenant)
        except applications.ApplicationError:
            continue  # An unresolved payment always takes priority over purge.
    with applications.database(write=True) as db:
        applications._execute(db, "DELETE FROM business_application_notifications WHERE state IN ('sent','superseded') AND created<?", (time.time() - 30 * 86400,))


def start(app):
    global _thread, _pid
    if app.testing or os.getenv('V7_APPLICATION_WORKER', os.getenv('V7_CHANNEL_WORKER', 'false')) != 'true':
        return
    if _pid == os.getpid() and _thread and _thread.is_alive():
        return
    _pid = os.getpid()
    _stop.clear()
    def loop():
        maintenance_at = 0
        while not _stop.is_set():
            try:
                with app.app_context():
                    worked = process_one(app.container)
                    if time.time() >= maintenance_at:
                        retention_once()
                        maintenance_at = time.time() + 3600
            except Exception as exc:
                app.logger.warning('Application worker failed error_type=%s', type(exc).__name__)
                worked = False
            _stop.wait(0.2 if worked else 3)
    _thread = Thread(target=loop, daemon=True, name='v7-application-notifications')
    _thread.start()
    atexit.register(_stop.set)
