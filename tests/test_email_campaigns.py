"""Exercise marketing consent, private tenancy and ambiguous provider outcomes."""
import json
from threading import Barrier
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from connectors import business_email
from service import channel_intelligence, email_campaigns
from tests.test_subscriptions import identity


PATH = '/admin/api/email-campaigns'
SEGMENT = '00000000-0000-4000-8000-000000000001'
BROADCAST = '00000000-0000-4000-8000-000000000002'
KEY = 're_' + 'campaign-fixture-only'
COPY = {'title': 'Summer launch', 'subject': 'Explore our summer collection',
        'body': 'The summer collection is here.\n\nAsk our team about <the new range>.'}
BINDING = {'segment_id': SEGMENT, 'sender': 'marketing@example.com', 'business_name': 'Example',
           'mailing_address': '1 Example Road', 'api_key': KEY}
CONTACTS = {'has_more': False, 'data': [
    {'id': '00000000-0000-4000-8000-000000000003', 'email': 'subscriber@example.com', 'unsubscribed': False},
    {'id': '00000000-0000-4000-8000-000000000004', 'email': 'unsubscribed@example.com', 'unsubscribed': True},
]}


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv('V7_EMAIL_CAMPAIGN_ROUTES_JSON', json.dumps({'EXAMPLE': BINDING}))
    request = Mock(side_effect=AssertionError('unexpected provider call'))
    monkeypatch.setattr(business_email, '_request', request)
    return request


def create(client):
    response = client.post(PATH, json=COPY)
    assert response.status_code == 201, response.json
    return response.json['campaign']


def review(client, row):
    response = client.post(PATH + '/' + row['id'] + '/review',
                           json={'revision': row['revision'], 'consent_confirmed': True})
    assert response.status_code == 200, response.json
    return response.json['campaign']


def send(client, row):
    return client.post(PATH + '/' + row['id'] + '/send',
                       json={'revision': row['revision'], 'confirmed': True})


def test_bound_audience_and_provider_unsubscribe(client, provider):
    identity(client, 'business_owner')
    draft = create(client)
    provider.side_effect = [CONTACTS, CONTACTS, {'id': BROADCAST}, CONTACTS, {'id': BROADCAST}]
    approved = review(client, draft)
    assert approved['state'] == 'reviewed' and approved['audience_count'] == 1
    result = send(client, approved)
    assert result.status_code == 200 and result.json['campaign']['state'] == 'submitted'
    _, _, prepare, _, dispatch = provider.call_args_list
    assert prepare.args == ('POST', '/broadcasts')
    payload = prepare.kwargs['data']
    assert prepare.kwargs['api_key'] == KEY
    assert payload['segment_id'] == SEGMENT and payload['from'] == BINDING['sender'] and payload['send'] is False
    assert '&lt;the new range&gt;' in payload['html']
    for field in ('html', 'text'):
        assert '{{{RESEND_UNSUBSCRIBE_URL}}}' in payload[field]
        assert '1 Example Road' in payload[field]
        assert 'AI-assisted campaign tool' in payload[field]
    assert dispatch.args == ('POST', f'/broadcasts/{BROADCAST}/send')
    assert send(client, approved).status_code == 409
    assert provider.call_count == 5
    public = client.get(PATH)
    assert public.headers['Cache-Control'] == 'no-store'
    for private in (KEY, SEGMENT, BROADCAST, 'subscriber@example.com', 'unsubscribed@example.com'):
        assert private not in public.text + result.text


def test_consent_confirmation_permissions_and_provider_ids_cannot_be_bypassed(client, provider):
    assert client.get(PATH).status_code == 401
    identity(client, 'business_staff')
    assert client.get(PATH).status_code == 403
    identity(client, 'business_owner')
    assert client.get(PATH + '?tenant=OTHER').status_code == 403
    assert client.post(PATH, json={**COPY, 'segment_id': SEGMENT}).status_code == 400
    assert client.post(PATH, json={**COPY, 'body': '{{{contact.email}}}'}).status_code == 400
    draft = create(client)
    assert send(client, draft).status_code == 409
    base = PATH + '/' + draft['id']
    assert client.post(base + '/review', json={'revision': draft['revision'], 'consent_confirmed': 1}).status_code == 400
    assert client.post(base + '/review', json={'revision': draft['revision'], 'consent_confirmed': True},
                       headers={'X-CSRF-Token': 'bad-token'}).status_code == 403
    assert client.get('/files/raw/' + email_campaigns.FILENAME).status_code == 404
    provider.assert_not_called()


def test_drift_and_edits_require_another_review(client, provider):
    identity(client, 'business_owner')
    different = {'has_more': False, 'data': [
        {**CONTACTS['data'][0], 'email': 'another-subscriber@example.com'},
    ]}
    provider.side_effect = [CONTACTS, different]
    draft = create(client)
    approved = review(client, draft)
    changed = send(client, approved)
    assert changed.status_code == 409 and changed.json['error'] == 'campaign_audience_changed'
    assert provider.call_count == 2 and all(call.args[0] == 'GET' for call in provider.call_args_list)
    result = client.put(PATH + '/' + draft['id'],
                        json={**COPY, 'subject': 'A different subject', 'revision': approved['revision']})
    assert result.json['campaign']['state'] == 'draft'
    assert send(client, approved).status_code == 409
    assert send(client, result.json['campaign']).status_code == 409


def test_reconfigured_sender_cannot_use_an_old_approval(client, provider, monkeypatch):
    identity(client, 'business_owner')
    provider.side_effect = [CONTACTS]
    approved = review(client, create(client))
    monkeypatch.setenv('V7_EMAIL_CAMPAIGN_ROUTES_JSON', json.dumps({
        'EXAMPLE': {**BINDING, 'sender': 'other-marketing@example.com'},
    }))
    response = send(client, approved)
    assert response.status_code == 409 and response.json['error'] == 'campaign_review_required'
    provider.assert_called_once()


def test_provider_draft_does_not_send_when_audience_changes_during_creation(client, provider):
    identity(client, 'business_owner')
    provider.side_effect = [CONTACTS, CONTACTS, {'id': BROADCAST},
                            {'has_more': False, 'data': [CONTACTS['data'][1]]}]
    approved = review(client, create(client))
    row = send(client, approved).json['campaign']
    assert row['state'] == 'failed' and row['error_code'] == 'campaign_audience_empty'
    assert all(not call.args[1].endswith('/send') for call in provider.call_args_list)


@pytest.mark.parametrize('contacts,error', [
    ({'has_more': True, 'data': []}, 'campaign_audience_too_large'),
    ({'has_more': False, 'data': [CONTACTS['data'][1]]}, 'campaign_audience_empty'),
])
def test_ineligible_audience_cannot_be_approved(client, provider, contacts, error):
    identity(client, 'business_owner')
    provider.side_effect = [contacts]
    draft = create(client)
    result = client.post(PATH + '/' + draft['id'] + '/review',
                         json={'revision': draft['revision'], 'consent_confirmed': True})
    assert result.status_code == 409 and result.json['error'] == error
    assert send(client, draft).status_code == 409
    provider.assert_called_once()


def test_timeout_reconciles_existing_send_without_a_replay(client, provider):
    identity(client, 'business_owner')
    provider.side_effect = [CONTACTS, CONTACTS, {'id': BROADCAST}, CONTACTS,
                            business_email.EmailTransportError('private error', uncertain=True),
                            {'id': BROADCAST, 'segment_id': SEGMENT, 'status': 'sent'}]
    approved = review(client, create(client))
    result = send(client, approved)
    uncertain = result.json['campaign']
    assert uncertain['state'] == 'uncertain' and 'private error' not in result.text
    assert send(client, uncertain).status_code == 409
    result = client.post(PATH + '/' + approved['id'] + '/reconcile', json={'revision': uncertain['revision']})
    assert result.status_code == 200 and result.json['campaign']['state'] == 'submitted'
    assert provider.call_args.args == ('GET', f'/broadcasts/{BROADCAST}')
    assert sum(call.args[1].endswith('/send') for call in provider.call_args_list) == 1


def test_parallel_requests_claim_the_same_campaign_once(app, client, provider):
    identity(client, 'business_owner')
    provider.side_effect = [CONTACTS]
    approved = review(client, create(client))
    gate = Barrier(2)
    initial_gets = iter((True, True))

    def transport(method, path, **kwargs):
        if method == 'GET':
            if next(initial_gets, False):
                gate.wait(timeout=10)
            return CONTACTS
        return {'id': BROADCAST}

    provider.side_effect = transport

    def attempt():
        with app.app_context():
            try:
                result = email_campaigns.send(app.container.storage, 'EXAMPLE', approved['id'],
                                              approved['revision'], 'operator')
                return result['state']
            except email_campaigns.CampaignError as error:
                return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: attempt(), range(2)))
    assert sorted(results) == ['campaign_changed', 'submitted']
    assert sum(call.args[1].endswith('/send') for call in provider.call_args_list) == 1


def test_generate_is_owner_only_rate_limited_and_never_sends(client, provider, monkeypatch):
    draft = Mock(return_value='Campaign copy for review.')
    monkeypatch.setattr(channel_intelligence, 'draft_campaign', draft, raising=False)
    identity(client, 'business_owner')
    for _ in range(4):
        result = client.post(PATH + '/generate', json={'brief': 'A launch based on our saved products'})
        assert result.status_code == 200 and result.json == {'body': 'Campaign copy for review.'}
    limited = client.post(PATH + '/generate', json={'brief': 'Another draft'})
    assert limited.status_code == 429
    assert draft.call_count == 4 and all(call.args[1] == 'EXAMPLE' for call in draft.call_args_list)
    assert client.get(PATH).json['campaigns'] == []
    provider.assert_not_called()
