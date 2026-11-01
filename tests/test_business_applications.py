"""Commercial eligibility uses real sessions and synthetic provider/database data."""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from service import business_applications as applications, subscriptions, tenant_access
from service.tenant_service import TenantService
from tests.conftest import set_test_identity
from tests.test_subscriptions import stripe as stripe_fixture

stripe = stripe_fixture


def details(**changes):
    return {'business_name': 'Synthetic detailing company', 'website': '',
            'description': 'Vehicle detailing and paint correction', 'plan_id': 'business',
            'accepted_terms': True, 'policy_version': 'draft-1', **changes}


@pytest.fixture
def intake(app):
    value = json.loads(applications._json(applications.DEFAULT_SETTINGS))
    value.update(intake_enabled=True, legal_review_completed=True, owner_email='operator@example.test')
    with applications.database(write=True) as db:
        applications._execute(db, 'INSERT INTO business_application_settings VALUES (1,?)', (applications._json(value),))
    return value


@pytest.fixture
def workspace(app, intake):
    tenant = 'APPLICANT'
    identity = {'id': 'applicant', 'email': 'applicant@example.test', 'roles': ['business_owner'], 'tenant': tenant}
    with app.app_context():
        TenantService(app.container.storage).create_tenant(tenant, 'Synthetic company', owner=identity)
    client = app.test_client()
    operator = app.test_client()
    with client.session_transaction() as state:
        set_test_identity(client, state, identity)
    with operator.session_transaction() as state:
        set_test_identity(operator, state, {'id': 'platform-reviewer', 'email': 'reviewer@example.test',
                                          'roles': ['platform_admin'], 'tenant': 'EXAMPLE'})
    return client, operator, tenant


def apply(workspace):
    client, _, tenant = workspace
    response = client.post('/business-applications/current?tenant=' + tenant, json=details())
    assert response.status_code == 201, response.json
    return response.json['application']


def decide(workspace, decision, **kwargs):
    _, operator, tenant = workspace
    row = operator.get('/business-applications/review?tenant=' + tenant).json['application']
    return operator.post('/business-applications/review?tenant=' + tenant,
                         json={'revision': row['revision'], 'decision': decision, **kwargs})


def test_new_managed_workspace_cannot_purchase_without_application(workspace, stripe):
    client, _, tenant = workspace
    assert client.get('/business-applications/current?tenant=' + tenant).json['application'] is None
    response = client.post('/billing/checkout?tenant=' + tenant, json={'kind': 'platform', 'plan_id': 'business'})
    assert response.status_code == 403
    stripe.assert_not_called()


@pytest.mark.parametrize('state', ['pending', 'reject', 'request_information', 'expire', 'cancel'])
@pytest.mark.parametrize('path,payload', [('/billing/checkout', {'kind': 'platform'}),
    ('/billing/checkout', {'kind': 'implementation'}), ('/billing/checkout', {'kind': 'whatsapp'}),
    ('/billing/checkout', {'kind': 'api', 'month': '2026-10'}),
    ('/billing/usage-credit/checkout', {'pack_id': 'gbp_5', 'request_id': 'synthetic-request-123'}),
    ('/billing/change-plan', {'plan_id': 'scale'}), ('/billing/portal', {})])
def test_all_purchase_entry_points_fail_closed(workspace, stripe, state, path, payload):
    client, _, tenant = workspace
    row = apply(workspace)
    if state == 'cancel':
        assert client.post('/business-applications/cancel?tenant=' + tenant, json={'revision': row['revision']}).status_code == 200
    elif state != 'pending':
        assert decide(workspace, state, message='Please describe the services.').status_code == 200
    response = client.post(path + '?tenant=' + tenant,
                           json={**payload, 'approved': True, 'status': 'APPROVED', 'tenant': 'EXAMPLE'})
    assert response.status_code == 403, response.json
    stripe.assert_not_called()
    with client.application.app_context():
        assert tenant_access.activation(tenant)['active'] is False


def test_customer_cannot_set_status_or_private_fields(workspace):
    client, operator, tenant = workspace
    response = client.post('/business-applications/current?tenant=' + tenant,
        json=details(status='APPROVED', service_preserved=1, research={'decision': 'approve'}, contact_email='attacker@example.test'))
    assert response.json['application']['status'] == 'PENDING_REVIEW'
    assert response.json['application']['contact_email'] == 'applicant@example.test'
    assert not response.json['application']['existing_service_preserved']
    assert client.post('/business-applications/review?tenant=' + tenant, json={'decision': 'approve', 'revision': 1}).status_code == 403
    assert operator.post('/business-applications/review?tenant=' + tenant, json={'decision': 'APPROVED', 'revision': 1}).status_code == 400


def test_private_notes_research_and_other_applications_are_not_exposed(workspace, app):
    client, operator, tenant = workspace
    apply(workspace)
    assert decide(workspace, 'request_information', note='PRIVATE_REVIEW_MARKER', message='Which services do you offer?').status_code == 200
    public = client.get('/business-applications/current?tenant=' + tenant)
    assert 'PRIVATE_REVIEW_MARKER' not in public.text and 'research' not in public.json['application']
    assert public.json['application']['public_message'] == 'Which services do you offer?'
    assert 'PRIVATE_REVIEW_MARKER' in operator.get('/business-applications/review?tenant=' + tenant).text
    for method, path in [('get', '/current'), ('put', '/current'), ('post', '/cancel'), ('post', '/close-payments')]:
        response = getattr(client, method)('/business-applications' + path + '?tenant=EXAMPLE', **({'json': details()} if method != 'get' else {}))
        assert response.status_code == 403
    assert client.get('/business-applications/queue').status_code == 403
    assert client.get('/business-applications/settings').status_code == 403
    assert app.test_client().get('/business-applications/review?tenant=' + tenant).status_code == 401


def test_staff_and_csrf_cannot_decide_or_change_settings(workspace, app):
    from flask.testing import FlaskClient
    client, _, tenant = workspace
    apply(workspace)
    staff = app.test_client()
    with staff.session_transaction() as state:
        set_test_identity(staff, state, {'id': 'staff', 'roles': ['business_staff'], 'tenant': tenant})
    for path in ['/review', '/settings', '/research', '/current', '/cancel']:
        assert staff.post('/business-applications' + path + '?tenant=' + tenant, json={}).status_code in {403, 405}
    browser = FlaskClient(app)
    assert browser.post('/business-applications/current', json=details()).status_code == 403
    assert client.post('/business-applications/cancel?tenant=' + tenant, json={'revision': 1},
                       headers={'X-CSRF-Token': 'wrong'}).status_code == 403


def test_no_self_approval_even_for_platform_role(workspace, app):
    _, _, tenant = workspace
    apply(workspace)
    self_admin = app.test_client()
    with self_admin.session_transaction() as state:
        set_test_identity(self_admin, state, {'id': 'self', 'email': 'applicant@example.test',
                                             'roles': ['platform_admin'], 'tenant': 'EXAMPLE'})
    response = self_admin.post('/business-applications/review?tenant=' + tenant, json={'revision': 1, 'decision': 'approve'})
    assert response.status_code == 403


def test_duplicate_application_and_stale_decision_are_conflicts(workspace):
    client, operator, tenant = workspace
    apply(workspace)
    assert client.post('/business-applications/current?tenant=' + tenant, json=details()).status_code == 409
    assert decide(workspace, 'approve').status_code == 200
    assert operator.post('/business-applications/review?tenant=' + tenant, json={'revision': 1, 'decision': 'reject'}).status_code == 409
    assert client.get('/business-applications/current?tenant=' + tenant).json['application']['status'] == 'APPROVED'


def test_open_checkout_and_uncertain_creation_prevent_revocation(workspace, stripe):
    client, _, tenant = workspace
    apply(workspace)
    assert decide(workspace, 'approve').status_code == 200
    with client.application.app_context():
        applications.reserve_payment(tenant, 'uncertain-reference', 'platform')
    assert decide(workspace, 'reject').status_code == 409
    assert client.post('/business-applications/close-payments?tenant=' + tenant, json={}).status_code == 409
    stripe.assert_not_called()
    with client.application.app_context():
        applications.bind_payment(tenant, 'uncertain-reference', 'cs_synthetic')
    stripe.side_effect = [{'id': 'cs_synthetic', 'status': 'open'}, {'id': 'cs_synthetic', 'status': 'expired'}]
    assert client.post('/business-applications/close-payments?tenant=' + tenant, json={}).status_code == 200
    assert decide(workspace, 'reject').status_code == 200
    with client.application.app_context(), pytest.raises(applications.ApplicationError):
        applications.verify_payment(tenant, 'uncertain-reference', 'platform')


def test_approved_checkout_reuses_plan_but_does_not_activate(workspace, stripe, monkeypatch):
    client, _, tenant = workspace
    apply(workspace)
    assert decide(workspace, 'approve').status_code == 200
    monkeypatch.setenv('V7_VAT_REGISTERED', 'false')
    stripe.return_value = {'id': 'cs_application', 'url': 'https://checkout.stripe.com/c/pay/application'}
    response = client.post('/billing/checkout?tenant=' + tenant, json={'kind': 'platform'})
    assert response.status_code == 200, response.json
    payload = stripe.call_args.args[2]
    assert payload['metadata[tenant]'] == tenant and payload['metadata[plan_id]'] == 'business'
    assert payload['line_items[0][price_data][unit_amount]'] == 19900
    with client.application.app_context():
        assert not tenant_access.activation(tenant)['active']
        applications.verify_payment(tenant, payload['metadata[billing_ref]'], 'platform')
    wrong_plan = client.post('/billing/checkout?tenant=' + tenant, json={'kind': 'implementation', 'plan_id': 'starter'})
    assert wrong_plan.status_code == 409


def test_changed_details_reopen_review_without_resetting_account(workspace):
    client, _, tenant = workspace
    apply(workspace)
    assert decide(workspace, 'approve').status_code == 200
    with applications.database(tenant, write=True) as db:
        applications._execute(db, 'UPDATE business_applications SET updated=? WHERE tenant=?', (time.time() - 60, tenant))
    row = client.get('/business-applications/current?tenant=' + tenant).json['application']
    response = client.put('/business-applications/current?tenant=' + tenant,
                          json=details(revision=row['revision'], description='Changed business activities'))
    assert response.status_code == 200 and response.json['application']['status'] == 'PENDING_REVIEW'
    assert client.get('/auth/session').status_code == 200


@pytest.mark.parametrize('changes', [{'website': 'https://127.0.0.1/'}, {'website': 'https://localhost/'},
    {'website': 'https://a.example@localhost/'}, {'website': 'http://example.com'},
    {'website': '', 'description': ''}, {'accepted_terms': 'true'}, {'policy_version': 'old'},
    {'plan_id': {'$ne': ''}}, {'business_name': 'x' * 121}])
def test_invalid_and_adversarial_application_inputs(workspace, changes):
    client, _, tenant = workspace
    assert client.post('/business-applications/current?tenant=' + tenant, json=details(**changes)).status_code == 400


def test_research_failure_never_decides_application(workspace, monkeypatch):
    from service.application_research import process
    import service.website_knowledge as website
    client, _, tenant = workspace
    apply(workspace)
    with applications.database(tenant, write=True) as db:
        policy = applications.settings(db=db)
        policy['research_enabled'] = True
        applications._execute(db, 'UPDATE business_application_settings SET value=?', (applications._json(policy),))
    monkeypatch.setattr(website, 'import_website', Mock(side_effect=RuntimeError('PRIVATE_RESEARCH_ERROR')))
    with client.application.app_context():
        process(client.application.container, tenant, 1)
    assert client.get('/business-applications/current?tenant=' + tenant).json['application']['status'] == 'PENDING_REVIEW'
    assert 'PRIVATE_RESEARCH_ERROR' not in client.get('/business-applications/current?tenant=' + tenant).text


def test_notification_outbox_survives_failure_and_omits_private_notes(workspace, monkeypatch):
    from service import application_notifications, registration_mail
    client, _, tenant = workspace
    apply(workspace)
    assert decide(workspace, 'request_information', note='SECRET_REVIEW_NOTE', message='Please describe your public services.').status_code == 200
    sent = Mock(side_effect=RuntimeError('SMTP_PRIVATE_TOKEN'))
    monkeypatch.setattr(registration_mail, 'send_transactional', sent)
    with client.application.app_context():
        while not sent.called:
            assert application_notifications.process_one(client.application.container)
        assert client.get('/business-applications/current?tenant=' + tenant).json['application']['status'] == 'NEEDS_INFORMATION'
        sent.side_effect = None
        with applications.database(write=True) as db:
            applications._execute(db, 'UPDATE business_application_notifications SET available=0')
        while application_notifications.process_one(client.application.container):
            pass
    assert 'SECRET_REVIEW_NOTE' not in str(sent.call_args_list)
    assert '/console/application?' in str(sent.call_args_list)
    assert 'New Vertex Seven business application' in str(sent.call_args_list)
    first_key = sent.call_args_list[0].kwargs['idempotency_key']
    assert sum(call.kwargs['idempotency_key'] == first_key for call in sent.call_args_list) == 2


def test_settings_are_typed_and_cannot_enable_unreviewed_policy(workspace):
    _, operator, _ = workspace
    value = operator.get('/business-applications/settings').json['settings']
    response = operator.put('/business-applications/settings', json={**value, 'legal_review_completed': False})
    assert response.status_code == 400
    assert operator.put('/business-applications/settings', json={**value, 'research_enabled': 'true'}).status_code == 400


def test_simultaneous_reviewers_cannot_overwrite_a_decision(workspace, app):
    _, operator, tenant = workspace
    apply(workspace)
    cookies = operator.get_cookie('session')
    def submit(decision):
        client = app.test_client()
        client.set_cookie('session', cookies.value)
        return client.post('/business-applications/review?tenant=' + tenant,
                           json={'revision': 1, 'decision': decision}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, ['approve', 'reject']))
    assert sorted(results) == [200, 409]


def test_full_approved_application_to_verified_subscription_and_setup(workspace, stripe, monkeypatch):
    from tests.test_subscriptions import signature
    client, _, tenant = workspace
    apply(workspace)
    assert decide(workspace, 'approve').status_code == 200
    monkeypatch.setenv('V7_VAT_REGISTERED', 'false')
    metadata, invoices = {}, {}
    def provider(method, path, *args, **kwargs):
        if method == 'POST' and path == '/v1/checkout/sessions':
            payload = args[0]
            kind = payload['metadata[kind]']
            metadata[kind] = {key: payload['metadata[' + key + ']'] for key in ('tenant', 'kind', 'billing_ref', 'plan_id')}
            return {'id': 'cs_application_' + kind, 'url': 'https://checkout.stripe.com/c/pay/' + kind}
        if path == '/v1/subscriptions/sub_application':
            return {'metadata': metadata['platform'], 'customer': 'cus_application', 'status': 'active',
                    'items': {'data': [{'current_period_end': int(time.time()) + 86400}]}}
        if path.startswith('/v1/invoices/'):
            return invoices[path.rsplit('/', 1)[1]]
        raise AssertionError('Unexpected synthetic provider call')
    stripe.side_effect = provider
    assert client.post('/billing/checkout?tenant=' + tenant, json={'kind': 'platform'}).status_code == 200
    assert not tenant_access.activation(tenant)['active']
    invoices['in_applicationmonthly'] = {'id':'in_applicationmonthly','currency':'gbp','created':int(time.time()),
        'subscription':'sub_application','total':19900,'amount_paid':19900,'amount_remaining':0,
        'status':'paid','billing_reason':'subscription_create','lines':{'data':[]}}
    def deliver(invoice):
        body = json.dumps({'type':'invoice.paid','data':{'object':{'id':invoice}}}).encode()
        response = client.post('/billing/stripe/webhook', data=body,content_type='application/json',
                               headers={'Stripe-Signature':signature(body)})
        assert response.status_code == 200, response.json
    deliver('in_applicationmonthly')
    assert not tenant_access.activation(tenant)['active']
    assert client.post('/billing/checkout?tenant=' + tenant,json={'kind':'implementation'}).status_code == 200
    invoices['in_applicationsetup'] = {'id':'in_applicationsetup','currency':'gbp','created':int(time.time()),
        'customer':'cus_application','metadata':metadata['implementation'],'total':29900,'amount_paid':29900,
        'amount_remaining':0,'status':'paid','lines':{'data':[]}}
    deliver('in_applicationsetup')
    deliver('in_applicationsetup')
    assert tenant_access.activation(tenant)['active']
    with subscriptions.connection(tenant) as db:
        assert db.execute('SELECT COUNT(*),SUM(paid) FROM billing_invoices WHERE tenant=?',(tenant,)).fetchone()[:] == (2,49800)
    # A material change requests review without automatically ending paid service.
    storage = client.application.container.storage
    with client.application.app_context():
        profile = storage.read_json(tenant, 'store_info.json')
        storage.write_json(tenant, 'store_info.json', {**profile, 'name': 'Changed company activity'})
    assert client.get('/business-applications/current?tenant=' + tenant).json['application']['status'] == 'PENDING_REVIEW'
    assert tenant_access.activation(tenant)['active']
    assert client.post('/billing/usage-credit/checkout?tenant=' + tenant,
                       json={'pack_id':'gbp_5','request_id':'after-material-change'}).status_code == 403


def test_unapproved_webhook_cannot_activate_a_managed_business_with_no_application(workspace):
    _, _, tenant = workspace
    with pytest.raises(applications.ApplicationError, match='application_payment_not_authorized'):
        applications.verify_payment(tenant, 'forged-private-reference', 'platform')


def test_retention_minimises_closed_records_but_not_paid_accounts(workspace):
    client, operator, tenant = workspace
    apply(workspace)
    assert decide(workspace, 'reject', note='Private old review').status_code == 200
    with applications.database(tenant, write=True) as db:
        applications._execute(db, 'UPDATE business_applications SET updated=0 WHERE tenant=?', (tenant,))
    assert applications.purge_closed(tenant)
    result = operator.get('/business-applications/review?tenant=' + tenant).json['application']
    assert result['contact_email'] == '' and result['business_name'] == 'Archived application'
    assert not any(event['note'] for event in result['history'])
    assert decide(workspace, 'approve').status_code == 409


def test_source_checked_research_cannot_output_an_approval_or_invent_evidence(monkeypatch):
    from types import SimpleNamespace
    from service import api_usage
    from service.application_research import _summarise
    container = SimpleNamespace(settings=SimpleNamespace(PLATFORM_MARKETING_TENANT='PLATFORM'),
                                rewriter=SimpleNamespace(_client=object(), _model='gpt-4o-mini'))
    monkeypatch.setattr(subscriptions, 'internal_business', lambda _: True)
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=''))])
    provider = Mock(return_value=response)
    monkeypatch.setattr(api_usage, 'tracked_completion', provider)
    pages = [{'url':'https://public.example/','title':'Services','text':'Paint correction and full valets.'}]
    for output in [{'status':'APPROVED'}, {'offerings':[{'source':0,'quote':'Invented activity'}],'review_items':[]},
                   {'offerings':[{'source':9,'quote':'Paint correction'}],'review_items':[]}]:
        response.choices[0].message.content = json.dumps(output)
        with pytest.raises(ValueError):
            _summarise(container, pages, {})
    response.choices[0].message.content = json.dumps({'offerings':[{'source':0,'quote':'Paint correction'}],'review_items':[]})
    assert _summarise(container, pages, {})['offerings'][0]['quote'] == 'Paint correction'
    assert 'tools' not in provider.call_args.kwargs
    assert provider.call_args.kwargs['messages'][1]['role'] == 'user'


def test_research_respects_disallowed_robots_without_requesting_pages(monkeypatch):
    from service import website_knowledge as website
    policy = Mock()
    policy.can_fetch.return_value = False
    monkeypatch.setattr(website, '_research_robots', lambda _: policy)
    network = Mock(side_effect=AssertionError('Disallowed content must not be requested'))
    monkeypatch.setattr(website, '_resolve_public_ip', network)
    with pytest.raises(website.WebsiteImportError, match='No readable public pages'):
        website.import_website('https://public.example/', respect_robots=True, max_pages=3, max_total_chars=12000)
    network.assert_not_called()


def test_application_api_returns_json_and_rejects_cross_origin_writes(workspace):
    client, _, tenant = workspace
    result = client.get('/business-applications/current?tenant=' + tenant)
    assert result.status_code == 200 and result.is_json
    assert result.headers.get('X-Robots-Tag') == 'noindex, nofollow'
    assert client.post('/business-applications/current?tenant=' + tenant, json=details(),
                       headers={'Origin':'https://attacker.example'}).status_code == 403


def test_accepted_policy_is_preserved_when_platform_policy_changes(workspace):
    client, operator, tenant = workspace
    row = apply(workspace)
    accepted = row['accepted_policy_text']
    value = operator.get('/business-applications/settings').json['settings']
    changed = operator.put('/business-applications/settings', json={**value, 'policy': value['policy'] + '\nA reviewed new policy condition.'})
    assert changed.status_code == 200
    response = client.get('/business-applications/current?tenant=' + tenant).json
    assert response['application']['accepted_policy_text'] == accepted
    assert response['policy']['policy'] != accepted
    assert response['application']['policy_version'] != response['policy']['policy_version']
    review = operator.get('/business-applications/review?tenant=' + tenant).json['application']
    assert any(event['kind'] == 'policy_accepted' and accepted in event['note'] for event in review['history'])
    # A private stored annotation cannot become a public DTO merely because it
    # was added alongside the whitelisted public application details.
    with applications.database(tenant, write=True) as db:
        stored = applications._lock(db, tenant)
        detail = json.loads(stored['details'])
        detail['private_annotation'] = 'INTERNAL_ONLY_MARKER'
        applications._execute(db, 'UPDATE business_applications SET details=? WHERE tenant=?', (applications._json(detail), tenant))
    assert 'INTERNAL_ONLY_MARKER' not in client.get('/business-applications/current?tenant=' + tenant).text


def test_application_search_uses_business_details_not_agreement_text(workspace):
    _, operator, _ = workspace
    apply(workspace)
    assert operator.get('/business-applications/queue?search=detailing').json['total'] == 1
    # This word exists in the accepted policy, not the applicant's activities.
    assert operator.get('/business-applications/queue?search=gambling').json['total'] == 0
    assert operator.get('/business-applications/queue?search=%25').json['total'] == 0
