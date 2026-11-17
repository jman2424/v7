"""Campaign labels require consent and never let customers choose approval."""
import json
from service import business_applications as applications, subscriptions
from tests import test_business_applications as application_tests

intake = application_tests.intake
workspace = application_tests.workspace
details = application_tests.details


def test_campaign_requires_consent_csrf_and_fixed_labels(client):
    assert client.post('/marketing/attribution',json={'source':'instagram'}).status_code==400
    client.set_cookie('v7_analytics_consent','v1:granted')
    assert client.post('/marketing/attribution',json={'source':'instagram'},headers={'X-CSRF-Token':'invalid'}).status_code==403
    assert client.post('/marketing/attribution',json={'source':'private-account@example.test'}).status_code==400
    assert client.post('/marketing/attribution',json={'source':'instagram'}).status_code==200
    client.delete_cookie('v7_analytics_consent')
    assert client.post('/marketing/attribution',json={'source':None}).status_code==200
    with client.session_transaction() as state:
        assert 'profile_campaign' not in state


def test_source_is_internal_and_paid_report_requires_operator(workspace):
    client,operator,tenant=workspace
    client.set_cookie('v7_analytics_consent','v1:granted')
    assert client.post('/marketing/attribution',json={'source':'tiktok'}).status_code==200
    assert client.post('/business-applications/current',json=details(acquisition_source='instagram')).status_code==201
    with applications.database(tenant) as db:
        row=applications._lock(db,tenant)
        assert json.loads(row['details'])['acquisition_source']=='tiktok'
        assert row['status']=='PENDING_REVIEW'
    assert client.get('/business-applications/acquisition').status_code==403
    with subscriptions.connection(tenant) as db:
        db.execute("INSERT INTO billing_invoices VALUES ('in_synthetic',?,'platform','2026-11',1,NULL,9900,9900,0,'paid','[]',NULL)",(tenant,))
    report=operator.get('/business-applications/acquisition')
    assert report.status_code==200
    source=next(row for row in report.json['sources'] if row['source']=='tiktok')
    assert source['applications']==1 and source['paid_subscriptions']==1 and source['first_payment_pence']==9900
    assert 'applicant@example.test' not in report.text
