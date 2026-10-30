"""Owner-opted cleanup of handled mail, never model-selected mailbox actions."""
from datetime import datetime
import time

from connectors import business_email as provider
from service import business_channels as channels, business_operations as operations


def _allowed(container, tenant, recipient, inbox, days):
    settings = channels.settings(container.storage, tenant)['email']
    return (channels.active(container.storage, tenant, 'email') and settings['cleanup_confirmed']
            and settings['provider_cleanup'] == 'trash_handled'
            and settings['retention_days'] == days
            and channels.bindings('email').get(recipient) == tenant
            and channels.inbox_bindings().get(inbox) == recipient)


def _safe_messages(messages, rows, cutoff):
    known = {}
    sent = set()
    for row in rows:
        if row['state'] not in {'completed', 'rejected', 'retaining'} or row['payload'].get('approved_action'):
            return False
        if row['created'] > cutoff:
            return False
        known[row['payload'].get('email_id')] = row
        if row['provider_id']:
            sent.add(row['provider_id'])
    for message in messages:
        if not isinstance(message, dict):
            return False
        direction = message.get('direction')
        if not ((direction == 'inbound' and message.get('id') in known)
                or (direction == 'outbound' and message.get('id') in sent)):
            return False
        try:
            received = datetime.fromisoformat(message['received_at'].replace('Z', '+00:00'))
            if received.tzinfo is None or received.timestamp() > cutoff:
                return False
        except (KeyError, TypeError, ValueError, OverflowError):
            return False
    return bool(messages)


def run(container, tenant, limit=5):
    operations.recover_cleanup(tenant)
    config = channels.settings(container.storage, tenant)['email']
    if config['provider_cleanup'] != 'trash_handled' or not config['cleanup_confirmed']:
        return
    claimed = 0
    for candidate in operations.cleanup_candidates(tenant, config['retention_days']):
        if claimed >= limit:
            break
        payload = candidate['payload']
        inbox, thread, recipient = payload.get('inbox_id'), payload.get('thread_id'), payload.get('recipient')
        if (payload.get('cleanup_outcome') or payload.get('approved_action') or not inbox or not thread
                or not _allowed(container, tenant, recipient, inbox, config['retention_days'])):
            continue
        job = operations.claim_cleanup(tenant, candidate)
        if not job:
            continue
        claimed += 1
        outcome = 'skipped'
        try:
            cutoff = time.time()-config['retention_days']*86400
            rows = operations.thread_operations(tenant, inbox, thread)
            before = provider.thread_emails(inbox, thread)
            if _safe_messages(before, rows, cutoff) and _allowed(container, tenant, recipient, inbox, config['retention_days']):
                job['payload'].update(cleanup_thread_hash=operations.cleanup_hash(inbox, thread), cleanup_attempted=True)
                if not operations.save_payload(tenant, job['id'], job['lease'], job['payload']):
                    continue
                provider.trash_thread(inbox, thread)
                outcome = 'trashed'
                # Thread deletion is reversible. Check for arrivals racing the
                # first read, and reopen instead of retaining new/unhandled mail
                # in Trash. Future inbound webhooks also reopen our cleaned thread.
                after = provider.thread_emails(inbox, thread)
                if not _safe_messages(after, operations.thread_operations(tenant, inbox, thread), cutoff):
                    provider.restore_thread(inbox, thread)
                    outcome = 'restored'
        except Exception as exc:
            from service.chat_diagnostics import emit
            emit('chat_optional_failure', phase='email_retention', error_type=type(exc).__name__)
            outcome = 'failed'
        operations.cleanup_receipt(tenant, job, outcome)
