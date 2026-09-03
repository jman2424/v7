from __future__ import annotations


def _as_platform_admin(client, tenant: str = "EXAMPLE") -> None:
    with client.session_transaction() as sess:
        sess["user"] = {"id": "platform", "roles": ["platform_admin"], "tenant": tenant}


def _as_owner(client, tenant: str = "EXAMPLE") -> None:
    with client.session_transaction() as sess:
        sess["user"] = {"id": "owner", "roles": ["business_owner"], "tenant": tenant}


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
