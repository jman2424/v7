"""An operator can explicitly repair an owner without broadening staff access."""
import pytest

from service.account_service import AccountService
from service.security import OWNER_PERMISSIONS, authenticate_user, has_permission
from tests.test_account_management import _as_owner, _as_platform_admin


def create(client, role='business_owner', permissions=None):
    _as_platform_admin(client)
    response = client.post('/admin/api/accounts', json={
        'email': 'repair@example.test', 'password': 'Synthetic-test-password-42!',
        'roles': [role], 'permissions': permissions or []})
    assert response.status_code == 201
    return response.json['account']


def test_operator_restores_only_tenant_owner_permissions_and_revokes_old_revision(client):
    account = create(client)
    service = AccountService(client.application.container.storage)
    before = service.get_account('EXAMPLE', account['id'])
    response = client.put('/admin/api/accounts/'+account['id'], json={'restore_owner_access': True})
    assert response.status_code == 200
    assert set(response.json['account']['permissions']) == OWNER_PERMISSIONS
    assert not {'platform.read', 'models.read', 'models.write'} & set(response.json['account']['permissions'])
    after = service.get_account('EXAMPLE', account['id'])
    assert after.get('credential_version') != before.get('credential_version')
    assert after['password_hash'] == before['password_hash']
    assert after.get('totp_secret') == before.get('totp_secret')
    with client.application.test_request_context():
        user = authenticate_user(client.application.container, email=account['email'],
                                 password='Synthetic-test-password-42!', tenant='EXAMPLE')
        assert has_permission(user, 'business_settings.write')
        assert has_permission(user, 'offerings.write')
        assert not has_permission(user, 'platform.read')


def test_owner_cannot_invoke_operator_restore_for_staff(client):
    account = create(client, 'business_staff')
    _as_owner(client)
    assert client.put('/admin/api/accounts/'+account['id'], json={'restore_owner_access': True}).status_code == 403


def test_restore_does_not_convert_staff_to_owner(client):
    account = create(client, 'business_staff')
    assert client.put('/admin/api/accounts/'+account['id'], json={'restore_owner_access': True}).status_code == 400


@pytest.mark.parametrize('value', [False, 'true', 1, None])
def test_restore_requires_explicit_boolean(client, value):
    account = create(client)
    assert client.put('/admin/api/accounts/'+account['id'], json={'restore_owner_access': value}).status_code == 400


def test_ordinary_owner_edits_preserve_explicit_permission_subset(client):
    account = create(client, permissions=['offerings.read'])
    response = client.put('/admin/api/accounts/'+account['id'], json={'active': True})
    assert response.status_code == 200
    assert response.json['account']['permissions'] == ['offerings.read']
