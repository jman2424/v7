from __future__ import annotations
from unittest.mock import Mock
import pytest

from service.account_service import ACCOUNT_FILE, AccountService
from service.security import verify_password
from tests.conftest import set_test_identity


def _as_platform_admin(client, tenant: str = "EXAMPLE") -> None:
    with client.session_transaction() as sess:
        set_test_identity(client, sess, {"id": "platform", "roles": ["platform_admin"], "tenant": tenant})


def _as_owner(client, tenant: str = "EXAMPLE") -> None:
    with client.session_transaction() as sess:
        set_test_identity(client, sess, {"id": "owner", "roles": ["business_owner"], "tenant": tenant})


def test_platform_operator_creates_tenant_owner_who_can_sign_in(client):
    _as_platform_admin(client)
    assert client.post('/admin/api/tenants', json={'key':'OTHER','name':'Other company'}).status_code == 201
    created = client.post(
        "/admin/api/accounts",
        json={
            "email": "owner@example.test",
            "password": "correct-horse-battery-staple",
            "roles": ["business_owner"],
        },
    )

    assert created.status_code == 201
    account = created.get_json()["account"]
    assert account["email"] == "owner@example.test"
    assert account["roles"] == ["business_owner"]
    assert "password_hash" not in account
    assert "password" not in account

    login = client.post(
        "/auth/login",
        json={"email": "owner@example.test", "password": "correct-horse-battery-staple", "tenant": "EXAMPLE"},
    )
    assert login.status_code == 202
    from service.security import generate_totp_token
    login = client.post('/auth/mfa/confirm', json={'code':generate_totp_token(login.json['mfa']['setup_key'])})
    assert login.status_code == 200
    assert login.get_json()["user"]["roles"] == ["business_owner"]
    assert login.get_json()["user"]["tenant"] == 'EXAMPLE'
    for path in ('catalog','statistics','api-usage','accounts'):
        assert client.get(f'/admin/api/{path}?tenant=OTHER').status_code == 403
    assert [row['key'] for row in client.get('/admin/api/tenants').json['tenants']] == ['EXAMPLE']
    assert client.put('/admin/api/catalog?tenant=OTHER', json={'version':1,'categories':[]}).status_code == 403
    # The same credentials cannot select another company at sign-in either.
    other = client.post('/auth/login', json={'email':'owner@example.test',
        'password':'correct-horse-battery-staple','tenant':'OTHER'})
    assert other.status_code == 401


def test_owner_can_create_staff_but_not_another_owner(client):
    _as_owner(client)

    staff = client.post(
        "/admin/api/accounts",
        json={"email": "staff@example.test", "password": "correct-horse-battery-staple", "roles": ["business_staff"]},
    )
    owner = client.post(
        "/admin/api/accounts",
        json={"email": "other@example.test", "password": "correct-horse-battery-staple", "roles": ["business_owner"]},
    )

    assert staff.status_code == 201
    assert owner.status_code == 403


def test_account_listing_never_returns_password_material(client):
    _as_platform_admin(client)
    client.post(
        "/admin/api/accounts",
        json={"email": "owner@example.test", "password": "correct-horse-battery-staple", "roles": ["business_owner"]},
    )

    listed = client.get("/admin/api/accounts")

    assert listed.status_code == 200
    assert listed.get_json()["accounts"] == [
        {
            "id": listed.get_json()["accounts"][0]["id"],
            "email": "owner@example.test",
            "roles": ["business_owner"],
            "active": True,
            "permissions": [],
        }
    ]


def test_owner_can_disable_and_reset_a_staff_account(client):
    _as_owner(client)
    created = client.post(
        "/admin/api/accounts",
        json={"email": "staff@example.test", "password": "correct-horse-battery-staple", "roles": ["business_staff"]},
    ).get_json()["account"]

    updated = client.put(
        f"/admin/api/accounts/{created['id']}",
        json={"active": False, "password": "a-new-long-staff-password"},
    )

    assert updated.status_code == 200
    assert updated.get_json()["account"] == {
        "id": created["id"],
        "email": "staff@example.test",
        "roles": ["business_staff"],
        "active": False,
        "permissions": [],
    }


def test_owner_cannot_disable_another_owner(client):
    _as_platform_admin(client)
    created = client.post(
        "/admin/api/accounts",
        json={"email": "other-owner@example.test", "password": "correct-horse-battery-staple", "roles": ["business_owner"]},
    ).get_json()["account"]
    _as_owner(client)

    blocked = client.put(f"/admin/api/accounts/{created['id']}", json={"active": False})

    assert blocked.status_code == 403


def test_disabled_account_loses_management_access_on_its_next_request(client):
    _as_platform_admin(client)
    created = client.post(
        "/admin/api/accounts",
        json={"email": "staff@example.test", "password": "correct-horse-battery-staple", "roles": ["business_staff"]},
    ).get_json()["account"]
    client.put(f"/admin/api/accounts/{created['id']}", json={"active": False})

    with client.session_transaction() as sess:
        sess["user"] = {"id": created["id"], "roles": ["business_staff"], "tenant": "EXAMPLE"}

    denied = client.get("/admin/api/catalog")

    assert denied.status_code == 401
    with client.session_transaction() as sess:
        assert "user" not in sess


def test_disabled_account_loses_legacy_file_access_on_its_next_request(client):
    _as_platform_admin(client)
    created = client.post(
        "/admin/api/accounts",
        json={"email": "staff@example.test", "password": "correct-horse-battery-staple", "roles": ["business_staff"]},
    ).get_json()["account"]
    client.put(f"/admin/api/accounts/{created['id']}", json={"active": False})

    with client.session_transaction() as sess:
        sess["user"] = {"id": created["id"], "roles": ["business_staff"], "tenant": "EXAMPLE"}

    denied = client.get("/files/raw/catalog.json")

    assert denied.status_code == 401
    with client.session_transaction() as sess:
        assert "user" not in sess


@pytest.mark.parametrize("length", [254, 255, 320])
def test_managed_account_email_length_matches_authentication(app, length):
    service = AccountService(app.container.storage)
    email = "a" * (length - len("@example.test")) + "@example.test"
    payload = {"email": email, "password": "Account-password-only-123", "roles": ["business_staff"]}
    if length > 254:
        with pytest.raises(ValueError, match="invalid_account_email"):
            service.create_account("EXAMPLE", payload)
        assert service.list_accounts("EXAMPLE") == []
    else:
        created = service.create_account("EXAMPLE", payload)
        assert created["email"] == email
        from service.security import authenticate_user
        with app.app_context():
            assert authenticate_user(app.container, email=email, password=payload["password"], tenant="EXAMPLE")


def test_managed_accounts_and_password_resets_preserve_long_passwords(app):
    service = AccountService(app.container.storage)
    prefix = "a" * 72
    account = service.create_account("EXAMPLE", {
        "email": "long-password@example.test", "password": prefix + "original",
        "roles": ["business_staff"],
    })
    stored = app.container.storage.read_json("EXAMPLE", ACCOUNT_FILE)[0]
    assert stored["password_hash"].startswith("scrypt:")
    assert verify_password(prefix + "original", stored["password_hash"])
    assert not verify_password(prefix + "different", stored["password_hash"])
    service.update_account("EXAMPLE", account["id"], {"password": prefix + "reset"})
    stored = app.container.storage.read_json("EXAMPLE", ACCOUNT_FILE)[0]
    assert verify_password(prefix + "reset", stored["password_hash"])
    assert not verify_password(prefix + "original", stored["password_hash"])


@pytest.mark.parametrize('email', ['résumé@example.test', 'owner@例子.test', 'one,two@example.test', 'Name<one@example.test>'])
def test_managed_account_email_validation_matches_signup(app, email):
    service = AccountService(app.container.storage)
    with pytest.raises(ValueError, match='invalid_account_email'):
        service.create_account('EXAMPLE', {'email': email, 'password': 'Account-test-password-123',
                                          'roles': ['business_staff']})
    assert service.list_accounts('EXAMPLE') == []


@pytest.mark.parametrize('email', ['!' * 8192, 'owner@' + '-.' * 8192 + '!'])
def test_oversized_account_email_is_rejected_before_regex_evaluation(app, monkeypatch, email):
    from service import account_service

    regex = Mock()
    regex.fullmatch.side_effect = AssertionError('Oversized account email reached regex evaluation')
    monkeypatch.setattr(account_service, '_EMAIL_RE', regex)
    service = AccountService(app.container.storage)
    with pytest.raises(ValueError, match='invalid_account_email'):
        service.create_account('EXAMPLE', {'email': email, 'password': 'Account-test-password-123',
                                          'roles': ['business_staff']})
    regex.fullmatch.assert_not_called()
    assert service.list_accounts('EXAMPLE') == []


def test_legacy_unicode_account_records_do_not_block_ascii_creation(app):
    storage = app.container.storage
    legacy = {'id':'account:历史', 'email':'résumé@example.test',
              'roles':['business_staff'], 'active':True, 'permissions':[]}
    storage.write_json('EXAMPLE', ACCOUNT_FILE, [legacy])
    service = AccountService(storage)
    created = service.create_account('EXAMPLE', {'email':'new@example.test',
        'password':'Account-test-password-123', 'roles':['business_staff']})
    assert created['email'] == 'new@example.test'
    assert service.get_account('EXAMPLE', legacy['id']) == legacy
    assert service.update_account('EXAMPLE', legacy['id'], {'active':False})['active'] is False
    assert len(service.list_accounts('EXAMPLE')) == 2


def test_unknown_unicode_account_id_remains_not_found(client):
    _as_platform_admin(client)
    client.post('/admin/api/accounts', json={'email':'staff@example.test',
        'password':'Account-test-password-123', 'roles':['business_staff']})
    response = client.put('/admin/api/accounts/account:未知', json={'active':False})
    assert response.status_code == 404
    assert response.get_json() == {'error':'account_not_found'}
