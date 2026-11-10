"""Private campaign workflow using Resend's marketing audience and delivery controls."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from html import escape
import json
import os
import re
import secrets
import time

from connectors import business_email
from retrieval.storage import Storage
from service.business_channels import UUID, address


FILENAME = 'email_campaigns.json'
MAX_AUDIENCE = 100
MAX_CAMPAIGNS = 50
REVIEW_TTL = 1800
SEND_TIMEOUT = 120
_ID = re.compile(r'[a-f0-9]{32}\Z')
_KEY = re.compile(r're_[A-Za-z0-9_-]{8,240}\Z')
_UNSUBSCRIBE = '{{{RESEND_UNSUBSCRIBE_URL}}}'
_AI_NOTICE = 'Sent with V7’s AI-assisted campaign tool.'
_EDITABLE = {'draft', 'reviewed', 'failed'}
_PUBLIC_FIELDS = ('id', 'title', 'subject', 'body', 'state', 'revision',
                  'audience_count', 'error_code', 'created_at', 'updated_at')


class CampaignError(ValueError):
    def __init__(self, code, status=400):
        super().__init__(code)
        self.code, self.status = code, status


def _fingerprint(value):
    encoded = json.dumps(value, ensure_ascii=True, separators=(',', ':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def checked_text(value, maximum, *, multiline=False):
    if not isinstance(value, str) or len(value) > maximum:
        raise CampaignError('invalid_campaign_copy')
    value = value.replace('\r\n', '\n').strip()
    if (not value or '{{' in value or '}}' in value
            or any(not char.isprintable() and not (multiline and char in '\n\t') for char in value)):
        raise CampaignError('invalid_campaign_copy')
    return value


@dataclass(frozen=True)
class Binding:
    segment_id: str
    sender: str
    business_name: str
    mailing_address: str
    api_key: str = field(repr=False)

    @property
    def revision(self):
        return _fingerprint((self.segment_id, self.sender, self.business_name, self.mailing_address))


def binding(tenant):
    """Operator supplies a dedicated credential and a consent-managed segment."""
    raw = os.getenv('V7_EMAIL_CAMPAIGN_ROUTES_JSON', '')
    if not raw or len(raw) > 100000:
        return None
    try:
        bindings = json.loads(raw)
        if not isinstance(bindings, dict) or len(bindings) > 100:
            return None
        parsed = {}
        used_segments, used_senders, used_keys, used_tenants = set(), set(), set(), set()
        for key, entry in bindings.items():
            if (key != Storage.validate_tenant_key(key) or key.casefold() in used_tenants
                    or not isinstance(entry, dict)
                    or set(entry) != {'segment_id', 'sender', 'business_name', 'mailing_address', 'api_key'}):
                return None
            segment, credential = entry['segment_id'], entry['api_key']
            if (not isinstance(segment, str) or not UUID.fullmatch(segment)
                    or not isinstance(credential, str) or not _KEY.fullmatch(credential)):
                return None
            sender = address(entry['sender'])
            segment = segment.lower()
            if segment in used_segments or sender in used_senders or credential in used_keys:
                return None
            used_segments.add(segment)
            used_senders.add(sender)
            used_keys.add(credential)
            used_tenants.add(key.casefold())
            parsed[key] = Binding(segment, sender, checked_text(entry['business_name'], 120),
                                  checked_text(entry['mailing_address'], 300, multiline=True), credential)
        return parsed.get(tenant)
    except (ValueError, TypeError, RecursionError):
        return None


def _require_binding(tenant):
    configured = binding(tenant)
    if configured is None:
        raise CampaignError('campaign_sender_not_configured', 409)
    return configured


def _read(storage, tenant):
    try:
        value = storage.read_json(tenant, FILENAME)
    except FileNotFoundError:
        return {'campaigns': {}, 'generation_attempts': []}
    if (not isinstance(value, dict) or not isinstance(value.get('campaigns'), dict)
            or not isinstance(value.get('generation_attempts'), list)):
        raise CampaignError('campaign_storage_unavailable', 503)
    return value


def _write(storage, tenant, document):
    storage._write_json(tenant, FILENAME, document, snapshot=False)


def _row(document, identifier, revision):
    if not _ID.fullmatch(identifier) or identifier not in document['campaigns']:
        raise CampaignError('campaign_not_found', 404)
    row = document['campaigns'][identifier]
    if row['revision'] != revision:
        raise CampaignError('campaign_changed', 409)
    return row


def _update(storage, tenant, identifier, revision, states, **changes):
    with storage.write_lock(tenant):
        document = _read(storage, tenant)
        row = _row(document, identifier, revision)
        if row['state'] not in states:
            raise CampaignError('campaign_state_conflict', 409)
        row.update(changes, revision=secrets.token_hex(16), updated_at=time.time())
        _write(storage, tenant, document)
    return row


def _public(row):
    result = {key: row[key] for key in _PUBLIC_FIELDS}
    if result['state'] == 'sending' and time.time() - result['updated_at'] >= SEND_TIMEOUT:
        result.update(state='uncertain', error_code='campaign_outcome_unknown')
    return result


def listing(storage, tenant):
    configured = binding(tenant)
    rows = _read(storage, tenant)['campaigns'].values()
    return {
        'configured': configured is not None,
        'can_manage': True,
        'sender': configured.sender if configured else '',
        'business_name': configured.business_name if configured else '',
        'mailing_address': configured.mailing_address if configured else '',
        'audience_limit': MAX_AUDIENCE,
        'campaigns': [_public(row) for row in sorted(rows, key=lambda row: row['created_at'], reverse=True)],
    }


def reserve_generation(storage, tenant):
    """Rate limit billable drafting per tenant across all app processes."""
    now = time.time()
    with storage.write_lock(tenant):
        document = _read(storage, tenant)
        attempts = [stamp for stamp in document['generation_attempts'] if now - stamp < 60]
        if len(attempts) >= 4:
            raise CampaignError('campaign_draft_rate_limited', 429)
        document['generation_attempts'] = [*attempts, now]
        _write(storage, tenant, document)


def _copy(title, subject, body):
    return {'title': checked_text(title, 80), 'subject': checked_text(subject, 140),
            'body': checked_text(body, 6000, multiline=True)}


def create(storage, tenant, actor, *, title, subject, body):
    copy = _copy(title, subject, body)
    now = time.time()
    identifier = secrets.token_hex(16)
    row = dict(copy, id=identifier, state='draft', revision=secrets.token_hex(16),
               audience_count=0, error_code='', created_by=actor, created_at=now, updated_at=now)
    with storage.write_lock(tenant):
        document = _read(storage, tenant)
        if len(document['campaigns']) >= MAX_CAMPAIGNS:
            raise CampaignError('campaign_storage_limit', 409)
        document['campaigns'][identifier] = row
        _write(storage, tenant, document)
    return _public(row)


def edit(storage, tenant, identifier, revision, *, title, subject, body):
    return _public(_update(storage, tenant, identifier, revision, _EDITABLE,
                           **_copy(title, subject, body), state='draft', audience_count=0,
                           review=None, provider_id=None, error_code=''))


def _audience(configured):
    """Validate a complete bounded segment and fingerprint subscribed membership."""
    try:
        data = business_email._request('GET', f'/segments/{configured.segment_id}/contacts?limit={MAX_AUDIENCE}',
                                       api_key=configured.api_key)
    except business_email.EmailTransportError:
        raise CampaignError('campaign_provider_unavailable', 503) from None
    rows = data.get('data')
    if data.get('has_more') is True:
        raise CampaignError('campaign_audience_too_large', 409)
    if data.get('has_more') is not False or not isinstance(rows, list) or len(rows) > MAX_AUDIENCE:
        raise CampaignError('campaign_provider_response_invalid', 502)
    subscribed = {}
    for row in rows:
        try:
            if not isinstance(row, dict) or type(row.get('unsubscribed')) is not bool:
                raise ValueError
            email = address(row.get('email'))
            identifier = row.get('id')
            if not isinstance(identifier, str) or not UUID.fullmatch(identifier):
                raise ValueError
        except ValueError:
            raise CampaignError('campaign_provider_response_invalid', 502) from None
        if not row['unsubscribed']:
            if email in subscribed:
                raise CampaignError('campaign_provider_response_invalid', 502)
            subscribed[email] = identifier
    if not subscribed:
        raise CampaignError('campaign_audience_empty', 409)
    # Never persist or expose contact addresses. The digest also detects address
    # changes to an existing contact ID between review and send.
    return len(subscribed), _fingerprint(sorted(subscribed.items()))


def review(storage, tenant, identifier, revision, actor):
    row = _row(_read(storage, tenant), identifier, revision)
    if row['state'] not in _EDITABLE:
        raise CampaignError('campaign_state_conflict', 409)
    configured = _require_binding(tenant)
    count, audience = _audience(configured)
    approval = {'binding': configured.revision, 'audience': audience,
                'actor': actor, 'reviewed_at': time.time(), 'consent_confirmed': True}
    return _public(_update(storage, tenant, identifier, revision, _EDITABLE, state='reviewed',
                           audience_count=count, review=approval, provider_id=None, error_code=''))


def _provider_copy(row, configured):
    footer = f'Marketing email from {configured.business_name}\n{configured.mailing_address}\n{_AI_NOTICE}'
    text = f"{row['body']}\n\n---\n{footer}\nUnsubscribe: {_UNSUBSCRIBE}"
    html = '<div style="font-family:Arial,sans-serif;font-size:16px;line-height:1.6">'
    html += escape(row['body']).replace('\n', '<br>') + '<hr><p>' + escape(footer).replace('\n', '<br>')
    html += f'<br><a href="{_UNSUBSCRIBE}">Unsubscribe</a></p></div>'
    return {'name': 'V7 '+row['id'], 'segment_id': configured.segment_id,
            'from': configured.sender, 'subject': row['subject'], 'html': html,
            'text': text, 'send': False}


def send(storage, tenant, identifier, revision, actor):
    row = _row(_read(storage, tenant), identifier, revision)
    if row['state'] != 'reviewed':
        raise CampaignError('campaign_review_required', 409)
    configured = _require_binding(tenant)
    approval = row['review']
    if (approval['consent_confirmed'] is not True or approval['binding'] != configured.revision
            or time.time() - approval['reviewed_at'] > REVIEW_TTL):
        raise CampaignError('campaign_review_required', 409)
    if _audience(configured) != (row['audience_count'], approval['audience']):
        raise CampaignError('campaign_audience_changed', 409)
    # Persist ownership of this send before touching the provider. A duplicate
    # request fails the revision check, even in a second process.
    claimed = _update(storage, tenant, identifier, revision, {'reviewed'},
                      state='sending', send_requested_by=actor)
    try:
        provider = business_email._request('POST', '/broadcasts', data=_provider_copy(row, configured),
                                            api_key=configured.api_key)
        provider_id = provider.get('id')
        if not isinstance(provider_id, str) or not UUID.fullmatch(provider_id):
            raise business_email.EmailTransportError('campaign_provider_response_invalid')
    except business_email.EmailTransportError:
        # Creating a draft can leave an orphan, but cannot deliver email.
        return _public(_update(storage, tenant, identifier, claimed['revision'], {'sending'},
                               state='failed', error_code='campaign_provider_draft_failed'))

    # A crash after this write can be reconciled by provider ID. An ambiguous
    # send is never replayed because Broadcasts do not document send idempotency.
    staged = _update(storage, tenant, identifier, claimed['revision'], {'sending'},
                     provider_id=provider_id)
    try:
        if _audience(configured) != (row['audience_count'], approval['audience']):
            raise CampaignError('campaign_audience_changed', 409)
    except CampaignError as error:
        return _public(_update(storage, tenant, identifier, staged['revision'], {'sending'},
                               state='failed', error_code=error.code))
    try:
        result = business_email._request('POST', f'/broadcasts/{provider_id}/send', data={},
                                          api_key=configured.api_key)
        if result.get('id') != provider_id:
            raise business_email.EmailTransportError('campaign_provider_response_invalid', uncertain=True)
    except business_email.EmailTransportError as error:
        state = 'uncertain' if error.uncertain else 'failed'
        code = 'campaign_outcome_unknown' if error.uncertain else 'campaign_provider_send_rejected'
    else:
        state, code = 'submitted', ''
    return _public(_update(storage, tenant, identifier, staged['revision'], {'sending'},
                           state=state, error_code=code))


def reconcile(storage, tenant, identifier, revision):
    row = _row(_read(storage, tenant), identifier, revision)
    if _public(row)['state'] != 'uncertain':
        raise CampaignError('campaign_state_conflict', 409)
    configured = _require_binding(tenant)
    provider_id = row.get('provider_id')
    if (not isinstance(provider_id, str) or not UUID.fullmatch(provider_id)
            or row['review']['binding'] != configured.revision):
        raise CampaignError('campaign_provider_review_required', 409)
    try:
        result = business_email._request('GET', f'/broadcasts/{provider_id}', api_key=configured.api_key)
    except business_email.EmailTransportError:
        raise CampaignError('campaign_provider_unavailable', 503) from None
    if result.get('id') != provider_id or result.get('segment_id') != configured.segment_id:
        raise CampaignError('campaign_provider_response_invalid', 502)
    if result.get('status') in {'queued', 'sent'}:
        return _public(_update(storage, tenant, identifier, revision, {'sending', 'uncertain'},
                               state='submitted', error_code=''))
    return _public(row)
