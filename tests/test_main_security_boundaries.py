"""Regression tests for request, catalog and filesystem security boundaries."""
import hashlib
import hmac
import io
import json
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlunsplit

import pytest
from flask import Flask

from app.config import load_settings
from app.middleware import install_rate_limit, install_request_id
from connectors.sheets import SheetsClient
from connectors.web_widget import WidgetBridge, canonical_origin
from retrieval.storage import Storage
from tests import test_platform_security as platform_tests

platform = platform_tests.platform


@pytest.mark.parametrize("path, method", [("/chat_api", "POST"), ("/admin/api/insights", "GET"),
    ("/files/raw/catalog.json", "PUT"), ("/healthz", "GET")])
def test_configured_limit_is_enforced_for_every_request_category(monkeypatch, path, method):
    app = Flask(__name__)
    install_request_id(app)
    install_rate_limit(app, SimpleNamespace(RATE_LIMIT_PER_MIN=2, RATE_LIMIT_BURST=0))
    app.add_url_rule(path, view_func=lambda: "ok", methods=[method])
    monkeypatch.setattr("app.middleware.time.monotonic", lambda: 100)
    client = app.test_client()
    statuses = [client.open(path, method=method).status_code for _ in range(3)]
    assert statuses == [200, 200, 429]
    assert client.open(path, method=method).headers["Retry-After"] == "60"


def test_switching_categories_cannot_bypass_the_global_bucket(monkeypatch):
    app = Flask(__name__)
    install_rate_limit(app, SimpleNamespace(RATE_LIMIT_PER_MIN=2, RATE_LIMIT_BURST=0))
    for path in ["/chat_api", "/admin/api/test", "/healthz"]:
        app.add_url_rule(path, endpoint=path, view_func=lambda: "ok", methods=["GET", "POST"])
    monkeypatch.setattr("app.middleware.time.monotonic", lambda: 100)
    client = app.test_client()
    assert client.post("/chat_api").status_code == 200
    assert client.get("/admin/api/test").status_code == 200
    assert client.get("/healthz").status_code == 429


@pytest.mark.parametrize("raw", [b'{"email":"a","email":"b"}', b'{"n":NaN}',
    b'{"n":Infinity}', b'{"n":1e999}', b'{"broken":', b'{"n":' + b'[' * 34 + b'0' + b']' * 34 + b'}'])
def test_invalid_json_cannot_reach_routes(platform, raw):
    client = platform[0].test_client()
    assert client.post("/chat_api", data=raw, content_type="application/json").status_code == 400


def test_duplicate_query_and_rest_body_limit(platform):
    client = platform[0].test_client()
    assert client.get("/healthz?tenant=ALPHA&tenant=BETA").status_code == 400
    assert client.post("/api/v1/chat", data=b" " * 65537, content_type="application/json").status_code == 413
    assert client.get("/version").status_code == 401


# Build synthetic user-info at runtime while preserving the hostile URL case.
_SYNTHETIC_CREDENTIAL_URL = urlunsplit((
    'https', "{}:{}@{}".format('user', 'password', 'site.test'),
    '', '', '',
))

@pytest.mark.parametrize("setting, value", [
    ("BASE_URL", "http://sales.example.test"), ("BASE_URL", _SYNTHETIC_CREDENTIAL_URL),
    ("BASE_URL", "https://site.test/path"), ("BASE_URL", "https://site.test:99999"),
    ("BASE_URL", "https://site.test\n"), ("BASE_URL", "https://site.test\\evil"),
    ("WHATSAPP_API_URL", "http://api.test"), ("WHATSAPP_API_URL", "https://api.test:0"),
    ("WHATSAPP_API_URL", "https://api.test?token=private"),
])
def test_unsafe_configured_urls_fail_at_startup(setting, value):
    with pytest.raises(RuntimeError):
        load_settings({"SECRET_KEY": "test-secret-" * 4, setting: value})


def test_settings_and_sheets_repr_hide_credentials():
    settings = load_settings({"SECRET_KEY": "private-secret-" * 4, "WHATSAPP_TOKEN": "provider-secret",
        "WHATSAPP_APP_SECRET": "signature-secret", "TWILIO_AUTH_TOKEN": "twilio-secret",
        "SHEETS_SERVICE_JSON": "service-private"})
    for value in [settings.SECRET_KEY, "provider-secret", "signature-secret", "twilio-secret", "service-private"]:
        assert value not in repr(settings)
    assert "sheet-secret" not in repr(SheetsClient("https://sheets.test", "sheet-secret"))


@pytest.mark.parametrize("value", ["https://user@shop.test", "https://shop.test/path", "https://shop.test?x=1", "https://shop.test\n"])
def test_widget_origins_are_exact(value):
    assert canonical_origin(value) == ""


def test_empty_widget_allowlist_is_not_replaced_with_defaults():
    bridge = WidgetBridge(allowed_origins=[])
    assert not bridge.validate_origin("http://localhost")


def test_sheets_import_never_adopts_blank_or_foreign_tenant_rows(monkeypatch):
    values = [["tenant", "category", "subcategory", "name", "price_str", "stock"],
        ["", "Devices", "", "Shared secret", "10", "yes"],
        ["BETA", "Devices", "", "Beta secret", "10", "yes"],
        ["ALPHA", "Devices", "", "Alpha item", "10", "yes"]]
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: io.BytesIO(json.dumps({"values": values}).encode()))
    client = SheetsClient("https://sheets.test", "key", export_sheet="test")
    result = client.import_catalog("ALPHA")
    assert [item["name"] for category in result["product_catalog"] for item in category["items"]] == ["Alpha item"]
    assert client.import_catalog("") is None


def test_legacy_loader_rejects_paths_outside_tenant_documents(tmp_path):
    root = tmp_path / "business"
    (root / "ALPHA").mkdir(parents=True)
    (root / "ALPHA/catalog.json").write_text('{}')
    outside = tmp_path / "private.json"
    outside.write_text('{"private":true}')
    storage = Storage(base_dir=root)
    assert storage.load_json("ALPHA/catalog.json") == {}
    assert storage.load_json(str(root / "ALPHA/catalog.json")) == {}
    for path in [str(outside), "../private.json", "ALPHA/../catalog.json", "versions/day/ALPHA/catalog.json"]:
        with pytest.raises(ValueError):
            storage.load_json(path)


@pytest.mark.parametrize("key", ["CON", "aux", "Lpt1", "NUL", "COM9"])
def test_windows_device_names_cannot_be_tenant_keys(key):
    with pytest.raises(ValueError):
        Storage.validate_tenant_key(key)


def _alias(monkeypatch, source, destination):
    """Exercise path resolution on Windows without requiring symlink privileges."""
    original = Path.resolve
    def resolve(path, *args, **kwargs):
        if path == source:
            return destination
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "resolve", resolve)


@pytest.mark.parametrize("operation", ["file", "loader", "audit", "snapshot_source", "snapshot_target", "lock"])
def test_aliases_never_read_or_overwrite_foreign_files(tmp_path, monkeypatch, operation):
    storage = Storage(base_dir=tmp_path / "business")
    alpha, beta = storage.tenant_dir("ALPHA"), storage.tenant_dir("BETA")
    alpha.mkdir(parents=True)
    beta.mkdir()
    for directory in [alpha, beta]:
        (directory / "catalog.json").write_text('{}')
        (directory / "audit.log.jsonl").write_text('{}\n')
    before = (beta / "catalog.json").read_bytes()
    source = alpha / ("audit.log.jsonl" if operation == "audit" else "catalog.json")
    if operation == "snapshot_target":
        snapshot = storage.versions_day_dir(tenant="ALPHA")
        snapshot.mkdir(parents=True)
        source = snapshot / "catalog.json"
    elif operation == "lock":
        source = storage.business_root / ".write-lock.sqlite3"
    _alias(monkeypatch, source, beta / "catalog.json")
    with pytest.raises(ValueError):
        if operation == "file":
            storage.read_json("ALPHA", "catalog.json")
        elif operation == "loader":
            storage.load_json("ALPHA/catalog.json")
        elif operation == "audit":
            storage.list_audit_entries("ALPHA")
        else:
            storage.write_json("ALPHA", "faq.json" if operation == "snapshot_source" else "catalog.json", {})
    assert (beta / "catalog.json").read_bytes() == before


def _signed_catalog(client, rows, secret, query=""):
    raw = json.dumps({"rows": rows}).encode()
    timestamp = str(int(time.time()))
    digest = hmac.new(secret.encode(), timestamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return client.post("/catalog_webhook" + query, data=raw, content_type="application/json",
        headers={"X-Catalog-Signature": f"t={timestamp},s={digest}"})


def test_signed_catalog_replay_cannot_undo_a_later_owner_edit(platform, monkeypatch):
    app = platform[0]
    secret = "catalog-test-secret"
    monkeypatch.setenv("CATALOG_WEBHOOK_SECRET", secret)
    monkeypatch.setattr(time, "time", lambda: 1900000000)
    client = app.test_client()
    rows = [{"category": "Devices", "name": "Imported", "price_str": "25"}]
    assert _signed_catalog(client, rows, secret, "?tenant=BETA").status_code == 400
    before_beta = app.container.storage.read_json("BETA", "catalog.json")
    first = _signed_catalog(client, rows, secret)
    assert first.status_code == 200, first.json
    later = {"version": 1, "categories": []}
    app.container.storage.write_json("ALPHA", "catalog.json", later)
    replay = _signed_catalog(client, rows, secret)
    assert replay.json == first.json
    assert app.container.storage.read_json("ALPHA", "catalog.json") == later
    assert app.container.storage.read_json("BETA", "catalog.json") == before_beta


@pytest.mark.parametrize("prepared", [False, True])
def test_catalog_import_fails_closed_if_audit_cannot_be_written(platform, monkeypatch, prepared):
    app = platform[0]
    before = app.container.storage.read_json("ALPHA", "catalog.json")
    monkeypatch.setenv("CATALOG_WEBHOOK_SECRET", "secret")
    def record(*args, **kwargs):
        if not prepared or kwargs["extra"]["result"] == "prepared":
            raise OSError("Test-only audit failure")
    monkeypatch.setattr("service.audit.AuditService.record", record)
    response = _signed_catalog(app.test_client(), [{"category": "Devices", "name": "Imported", "price_str": "25"}], "secret")
    assert response.status_code == 500
    assert app.container.storage.read_json("ALPHA", "catalog.json") == before


def test_file_write_fails_closed_on_audit_failure(platform, monkeypatch):
    client = platform[0].test_client()
    csrf = platform_tests.login(client)
    before = client.get("/files/raw/faq.json").json
    def record(*args, **kwargs):
        raise OSError("Test-only audit failure")
    monkeypatch.setattr("service.audit.AuditService.record", record)
    response = client.put("/files/raw/faq.json", json=[{"q": "Private?", "a": "No"}], headers={"X-CSRF-Token": csrf})
    assert response.status_code == 500
    assert client.get("/files/raw/faq.json").json == before


def test_file_editor_requires_json_content_type(platform):
    client = platform[0].test_client()
    csrf = platform_tests.login(client)
    response = client.put("/files/raw/faq.json", data='[{"q":"First","q":"Second","a":"Value"}]',
        content_type="text/plain", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 415
