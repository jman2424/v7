"""First-party chat activation cannot waive a customer's verified payments."""
from dataclasses import replace

from service import session_store, subscriptions, tenant_access
from service.tenant_service import TenantService
from tests.test_subscriptions import identity


def configure(client, tenant):
    container = client.application.container
    container.settings = replace(container.settings, PLATFORM_MARKETING_TENANT=tenant)


def activation(client, tenant):
    with client.application.app_context():
        return tenant_access.activation(tenant)


def create(client, tenant, owner=None):
    return TenantService(client.application.container.storage).create_tenant(tenant, tenant, owner=owner)


def test_only_explicit_platform_owned_business_is_exempt_and_disabling_revokes(client):
    create(client, 'INTERNAL')
    create(client, 'CUSTOMER')
    assert activation(client, 'INTERNAL')['active'] is False
    configure(client, 'INTERNAL')
    assert activation(client, 'INTERNAL') == {'active': True, 'status': 'platform_internal'}
    assert activation(client, 'CUSTOMER')['active'] is False
    assert client.get('/chat_ui?tenant=CUSTOMER').status_code == 403
    assert client.get('/widget.js?tenant=CUSTOMER').status_code == 403
    with subscriptions.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM billing_contracts').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM billing_invoices').fetchone()[0] == 0
    configure(client, '')
    assert activation(client, 'INTERNAL')['active'] is False
    assert client.get('/chat_ui?tenant=INTERNAL').status_code == 403


def test_owner_assigned_business_cannot_use_the_exemption(client):
    owner = {'id': 'owner', 'email': 'owner@example.test', 'tenant': 'EXAMPLE', 'roles': ['business_owner']}
    create(client, 'CUSTOMER', owner=owner)
    configure(client, 'CUSTOMER')
    assert activation(client, 'CUSTOMER')['active'] is False
    assert client.get('/widget.js?tenant=CUSTOMER').status_code == 403
    # Even an empty owner string is not a platform-admin NULL ownership record.
    with session_store.connection() as db:
        db.execute('UPDATE managed_businesses SET owner=? WHERE tenant=?', ('', 'CUSTOMER'))
    assert activation(client, 'CUSTOMER')['active'] is False


def test_exact_configuration_does_not_exempt_another_case_or_company(client):
    create(client, 'INTERNAL')
    create(client, 'INTERNAL_OTHER')
    configure(client, 'internal')
    assert activation(client, 'INTERNAL')['active'] is False
    assert client.get('/widget.js?tenant=INTERNAL').status_code == 403
    configure(client, 'INTERNAL')
    assert client.get('/chat_ui?tenant=internal').status_code in {200, 404}
    assert activation(client, 'INTERNAL_OTHER')['active'] is False


def test_exempt_agent_still_checks_management_session_tenant_and_origin(client):
    create(client, 'INTERNAL')
    configure(client, 'INTERNAL')
    assert client.get('/widget.js?tenant=INTERNAL').status_code == 200
    assert client.get('/chat_ui?tenant=INTERNAL').status_code == 200
    assert client.post('/admin/api/test-agent?tenant=INTERNAL', json={'message': 'hello'}).status_code == 401
    identity(client, role='business_owner')
    assert client.post('/admin/api/test-agent?tenant=INTERNAL', json={'message': 'hello'}).status_code == 403
    identity(client)
    assert client.post('/admin/api/test-agent?tenant=INTERNAL', json={'message': 'hello'}).status_code == 200
    assert client.post('/chat_api', json={'tenant': 'INTERNAL', 'message': 'hello'},
                       headers={'Origin': 'https://unapproved.example.test'}).status_code == 403


def test_tenant_creation_payload_cannot_request_an_exemption(client):
    identity(client, role='business_owner')
    configure(client, 'CUSTOMER')
    result = client.post('/admin/api/tenants', json={
        'key': 'CUSTOMER', 'name': 'Customer', 'active': True,
        'platform_internal': True, 'owner': None,
    })
    assert result.status_code == 201
    assert result.json['tenant']['activation']['active'] is False
    assert client.post('/chat_api', json={'tenant': 'CUSTOMER', 'message': 'hello'}).status_code == 403
