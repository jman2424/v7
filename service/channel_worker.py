"""Durable customer-message jobs, driven in-process or by an explicit worker.

The queue survives restarts. Leases protect concurrent app instances. An
interrupted generation/send goes to review instead of silently repeating spend.
"""
from __future__ import annotations

import atexit
import os
import re
import secrets
from threading import Event, Lock, Thread
import time

from connectors import business_email
from service import business_channels as channels, business_operations as operations

_lock, _wake, _stop = Lock(), Event(), Event()
_thread = None
_pid = None
_tenant_offset = 0


def wake():
    _wake.set()


def _answer(container, job, text):
    tenant, channel = job['tenant'], job['channel']
    runtime = container.for_tenant(tenant)
    result = runtime.handler.handle(text, tenant=tenant, session_id=job['conversation_id'], channel=channel,
                                    metadata={'request_id': secrets.token_hex(12), 'source': 'business_channel'})
    if not isinstance(result, dict):
        raise ValueError('channel_invalid_answer')
    answer = result.get('reply')
    if not isinstance(answer, str) or not answer.strip() or len(answer) > 6000 or '\x00' in answer:
        raise ValueError('channel_invalid_answer')
    if re.search(r'https?://|mailto:|tel:', answer, re.I):
        raise ValueError('channel_unapproved_link')
    agent = result.get('agent') or {}
    if not isinstance(agent, dict):
        raise ValueError('channel_invalid_agent')
    verified = isinstance(agent, dict) and agent.get('_validated_grounded') is True
    # Preserve existing deterministic salutations/boundaries. This does not
    # bless an extractive FAQ, price, policy, memory recall or model fallback.
    local_conversation = (result.get('intent') in {'greeting', 'smalltalk', 'out_of_scope'}
                          and not re.search(r'https?://|[£$€%]|\d', answer))
    routine = ((verified or local_conversation) and agent.get('intent') not in {'book', 'quote', 'checkout', 'handoff', 'cancel', 'complaint'}
               and not agent.get('requested_action')
               and agent.get('next_action') not in {'open_request_form', 'request_handoff'})
    if channel == 'email' and verified:
        # Use current approved page records, never model-written URLs/recipients.
        from service.website_destinations import public_targets
        from service.platform_offer_knowledge import public_destinations
        original = runtime.handler.h_v7
        refresh = getattr(original, 'request_copy', None)
        v7 = refresh() if callable(refresh) else original
        targets = public_targets(v7.website_destinations, v7.website_knowledge, v7.business_profile.get('website', ''))
        targets += public_destinations(tenant, v7.website_destinations)
        chosen = set(agent.get('navigation_ids') or [])
        links = [row['label']+': '+row['url'] for row in targets if row['id'] in chosen][:3]
        if links:
            answer += '\n\n'+'\n'.join(dict.fromkeys(links))
    if len(answer) > 6000:
        raise ValueError('channel_answer_too_long')
    return answer, routine


def process_one(container, tenant):
    job = operations.claim(tenant)
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
        if job['state'] == 'sending':
            # All sends use an immutable approved draft and one stable provider
            # idempotency key. Expired/ambiguous sends cannot be auto-retried.
            if channel != 'email' or time.time()-job['created'] > 23*3600:
                operations.finish(tenant, identifier, lease, 'uncertain', reply=job['reply'], error_code='send_window_expired')
                return True
            provider_id = business_email.send_reply(job, job['reply'])
            operations.finish(tenant, identifier, lease, 'completed', reply=job['reply'], provider_id=provider_id)
            return True
        if channel == 'phone' and current['mode'] == 'review':
            operations.finish(tenant, identifier, lease, 'needs_review', error_code='call_message_received')
            return True
        if channel == 'email':
            message = business_email.receive(payload['email_id'])
            clean = business_email.content(message, expected_sender=job['source_address'], expected_recipient=payload['recipient'])
            payload = {**payload, **clean}
            # No raw headers, HTML, attachments, download URLs or credentials.
            if not operations.save_payload(tenant, identifier, lease, payload):
                return True
            job['payload'] = payload
            if clean['automated']:
                operations.finish(tenant, identifier, lease, 'rejected', error_code='automated_email_skipped')
                return True
            text = ('Subject: '+clean['subject']+'\n\n' if clean['subject'] else '')+clean['text']
            if len(text) > 4000:
                operations.finish(tenant, identifier, lease, 'needs_review', error_code='email_body_needs_review')
                return True
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
            automatic = automatic and payload['sender_domain_authenticated'] and not payload['attachments']
            state = 'approved' if automatic else 'needs_review'
            operations.finish(tenant, identifier, lease, state, reply=answer,
                              error_code='' if automatic else 'reply_review_required')
        else:
            state = 'completed' if automatic and len(answer) <= 1400 else 'needs_review'
            if state == 'completed' and not operations.save_payload(tenant, identifier, lease,
                    {**payload, 'phone_reply_verified': True}):
                return True
            operations.finish(tenant, identifier, lease, state, reply=answer,
                              error_code='' if state == 'completed' else 'call_followup_required')
    except business_email.EmailTransportError as exc:
        operations.finish(tenant, identifier, lease, 'uncertain' if exc.uncertain else 'needs_review',
                          reply=job['reply'], error_code=exc.code)
    except Exception as exc:
        # Never record provider exception bodies, caller text or credentials.
        from service.chat_diagnostics import emit
        emit('chat_optional_failure', phase='business_channel', error_type=type(exc).__name__)
        # A database error after provider acceptance must never turn an
        # ambiguous send back into an editable/resendable draft.
        operations.finish(tenant, identifier, lease, 'uncertain' if sending else 'needs_review',
                          reply=job['reply'], error_code='channel_processing_failed')
    return True


def run_pending(container, limit=20):
    global _tenant_offset
    count = 0
    # A bounded share per tenant prevents one busy inbox monopolising a pass.
    tenants = list(container.storage.tenant_keys())
    if not tenants:
        return 0
    start = _tenant_offset % len(tenants)
    for index in range(len(tenants)):
        tenant = tenants[(start+index) % len(tenants)]
        try:
            for channel in channels.CHANNELS:
                config = channels.settings(container.storage, tenant)[channel]
                operations.purge(tenant, channel, config['retention_days'])
            for _ in range(2):
                if count >= limit or not process_one(container, tenant):
                    break
                count += 1
        except Exception as exc:
            from service.chat_diagnostics import emit
            emit('chat_optional_failure', phase='business_channel_tenant', error_type=type(exc).__name__)
        _tenant_offset = (start+index+1) % len(tenants)
        if count >= limit:
            break
    return count


def start(app):
    global _thread, _pid
    if os.getenv('V7_CHANNEL_WORKER', 'false') != 'true' or app.testing:
        return
    with _lock:
        if _pid == os.getpid() and _thread and _thread.is_alive():
            return
        _pid = os.getpid()
        _stop.clear()
        def loop():
            while not _stop.is_set():
                try:
                    with app.app_context():
                        run_pending(app.container)
                except Exception as exc:
                    app.logger.warning('Business channel worker failed (%s)', type(exc).__name__)
                _wake.wait(3)
                _wake.clear()
        _thread = Thread(target=loop, name='v7-business-channels', daemon=True)
        _thread.start()
        atexit.register(lambda: (_stop.set(), _wake.set()))


if __name__ == '__main__':
    import argparse
    from app import create_app
    parser = argparse.ArgumentParser(description='Run V7 durable channel work or content retention once.')
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--once', action='store_true')
    choice.add_argument('--purge-only', action='store_true')
    args = parser.parse_args()
    app = create_app()
    with app.app_context():
        if args.once:
            print('Processed operations:', run_pending(app.container))
        else:
            count = 0
            for tenant in app.container.storage.tenant_keys():
                for channel in channels.CHANNELS:
                    config = channels.settings(app.container.storage, tenant)[channel]
                    count += operations.purge(tenant, channel, config['retention_days'])
            print('Removed message content:', count)
