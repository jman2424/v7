"""Route-level login, company and staff boundaries for management data."""
import pytest

from service import analytics_db
from tests.conftest import set_test_identity


MANAGEMENT_READS = (
    '/admin/api/' + resource for resource in (
        'catalog', 'faq', 'offers', 'delivery', 'profile', 'branches',
        'agent-settings', 'widget', 'website-knowledge', 'accounts',
        'join-requests', 'sales-actions', 'action-requests', 'insights',
        'statistics', 'kpis', 'timeseries', 'sessions_timeseries', 'channels',
        'intents', 'fallbacks', 'errors', 'questions', 'leads', 'conversations',
        'integrations', 'activation', 'api-usage',
    )
)
MANAGEMENT_READS = tuple(MANAGEMENT_READS) + (
    '/files/raw/catalog.json', '/files/versions', '/analytics/kpis.json',
    '/analytics/rollups.json', '/analytics/export.csv', '/__diag/validate',
    '/__diag/selfrepair', '/__diag/self_repair', '/catalog_webhook',
    '/export_catalog_csv', '/mode', '/billing/subscription',
)
MANAGEMENT_WRITES = (
    ('PUT', '/admin/api/catalog'), ('PUT', '/admin/api/faq'),
    ('PUT', '/admin/api/offers'), ('PUT', '/admin/api/delivery'),
    ('PUT', '/admin/api/profile'), ('PUT', '/admin/api/branches'),
    ('PUT', '/admin/api/agent-settings'), ('PUT', '/admin/api/widget'),
    ('PUT', '/admin/api/sales-actions'), ('POST', '/admin/api/mode'),
    ('POST', '/admin/api/website-knowledge/import'),
    ('POST', '/admin/api/test-agent'), ('POST', '/admin/api/accounts'),
    ('PUT', '/admin/api/accounts/unknown'),
    ('POST', '/admin/api/join-requests/unknown'),
    ('PUT', '/admin/api/leads/unknown'),
    ('POST', '/admin/api/recorded-sales'),
    ('POST', '/admin/api/recorded-sales/unknown/void'),
    ('POST', '/admin/api/whatsapp-qr'),
    ('PUT', '/files/raw/catalog.json'),
    ('POST', '/admin/api/ai-model/review'),
    ('POST', '/admin/api/ai-model/confirm'), ('PUT', '/admin/api/ai-model'),
    ('POST', '/billing/checkout'), ('POST', '/billing/discount'),
    ('POST', '/billing/portal'), ('POST', '/billing/whatsapp'),
    ('POST', '/billing/api-charge'),
)


def identity(client, role):
    with client.session_transaction() as state:
        set_test_identity(client, state, {'id': role, 'roles': [role], 'tenant': 'EXAMPLE'})


def test_every_management_data_route_requires_login(client):
    for path in (*MANAGEMENT_READS, '/admin/api/tenants', '/admin/api/platform',
                 '/billing/companies', '/__diag/catalog_env'):
        response = client.get(path)
        assert response.status_code == 401, (path, response.status_code)
    for method, path in (*MANAGEMENT_WRITES, ('POST', '/admin/api/tenants')):
        response = client.open(path, method=method, json={})
        assert response.status_code == 401, (method, path, response.status_code)


@pytest.mark.parametrize('role', ['business_owner', 'business_staff'])
def test_management_routes_reject_another_company_before_reading_or_writing(client, role):
    identity(client, role)
    for path in MANAGEMENT_READS:
        response = client.get(path + '?tenant=OTHER')
        assert response.status_code == 403, (role, path, response.status_code)
    for method, path in MANAGEMENT_WRITES:
        response = client.open(path + '?tenant=OTHER', method=method, json={})
        assert response.status_code == 403, (role, method, path, response.status_code)


def test_staff_cannot_use_owner_or_operator_controls(client):
    identity(client, 'business_staff')
    for path in ('/admin/api/accounts', '/admin/api/join-requests',
                 '/admin/api/sales-actions', '/admin/api/action-requests',
                 '/admin/api/tenants', '/admin/api/platform', '/billing/companies',
                 '/billing/subscription', '/admin/api/api-usage', '/__diag/catalog_env'):
        assert client.get(path).status_code == 403, path
    for method, path in (
        ('POST', '/admin/api/tenants'), ('POST', '/admin/api/accounts'),
        ('PUT', '/admin/api/accounts/unknown'),
        ('POST', '/admin/api/join-requests/unknown'),
        ('PUT', '/admin/api/sales-actions'), ('POST', '/admin/api/recorded-sales'),
        ('POST', '/admin/api/recorded-sales/unknown/void'),
        ('POST', '/admin/api/ai-model/review'),
        ('POST', '/admin/api/ai-model/confirm'), ('PUT', '/admin/api/ai-model'),
        ('POST', '/billing/checkout'), ('POST', '/billing/discount'),
        ('POST', '/billing/portal'), ('POST', '/billing/whatsapp'),
        ('POST', '/billing/api-charge'),
    ):
        assert client.open(path, method=method, json={}).status_code == 403, path


def test_foreign_lead_id_cannot_be_read_or_changed_in_the_own_company(client):
    analytics_db.upsert_lead(tenant='OTHER', lead_id='foreign-lead', name='Other private customer')
    identity(client, 'business_owner')
    assert client.put('/admin/api/leads/foreign-lead', json={'status': 'Won'}).status_code == 404
    leads = client.get('/admin/api/leads')
    assert leads.status_code == 200
    assert 'Other private customer' not in leads.text
    assert analytics_db.get_leads(tenant='OTHER')[0]['status'] == 'Open'


@pytest.mark.parametrize('body', [
    '{"greeting":"First","greeting":"Second"}', '{"greeting":NaN}',
    '{"greeting":1e309}', '{"greeting":', 'null', '[]', 'false',
])
def test_invalid_widget_json_cannot_clear_approved_origins_or_mutate_data(client, tmp_business, body):
    identity(client, 'business_owner')
    storage = client.application.container.storage
    branding = storage.read_json('EXAMPLE', 'branding.json')
    branding['widget'] = {**branding.get('widget', {}),
                          'allowed_origins': ['https://approved.example.test'],
                          'greeting': 'Keep this greeting'}
    storage.write_json('EXAMPLE', 'branding.json', branding, snapshot=False)
    document = tmp_business / 'branding.json'
    before = document.read_bytes()
    response = client.put('/admin/api/widget', data=body, content_type='application/json')
    assert response.status_code == 400
    assert document.read_bytes() == before
    assert not storage.versions_root.exists()
    assert client.get('/admin/api/widget').json['widget']['allowed_origins'] == ['https://approved.example.test']


@pytest.mark.parametrize('body', ['null', '[]', '[{"mode":"V7"}]', 'false', '{"mode":NaN}'])
def test_invalid_mode_json_is_rejected_without_mutation(client, tmp_business, body):
    identity(client, 'business_owner')
    document = tmp_business / 'overrides.json'
    before = document.read_bytes()
    response = client.post('/admin/api/mode', data=body, content_type='application/json')
    assert response.status_code == 400
    assert document.read_bytes() == before


def test_empty_widget_object_keeps_its_existing_reset_behavior(client):
    identity(client, 'business_owner')
    assert client.put('/admin/api/widget', json={}).status_code == 200
