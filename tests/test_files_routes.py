from __future__ import annotations

import shutil
from pathlib import Path


def _add_tenant(app, name: str = "ALT") -> None:
    business_root = Path(app.container.storage.business_root)
    source = business_root / "EXAMPLE"
    target = business_root / name
    if not target.exists():
        shutil.copytree(source, target)


def _as_owner(client, tenant: str = "EXAMPLE") -> None:
    with client.session_transaction() as sess:
        sess["user"] = {"id": "owner", "roles": ["business_owner"], "tenant": tenant}


def test_raw_files_use_signed_in_owner_tenant(client, app):
    _add_tenant(app)
    _as_owner(client)

    own_catalog = client.get("/files/raw/catalog.json")
    other_catalog = client.get("/files/raw/catalog.json?tenant=ALT")

    assert own_catalog.status_code == 200
    assert own_catalog.get_json()["categories"]
    assert other_catalog.status_code == 403


def test_raw_files_allow_only_known_tenant_configuration(client):
    _as_owner(client)

    account_file = client.get("/files/raw/users.json")
    traversal = client.get("/files/raw/../store_info.json")

    assert account_file.status_code == 404
    assert traversal.status_code == 404
