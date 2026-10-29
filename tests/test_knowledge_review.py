"""Knowledge review is bounded, advisory, private to management and never paid AI."""
import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from service.knowledge_review import DOCUMENTS, MAX_ISSUES, MAX_ROWS, review, review_documents
from service.plan_catalog import get_plan
from tests.conftest import set_test_identity

NOW = datetime(2026, 10, 29, tzinfo=timezone.utc)


def configured_documents():
    return {
        'store_info.json': {'name': 'Fixture', 'about': 'Document translation.',
                            'email': 'team@example.com', 'website': 'https://fixture.example/'},
        'overrides.json': {'sales_playbook': {'primary_goal': 'request_quote'}},
        'catalog.json': {'currency': 'GBP', 'categories': [{'items': [
            {'name': 'Review', 'price': 50, 'sku': 'review'}]}]},
        'faq.json': [{'q': 'Certified translation?', 'a': 'Ask our team to confirm the certification needed.'}],
        'website_knowledge.json': {'source_url': 'https://fixture.example/', 'fetched_at': NOW.isoformat(),
                                   'pages': [{'url': 'https://fixture.example/services', 'text': 'Public services.'}]},
    }


def codes(result):
    return {issue['code'] for issue in result['issues']}


def identity(client, *, role='business_owner', permissions=None):
    user = {'id': 'reviewer', 'roles': [role], 'tenant': 'EXAMPLE'}
    if permissions is not None:
        user['permissions'] = permissions
    with client.session_transaction() as state:
        set_test_identity(client, state, user)


def test_review_does_not_change_sources_or_certify_readiness():
    documents = configured_documents()
    before = copy.deepcopy(documents)
    result = review_documents(documents, now=NOW)
    assert result['complete'] and result['issues'] == []
    assert documents == before
    assert result['counts']['active_catalogue_items_reviewed'] == 1
    assert 'semantic contradictions' in result['scope']
    assert 'ready' not in result


def test_empty_business_gets_useful_editor_tasks_without_invented_facts():
    result = review_documents({}, now=NOW)
    assert {'identity_missing', 'business_focus_missing', 'contact_missing', 'goal_review',
            'offerings_missing', 'faqs_missing'} <= codes(result)
    assert all(issue['section'] in {'profile', 'catalog', 'agent', 'faqs'} for issue in result['issues'])


def test_conflict_report_identifies_entries_without_disclosing_answers_or_private_work():
    documents = configured_documents()
    documents['faq.json'] = [{'q': 'Refund policy?', 'a': 'POLICY_A'},
                              {'q': 'REFUND POLICY ?', 'a': 'POLICY_B'},
                              {'q': 'Refund policy?', 'a': 'PRIVATE_FAQ', 'public': False}]
    documents['business_core.json'] = {'work': [{'customer_reference': 'PRIVATE_CUSTOMER'}],
        'offerings': [{'name': 'PRIVATE_OFFERING', 'active': False}]}
    result = review_documents(documents, now=NOW)
    assert result['counts']['conflicting_faq_topics'] == 1
    assert 'entries 1, 2' in next(issue['message'] for issue in result['issues'] if issue['code'] == 'faq_conflict')
    assert not any(secret in json.dumps(result) for secret in ('POLICY_A', 'POLICY_B', 'PRIVATE_'))


def test_identical_duplicates_are_advisory_and_do_not_count_as_conflicts():
    documents = configured_documents()
    documents['faq.json'] *= 2
    result = review_documents(documents, now=NOW)
    assert result['counts']['duplicate_faq_topics'] == 1
    assert result['counts']['conflicting_faq_topics'] == 0
    assert codes(result) == {'faq_duplicate'}


@pytest.mark.parametrize('age,code', [(31, 'website_stale'), (-2, 'website_date_unknown')])
def test_import_age_is_advisory_without_network_fetches(age, code):
    documents = configured_documents()
    documents['website_knowledge.json']['fetched_at'] = (NOW - timedelta(days=age)).isoformat()
    assert code in codes(review_documents(documents, now=NOW))


@pytest.mark.parametrize('value', ['', 'invalid', '2026-10-28T00:00:00'])
def test_unknown_or_naive_import_date_does_not_imply_freshness(value):
    documents = configured_documents()
    documents['website_knowledge.json']['fetched_at'] = value
    assert 'website_date_unknown' in codes(review_documents(documents, now=NOW))


def test_old_website_import_and_other_site_pages_are_not_counted_as_usable():
    documents = configured_documents()
    documents['store_info.json']['website'] = 'https://new.example/'
    result = review_documents(documents, now=NOW)
    assert result['counts']['usable_imported_pages'] == 0
    assert 'website_refresh' in codes(result)


def test_missing_currency_flags_price_claim_risk_without_changing_prices():
    documents = configured_documents()
    documents['catalog.json'].pop('currency')
    assert 'catalog_currency_missing' in codes(review_documents(documents, now=NOW))


def test_explicit_native_quote_only_service_does_not_require_a_fixed_price():
    documents = configured_documents()
    documents['catalog.json'] = {}
    documents['business_core.json'] = {'offerings': [{'name': 'Legal translation', 'price_type': 'quote', 'active': True}]}
    result = review_documents(documents, now=NOW)
    assert 'offerings_missing' not in codes(result)
    assert result['counts']['active_native_offerings_reviewed'] == 1


def test_report_limits_never_silently_claim_a_complete_audit():
    documents = configured_documents()
    documents['faq.json'] = [{'q': str(i), 'a': 'First'} for i in range(MAX_ROWS + 1)]
    result = review_documents(documents, now=NOW)
    assert not result['complete'] and 'review_limit' in codes(result)
    documents['faq.json'] = [row for i in range(100) for row in (
        {'q': str(i), 'a': 'First'}, {'q': str(i), 'a': 'Second'})]
    result = review_documents(documents, now=NOW)
    assert not result['complete'] and len(result['issues']) == MAX_ISSUES
    assert result['counts']['conflicting_faq_topics'] == 100


def test_malformed_source_shapes_are_review_issues_not_raw_data():
    result = review_documents({'store_info.json': [], 'faq.json': {},
                              'overrides.json': {'sales_playbook': {'unexpected': 'SECRET'}}}, now=NOW)
    assert {'invalid_document', 'playbook_invalid'} <= codes(result)
    assert 'SECRET' not in json.dumps(result)


def test_malformed_records_are_flagged_without_suppressing_valid_records():
    documents = configured_documents()
    documents['faq.json'].append({'q': 'Missing answer'})
    documents['catalog.json']['categories'][0]['items'].append(None)
    result = review_documents(documents, now=NOW)
    assert {'faq_invalid_entries', 'invalid_entries'} <= codes(result)
    assert result['counts']['faq_topics_reviewed'] == 1
    assert result['counts']['active_catalogue_items_reviewed'] == 1


def test_storage_reads_once_in_the_resolved_tenant_without_private_documents():
    calls = []
    class Storage:
        def read_json_many(self, tenant, filenames):
            calls.append((tenant, filenames))
            return configured_documents()
    review(Storage(), 'TENANT_A')
    assert calls == [('TENANT_A', DOCUMENTS)]
    assert not any('crm' in name or 'account' in name or 'history' in name for name in DOCUMENTS)


def test_route_requires_login(client):
    assert client.get('/admin/api/knowledge-review').status_code == 401


@pytest.mark.parametrize('role', ['business_owner', 'business_staff'])
def test_route_rejects_another_tenant_before_reviewing_documents(client, monkeypatch, role):
    identity(client, role=role)
    def forbidden(*args):
        pytest.fail('cross-tenant review reached storage')
    monkeypatch.setattr('service.knowledge_review.review', forbidden)
    assert client.get('/admin/api/knowledge-review?tenant=OTHER').status_code == 403


@pytest.mark.parametrize('permissions', [[], ['business_settings.read'], ['offerings.read']])
def test_scoped_staff_needs_both_existing_read_permissions(client, permissions):
    identity(client, role='business_staff', permissions=permissions)
    assert client.get('/admin/api/knowledge-review').status_code == 403


@pytest.mark.parametrize('plan', ['starter', 'business', 'scale'])
def test_review_is_available_on_every_plan_without_credit_or_model_calls(client, monkeypatch, plan):
    identity(client)
    monkeypatch.setattr('service.subscriptions.configured_plan', lambda tenant: get_plan(plan))
    monkeypatch.setattr('service.grounded_conversation.tracked_completion',
                        lambda *args, **kwargs: pytest.fail('review must not call a model'))
    response = client.get('/admin/api/knowledge-review')
    assert response.status_code == 200
    assert response.get_json()['tenant'] == 'EXAMPLE'
    assert response.headers['Cache-Control'] == 'no-store'
    assert 'issues' in response.get_json()


def test_route_storage_failure_does_not_expose_path_or_document(client, monkeypatch):
    identity(client)
    def broken(*args):
        raise ValueError('PRIVATE_PATH_AND_CONTENT')
    monkeypatch.setattr('service.knowledge_review.review', broken)
    response = client.get('/admin/api/knowledge-review')
    assert response.status_code == 503
    assert response.get_json() == {'error': 'knowledge_review_unavailable'}
