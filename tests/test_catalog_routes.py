from __future__ import annotations


def test_catalog_webhook_reads_the_active_tenant_catalog(client, monkeypatch):
    monkeypatch.delenv("CATALOG_FILE", raising=False)

    response = client.get("/catalog_webhook")

    assert response.status_code == 200
    catalog = response.get_json()
    assert isinstance(catalog.get("categories"), list)
    assert catalog["categories"]
