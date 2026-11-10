"""Durable customer-message jobs, driven in-process or by an explicit worker.

The queue survives restarts. Leases protect concurrent app instances. An
interrupted generation/send goes to review instead of silently repeating spend.
"""
from __future__ import annotations

import atexit
from functools import partial
import os
import secrets
from threading import Event, Lock, Thread
import time

from connectors import business_email
from service import business_channels as channels, business_operations as operations
from service.ai_disclosure import phone_copy
from service.channel_intelligence import navigation_targets, render_queued_reply

_lock, _stop = Lock(), Event()
_wake_events = {lane: Event() for lane in ('phone', 'background')}
_threads = {}
_retention_thread = None
_pid = None
_tenant_offsets = {'all': 0, 'phone': 0, 'background': 0}


def wake():
    for signal in _wake_events.values():
        signal.set()


def _shutdown():
    _stop.set()
    wake()


def _answer(container, job, text):
    tenant, channel = job['tenant'], job['channel']
    runtime = container.for_tenant(tenant)
    result = runtime.handler.handle(text, tenant=tenant, session_id=job['conversation_id'], channel=channel,
                                    metadata={'request_id': secrets.token_hex(12), 'source': 'business_channel'})

    def targets():
        original = runtime.handler.h_v7
        refresh = getattr(original, 'request_copy', None)
        v7 = refresh() if callable(refresh) else original
        return navigation_targets(v7, tenant)

    language = job.get('payload', {}).get('language')
    prompt = phone_copy(language, 'website_pages') if channel == 'phone' else None
    return render_queued_reply(result, channel, targets, phone_page_prompt=prompt)


def process_one(container, tenant, *, lane='all'):
    job = operations.claim(tenant, lane=lane)
    if job is None:
        return False
    identifier, lease, channel = job['id'], job['lease'], job['channel']
    sending = job['state'] == 'sending'
    try:
        if channel == 'workflow':
            operations.finish(tenant, identifier, lease, 'needs_review', error_code='manual_business_action')
            return True
        if not channels.active(container.storage, tenant, channel):
            operations.finish(tenant, identifier, lease, 'needs_review', reply=job['reply'], error_code='channel_disabled')
            return True
        current = channels.settings(container.storage, tenant)[channel]
        payload = job['payload']
        if channels.bindings(channel).get(payload['recipient']) != tenant:
            operations.finish(tenant, identifier, lease, 'needs_review', reply=job['reply'], error_code='channel_route_changed')
            return True
        if channel == 'email' and payload.get('inbox_id') and channels.inbox_bindings().get(payload['inbox_id']) != payload['recipient']:
            operations.finish(tenant, identifier, lease, 'needs_review', reply=job['reply'], error_code='channel_route_changed')
            return True
        if channel == 'email' and channels.email_senders().get(payload['recipient']) != payload.get('sending_address', payload['recipient']):
            operations.finish(tenant, identifier, lease, 'needs_review', reply=job['reply'], error_code='channel_sender_changed')
            return True
        if job['state'] == 'sending':
            # All sends use an immutable approved draft and one stable provider
            # idempotency key. Expired/ambiguous sends cannot be auto-retried.
            if channel != 'email' or time.time()-job['created'] > 23*3600:
                operations.finish(tenant, identifier, lease, 'uncertain', reply=job['reply'], error_code='send_window_expired')
                return True
            approval = payload.get('reply_approval')
            if approval != 'owner' and (approval == 'automatic' or payload.get('mode_at_intake') == 'automatic'):
                if (current['mode'] != 'automatic' or payload.get('inbox_id')
                        or not payload.get('sender_domain_authenticated') or payload.get('attachments')):
                    operations.finish(tenant, identifier, lease, 'needs_review', reply=job['reply'],
                                      error_code='reply_review_required')
                    return True
            provider_id = business_email.send_reply(job, job['reply'])
            operations.finish(tenant, identifier, lease, 'completed', reply=job['reply'], provider_id=provider_id)
            return True
        if channel == 'phone' and (current['mode'] == 'review' or payload.get('mode_at_intake') == 'review'):
            operations.finish(tenant, identifier, lease, 'needs_review', error_code=(
                'call_transcript_unclear' if payload.get('transcript_needs_review') is True else 'call_message_received'))
            return True
        if channel == 'phone' and time.time() - job['created'] >= operations.PHONE_REPLY_WINDOW:
            operations.finish(tenant, identifier, lease, 'needs_review', error_code='call_reply_timed_out')
            return True
        if channel == 'email':
            if payload.get('restore_thread'):
                business_email.restore_thread(payload['inbox_id'], payload['thread_id'])
            message = (business_email.receive_inbox(payload['inbox_id'], payload['thread_id'], payload['email_id'])
                       if payload.get('inbox_id') else business_email.receive(payload['email_id']))
            clean = business_email.content(message, expected_sender=job['source_address'],
                                           expected_recipient=payload['recipient'], routed_recipients=channels.bindings('email'))
            payload = {**payload, **clean}
            # No raw headers, HTML, attachments, download URLs or credentials.
            if not operations.save_payload(tenant, identifier, lease, payload):
                return True
            job['payload'] = payload
            if clean['automated']:
                operations.finish(tenant, identifier, lease, 'rejected', error_code='automated_email_skipped')
                return True
            text = business_email.question_text(clean)
        else:
            text = payload['text']
        answer, routine = _answer(container, job, text)
        # Recheck grants/mode/routing after inference. A concurrent owner/operator
        # change must take effect before a reply is sent or spoken.
        enabled = channels.active(container.storage, tenant, channel)
        latest = channels.settings(container.storage, tenant)[channel]
        automatic = (enabled and current['mode'] == latest['mode'] == payload.get('mode_at_intake') == 'automatic'
                     and routine and channels.bindings(channel).get(payload['recipient']) == tenant)
        if channel == 'email':
            automatic = (automatic and not payload.get('inbox_id')
                         and payload['sender_domain_authenticated'] and not payload['attachments'])
            state = 'approved' if automatic else 'needs_review'
            operations.finish(tenant, identifier, lease, state, reply=answer,
                              error_code='' if automatic else 'reply_review_required',
                              payload={**payload, 'reply_approval': 'automatic'} if automatic else None)
        else:
            timed_out = time.time() - job['created'] >= operations.PHONE_REPLY_WINDOW
            state = 'completed' if automatic and not timed_out and len(answer) <= 1400 else 'needs_review'
            error = 'call_reply_timed_out' if timed_out else 'call_followup_required'
            operations.finish(tenant, identifier, lease, state, reply=answer,
                              error_code='' if state == 'completed' else error,
                              payload={**payload, 'phone_reply_verified': True} if state == 'completed' else None)
    except business_email.EmailTransportError as exc:
        operations.finish(tenant, identifier, lease, 'uncertain' if exc.uncertain else 'needs_review',
                          reply=job['reply'], error_code=exc.code)
    except Exception as exc:
        # Never record provider exception bodies, caller text or credentials.
        from service.chat_diagnostics import emit
        emit('chat_optional_failure', phase='business_channel', error_type=type(exc).__name__)
        # A database error after provider acceptance must never turn an
        # ambiguous send back into an editable/resendable draft.
        safe_codes = {'channel_invalid_answer': 'channel_invalid_answer',
                      'channel_unapproved_link': 'channel_unapproved_link',
                      'channel_invalid_agent': 'channel_invalid_agent',
                      'channel_answer_too_long': 'channel_answer_too_long'}
        code = safe_codes.get(str(exc), 'channel_processing_failed') if type(exc) is ValueError else 'channel_processing_failed'
        operations.finish(tenant, identifier, lease, 'uncertain' if sending else 'needs_review',
                          reply=job['reply'], error_code=code)
    return True


def run_pending(container, limit=20, *, tenants=None, lane='all'):
    count = 0
    # A bounded share per tenant prevents one busy inbox monopolising a pass.
    tenants = channels.configured_tenants() if tenants is None else list(tenants)
    if not tenants:
        return 0
    process = process_one if lane == 'all' else partial(process_one, lane=lane)
    start = _tenant_offsets[lane] % len(tenants)
    for index in range(len(tenants)):
        tenant = tenants[(start+index) % len(tenants)]
        try:
            for _ in range(2):
                if count >= limit or not process(container, tenant):
                    break
                count += 1
        except Exception as exc:
            from service.chat_diagnostics import emit
            emit('chat_optional_failure', phase='business_channel_tenant', error_type=type(exc).__name__)
        _tenant_offsets[lane] = (start+index+1) % len(tenants)
        if count >= limit:
            break
    return count


def run_retention(container, *, tenants=None, provider_cleanup=True):
    from service.business_email_retention import run as cleanup_email
    count = 0
    for tenant in channels.configured_tenants() if tenants is None else tenants:
        try:
            if provider_cleanup:
                cleanup_email(container, tenant)
            else:
                operations.recover_cleanup(tenant)
            for channel in channels.CHANNELS:
                config = channels.settings(container.storage, tenant)[channel]
                count += operations.purge(tenant, channel, config['retention_days'])
        except Exception as exc:
            from service.chat_diagnostics import emit
            emit('chat_optional_failure', phase='channel_retention', error_type=type(exc).__name__)
    return count


def start(app):
    global _retention_thread, _pid
    if os.getenv('V7_CHANNEL_WORKER', 'false') != 'true' or app.testing:
        return
    with _lock:
        if (_pid == os.getpid() and all(lane in _threads and _threads[lane].is_alive() for lane in _wake_events)
                and _retention_thread and _retention_thread.is_alive()):
            return
        if _pid != os.getpid():
            _threads.clear()
            atexit.register(_shutdown)
        _pid = os.getpid()
        _stop.clear()
        def loop(lane, signal):
            while not _stop.is_set():
                signal.clear()
                try:
                    with app.app_context():
                        run_pending(app.container, lane=lane)
                except Exception as exc:
                    app.logger.warning('Business channel worker failed (%s)', type(exc).__name__)
                signal.wait(3)
        for lane, signal in _wake_events.items():
            if lane not in _threads or not _threads[lane].is_alive():
                _threads[lane] = Thread(target=loop, args=(lane, signal), name=f'v7-channel-{lane}', daemon=True)
                _threads[lane].start()
        def retention_loop():
            while not _stop.is_set():
                try:
                    with app.app_context():
                        run_retention(app.container)
                except Exception as exc:
                    app.logger.warning('Channel retention worker failed (%s)', type(exc).__name__)
                _stop.wait(300)
        if not _retention_thread or not _retention_thread.is_alive():
            _retention_thread = Thread(target=retention_loop, name='v7-channel-retention', daemon=True)
            _retention_thread.start()


if __name__ == '__main__':
    import argparse
    from app import create_app
    parser = argparse.ArgumentParser(description='Run V7 durable channel work or content retention once.')
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--once', action='store_true')
    choice.add_argument('--purge-only', action='store_true')
    choice.add_argument('--retention-once', action='store_true')
    parser.add_argument('--tenant', help='Explicit existing tenant for maintenance, including a removed provider route.')
    args = parser.parse_args()
    app = create_app()
    with app.app_context():
        tenants = channels.configured_tenants()
        if args.tenant:
            tenant = app.container.storage.validate_tenant_key(args.tenant)
            if not app.container.storage.tenant_exists(tenant):
                parser.error('Unknown maintenance tenant')
            tenants = [tenant]
        if args.once:
            print('Processed operations:', run_pending(app.container, tenants=tenants))
        else:
            print('Removed message content:', run_retention(app.container, tenants=tenants,
                                                            provider_cleanup=args.retention_once))
