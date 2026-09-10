from __future__ import annotations

from conftest import set_test_identity


def test_catalog_webhook_reads_the_active_tenant_catalog(client, monkeypatch):
    monkeypatch.delenv("CATALOG_FILE", raising=False)
    with client.session_transaction() as state:
        set_test_identity(client, state, {"email": "admin@example.com", "roles": ["platform_admin"]})

    response = client.get("/catalog_webhook")

    assert response.status_code == 200
    catalog = response.get_json()
    assert isinstance(catalog.get("categories"), list)
    assert catalog["categories"]
