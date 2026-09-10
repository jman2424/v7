from __future__ import annotations
from tests.conftest import set_test_identity


def _as_platform_admin(client, tenant: str = "EXAMPLE") -> None:
    with client.session_transaction() as sess:
        set_test_identity(client, sess, {"id": "platform", "roles": ["platform_admin"], "tenant": tenant})


def _as_owner(client, tenant: str = "EXAMPLE") -> None:
    with client.session_transaction() as sess:
        set_test_identity(client, sess, {"id": "owner", "roles": ["business_owner"], "tenant": tenant})


def test_platform_operator_creates_tenant_owner_who_can_sign_in(client):
    _as_platform_admin(client)
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
    assert login.status_code == 200
    assert login.get_json()["user"]["roles"] == ["business_owner"]


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
