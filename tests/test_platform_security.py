"""Regression tests against real routes, storage and two isolated companies."""
import base64
import hashlib
import hmac
import json
import struct
import time
from pathlib import Path
from unittest.mock import Mock

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from app.config import load_settings
from service import analytics_db
from service.security import verify_totp


@pytest.fixture
def platform(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    monkeypatch.setenv("SECURITY_DB_PATH", str(tmp_path / "security.db"))
    for key in ["ADMIN_USERNAME", "ADMIN_PASSWORD", "ADMIN_PASSWORD_HASH", "ADMIN_TOTP_SECRET",
                "OPENAI_API_KEY", "WHATSAPP_APP_SECRET", "WHATSAPP_VERIFY_TOKEN",
                "WHATSAPP_TOKEN", "WHATSAPP_PHONE_ID", "TWILIO_AUTH_TOKEN", "TWILIO_WHATSAPP_NUMBER"]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(analytics_db, "DB_PATH", str(tmp_path / "analytics.db"))
    monkeypatch.setattr(analytics_db, "_INIT_DONE", False)
    monkeypatch.setattr("app.app_factory.configure_logging", lambda settings: None)
    for tenant, product in [("ALPHA", "Alpha laptop"), ("BETA", "Beta tablet")]:
        root = tmp_path / "business" / tenant
        root.mkdir(parents=True)
        files = {
            "catalog.json": {"version": 1, "categories": [{"id": "devices", "name": "Devices",
                "items": [{"sku": tenant + "_1", "name": product, "price": 25, "in_stock": True}]}]},
            "faq.json": [{"q": "Opening hours?", "a": tenant + " is open from 9 to 5."}],
            "branches.json": [], "delivery.json": {}, "synonyms.json": {},
            "overrides.json": {"ai": {"mode": "v7"}}, "branding.json": {"widget": {"greeting": "Hello from " + tenant}},
            "store_info.json": {"name": tenant},
        }
        for filename, value in files.items():
            (root / filename).write_text(json.dumps(value), encoding="utf-8")
    password = "Test-only-password-42!"
    hashed = generate_password_hash(password)
    registry = tmp_path / "accounts.json"
    registry.write_text(json.dumps({"users": [
        {"email": "admin@example.test", "password_hash": hashed, "role": "platform_admin"},
        {"email": "owner@example.test", "password_hash": hashed, "role": "business_owner", "tenant": "ALPHA"},
    ]}), encoding="utf-8")
    monkeypatch.setenv("ADMIN_USERS_FILE", str(registry))
    app = create_app({"TESTING": True, "MODE": "V7", "BUSINESS_KEY": "ALPHA", "SECRET_KEY": "test-secret-" * 4})
    return app, registry, password


def login(client, email="owner@example.test", password="Test-only-password-42!"):
    csrf = client.get("/auth/session").json["csrf_token"]
    response = client.post("/auth/login", json={"email": email, "password": password},
                           headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200, response.json
    return response.json["csrf_token"]


@pytest.mark.parametrize("path", ["/admin/api/insights", "/admin/api/platform", "/admin/api/conversations",
    "/files/raw/catalog.json", "/analytics/kpis.json", "/__diag/validate", "/catalog_webhook", "/export_catalog_csv", "/mode"])
def test_management_requires_login(platform, path):
    assert platform[0].test_client().get(path).status_code == 401


def test_login_requires_csrf_and_rotates_session(platform):
    client = platform[0].test_client()
    old = client.get("/auth/session").json["csrf_token"]
    assert client.post("/auth/login", json={"email": "owner@example.test", "password": platform[2]}).status_code == 403
    token = login(client)
    assert token != old
    with client.session_transaction() as session:
        assert "totp_secret" not in session["user"]
        assert "password_hash" not in str(dict(session))
    assert client.get("/admin/logout").status_code in {404, 405}


@pytest.mark.parametrize("path", ["/admin/api/insights", "/admin/api/conversations", "/files/raw/catalog.json",
    "/analytics/kpis.json", "/__diag/validate", "/catalog_webhook", "/export_catalog_csv", "/mode", "/admin/business"])
def test_owner_cannot_read_another_tenant(platform, path):
    client = platform[0].test_client()
    login(client)
    assert client.get(path + "?tenant=BETA").status_code == 403


def test_platform_only_companies_and_pages(platform):
    client = platform[0].test_client()
    login(client)
    assert client.get("/admin/companies").status_code == 403
    assert client.get("/admin/api/platform").status_code == 403
    resources = {"business", "settings", "products", "faqs", "branches", "delivery"}
    for page in ["overview", "business", "settings", "errors", "integrations", "conversations", "products", "faqs", "branches", "delivery"]:
        response = client.get("/admin/" + page)
        assert response.status_code == 200, response.data
        assert (b'id="resource-json"' in response.data) == (page in resources)
        assert b'aria-current="page"' in response.data
    other = platform[0].test_client()
    login(other, "admin@example.test")
    assert other.get("/admin/companies").status_code == 200
    assert {row["tenant"] for row in other.get("/admin/api/platform").json["companies"]} == {"ALPHA", "BETA"}
    assert "Beta tablet" in other.get("/files/raw/catalog.json?tenant=BETA").text


def test_logout_revokes_copied_cookie(platform):
    client = platform[0].test_client()
    token = login(client)
    stolen = client.get_cookie("session").value
    assert client.post("/auth/logout", headers={"X-CSRF-Token": token}).status_code == 200
    replay = platform[0].test_client()
    replay.set_cookie("session", stolen)
    assert replay.get("/admin/api/insights").status_code == 401


def test_disabling_account_revokes_session(platform):
    client = platform[0].test_client()
    login(client)
    records = json.loads(platform[1].read_text())
    records["users"][1]["disabled"] = True
    platform[1].write_text(json.dumps(records))
    assert client.get("/admin/api/insights").status_code == 401


def test_login_limit_cannot_be_bypassed_with_forwarded_headers(platform):
    client = platform[0].test_client()
    csrf = client.get("/auth/session").json["csrf_token"]
    statuses = [client.post("/auth/login", json={"email": "owner@example.test", "password": "wrong"},
        headers={"X-CSRF-Token": csrf, "X-Forwarded-For": f"192.0.2.{i}"}).status_code for i in range(7)]
    assert statuses[:5] == [401] * 5
    assert statuses[5:] == [429, 429]


def test_file_writes_scope_schema_csrf_and_snapshot(platform):
    client = platform[0].test_client()
    csrf = login(client)
    url = "/files/raw/faq.json"
    original = client.get(url).json
    payload = [{"q": "Where?", "a": "At our branch."}]
    assert client.put(url, json=payload).status_code == 403
    headers = {"X-CSRF-Token": csrf}
    assert client.put(url + "?tenant=BETA", json=payload, headers=headers).status_code == 403
    assert client.put(url, json=[{"bad": "schema"}], headers=headers).status_code == 400
    response = client.put(url, json=payload, headers=headers)
    assert response.status_code == 200, response.json
    storage = platform[0].container.storage
    assert json.loads((storage.versions_root / response.json["snapshot"]).read_text()) == original
    assert client.get(url).json == payload
    assert (Path.cwd() / "logs/selfrepair.log").exists()
    assert client.get("/files/raw/audit.log.jsonl").status_code == 404
    for tenant in ["../BETA", "versions", "/etc", "C:\\Windows"]:
        with pytest.raises(ValueError):
            storage.tenant_dir(tenant)
    with pytest.raises(ValueError):
        storage.file_path("ALPHA", "../BETA/catalog.json")


def test_chat_uses_scoped_catalog_and_protected_conversation(platform, monkeypatch):
    app = platform[0]
    seen = []
    for key in ["ALPHA", "BETA"]:
        scoped = app.container.for_tenant(key)
        def handle(text, *, tenant, session_id, **kwargs):
            seen.append((tenant, session_id))
            return {"reply": tenant + " reply", "intent": "faq", "private": "do-not-expose"}
        monkeypatch.setattr(scoped.handler, "handle", handle)
    client = app.test_client()
    first = client.post("/chat_api", json={"tenant": "ALPHA", "message": "Hello", "session_id": "chosen-by-attacker"})
    assert first.status_code == 200, first.json
    assert "raw" not in first.json and "do-not-expose" not in first.text
    token = first.json["conversation_token"]
    assert seen[0][1] != "chosen-by-attacker"
    assert client.post("/chat_api", json={"tenant": "BETA", "message": "Hello", "conversation_token": token}).status_code == 403
    assert client.post("/chat_api", json={"tenant": "ALPHA", "message": "Again", "conversation_token": token}).status_code == 200
    assert seen[0] == seen[1]
    assert app.container.for_tenant("ALPHA").catalog.storage.tenant_key == "ALPHA"
    assert app.container.for_tenant("BETA").catalog.storage.tenant_key == "BETA"


@pytest.mark.parametrize("payload", [[], None, {"message": []}, {"message": "x" * 4001}, {"tenant": "../BETA", "message": "Hi"}])
def test_chat_rejects_malformed_payloads(platform, payload):
    assert platform[0].test_client().post("/chat_api", json=payload).status_code in {400, 404, 415}


def test_chat_origin_and_missing_tenant(platform):
    client = platform[0].test_client()
    assert client.post("/chat_api", json={"message": "hello"}, headers={"Origin": "https://unapproved.example"}).status_code == 403
    assert client.get("/chat_ui?tenant=MISSING").status_code == 404
    assert client.get("/chat_ui?tenant=ALPHA").status_code == 200


def test_tenant_analytics_and_error_reporting(platform):
    client = platform[0].test_client()
    login(client)
    analytics_db.log_message(tenant="BETA", channel="web", direction="inbound", session_id="private", text="Beta private")
    analytics_db.log_error(tenant="ALPHA", channel="web", session_id="test", error_code="provider_failure")
    result = client.get("/admin/api/insights").json
    assert result["kpis"]["errors"] == 1
    assert result["kpis"]["total"] == 0
    assert "Beta private" not in json.dumps(result)
    assert not client.get("/admin/api/conversations").json["messages"]
    assert client.get("/admin/api/insights?limit=-1").status_code == 400


def test_totp_standard_unpadded_secret():
    secret = "JBSWY3DPEHPK3PXP"
    digest = hmac.new(base64.b32decode(secret), struct.pack(">Q", int(time.time()) // 30), hashlib.sha1).digest()
    offset = digest[-1] & 15
    code = str((struct.unpack(">I", digest[offset:offset+4])[0] & 0x7fffffff) % 1000000).zfill(6)
    assert verify_totp(secret, code)
    assert not verify_totp(secret, "invalid")
    assert not verify_totp("invalid", code)


def test_no_default_secret(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError):
        load_settings()


def test_response_security_headers(platform):
    response = platform[0].test_client().get("/admin/login")
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "script-src 'self' 'nonce-" in response.headers["Content-Security-Policy"]
    assert "HttpOnly" in response.headers["Set-Cookie"]


@pytest.mark.parametrize("setting", ["https", "production", "secure_cookie"])
def test_production_platform_login_explains_mfa_without_granting_access(platform, setting):
    from dataclasses import replace
    app = platform[0]
    if setting == "https":
        app.container.settings = replace(app.container.settings, BASE_URL="https://sales.example.test")
    elif setting == "production":
        app.container.settings = replace(app.container.settings, ENVIRONMENT="production")
    else:
        app.config["SESSION_COOKIE_SECURE"] = True
    client = app.test_client()
    csrf = client.get("/auth/session").json["csrf_token"]
    response = client.post("/auth/login", json={"email": "admin@example.test", "password": platform[2]},
                           headers={"X-CSRF-Token": csrf})
    assert response.status_code == 403
    assert response.json["error"] == "mfa_setup_required"
    assert "password was accepted" in response.json["message"]
    assert client.get("/admin/api/platform").status_code == 401


def test_mfa_setup_message_is_only_shown_after_correct_password(platform):
    from dataclasses import replace
    app = platform[0]
    app.container.settings = replace(app.container.settings, ENVIRONMENT="production")
    client = app.test_client()
    csrf = client.get("/auth/session").json["csrf_token"]
    response = client.post("/auth/login", json={"email": "admin@example.test", "password": "wrong"},
                           headers={"X-CSRF-Token": csrf})
    assert response.status_code == 401
    assert response.json["error"] == "invalid_credentials"
    response = client.post("/admin/login", data={"email": "admin@example.test", "password": platform[2],
                                                "csrf_token": csrf})
    assert response.status_code == 403
    assert "password was accepted" in response.text
    assert 'name="csrf_token"' in response.text
    assert platform[2] not in response.text
    assert client.get("/admin/api/platform").status_code == 401


def test_production_admin_keeps_password_after_authenticator_configuration(platform):
    from dataclasses import replace
    from service.security import generate_totp_secret, generate_totp_token
    app, registry, password = platform
    app.container.settings = replace(app.container.settings, ENVIRONMENT="production")
    secret = generate_totp_secret()
    records = json.loads(registry.read_text())
    records["users"][0]["totp_secret"] = secret
    registry.write_text(json.dumps(records))
    client = app.test_client()
    csrf = client.get("/auth/session").json["csrf_token"]
    credentials = {"email": "admin@example.test", "password": password}
    headers = {"X-CSRF-Token": csrf}
    assert client.post("/auth/login", json=credentials, headers=headers).status_code == 401
    response = client.post("/auth/login", json={**credentials, "totp": generate_totp_token(secret)}, headers=headers)
    assert response.status_code == 200
    assert client.get("/admin/api/platform").status_code == 200
    assert secret not in response.text
    with client.session_transaction() as state:
        assert secret not in str(dict(state))


def test_login_csrf_failure_has_recovery_message_and_fresh_form(platform):
    client = platform[0].test_client()
    response = client.post("/auth/login", json={"email": "owner@example.test", "password": platform[2]})
    assert response.status_code == 403
    assert response.json["error"] == "csrf_failed"
    assert "Reload the page" in response.json["message"]
    assert client.get("/admin/api/insights").status_code == 401
    form = client.post("/admin/login", data={"email": "owner@example.test", "password": platform[2]})
    assert form.status_code == 403
    assert 'name="csrf_token"' in form.text
    assert "Reload the page" in form.text


def test_widget_frame_allowlist_is_tenant_scoped(platform):
    branding = Path.cwd() / "business/ALPHA/branding.json"
    branding.write_text(json.dumps({"allowed_origins": ["https://shop.example.test"]}))
    client = platform[0].test_client()
    alpha = client.get("/chat_ui?tenant=ALPHA").headers["Content-Security-Policy"]
    beta = client.get("/chat_ui?tenant=BETA").headers["Content-Security-Policy"]
    assert "frame-ancestors 'self' https://shop.example.test" in alpha
    assert "shop.example.test" not in beta


def test_existing_branch_and_delivery_formats_can_be_saved(platform):
    client = platform[0].test_client()
    csrf = login(client)
    examples = Path(__file__).resolve().parents[1] / "business/TARIQ"
    for filename in ["branches.json", "delivery.json"]:
        payload = json.loads((examples / filename).read_text(encoding="utf-8"))
        result = client.put("/files/raw/" + filename, json=payload, headers={"X-CSRF-Token": csrf})
        assert result.status_code == 200, result.json
        assert client.get("/files/raw/" + filename).json == payload


def test_conversations_filter_time_without_leaking_other_companies(platform):
    client = platform[0].test_client()
    login(client)
    for tenant, message in [("ALPHA", "Old message"), ("ALPHA", "Current message"), ("BETA", "Private message")]:
        analytics_db.log_message(tenant=tenant, channel="web", direction="inbound", session_id="test", text=message)
    with analytics_db._conn() as db:
        db.execute("UPDATE events SET ts_utc='2000-01-01T00:00:00+00:00' WHERE text='Old message'")
    response = client.get("/admin/api/conversations?minutes=60")
    assert [row["text"] for row in response.json["messages"]] == ["Current message"]


def test_lead_export_scopes_and_neutralizes_spreadsheet_formulas(platform):
    client = platform[0].test_client()
    login(client)
    analytics_db.upsert_lead(tenant="ALPHA", lead_id="a", name="=1+1")
    analytics_db.upsert_lead(tenant="BETA", lead_id="b", name="Other tenant private name")
    response = client.get("/analytics/export.csv")
    assert response.status_code == 200
    assert "'=1+1" in response.text
    assert "Other tenant private name" not in response.text


def test_legacy_lead_write_fails_closed(platform, monkeypatch):
    analytics_db._ensure_ready()
    monkeypatch.setattr(analytics_db, "_table_columns", lambda *_: {"lead_id", "name", "phone"})
    with pytest.raises(RuntimeError, match="tenant migration"):
        analytics_db.upsert_lead(tenant="ALPHA", lead_id="shared-id", name="Private")


def test_agent_answers_company_faq_and_reloads_owner_edits(platform):
    client = platform[0].test_client()
    first = client.post("/chat_api", json={"tenant": "ALPHA", "message": "Opening hours?"})
    assert first.json["reply"] == "ALPHA is open from 9 to 5."
    csrf = login(client)
    result = client.put("/files/raw/faq.json", json=[{"q": "Opening hours?", "a": "Open until 7 today."}],
                        headers={"X-CSRF-Token": csrf})
    assert result.status_code == 200
    assert client.post("/chat_api", json={"tenant": "ALPHA", "message": "Opening hours?"}).json["reply"] == "Open until 7 today."
    assert client.post("/chat_api", json={"tenant": "BETA", "message": "Opening hours?"}).json["reply"] == "BETA is open from 9 to 5."


def test_agent_finds_tenant_products_and_never_invents_certification(platform):
    client = platform[0].test_client()
    response = client.post("/chat_api", json={"tenant": "ALPHA", "message": "laptop"})
    assert response.status_code == 200
    assert "Alpha laptop" in response.json["reply"]
    assert "Beta tablet" not in response.json["reply"]
    followup = client.post("/chat_api", json={"tenant": "ALPHA", "message": "are they halal",
                          "conversation_token": response.json["conversation_token"]})
    assert "our meat products are halal" not in followup.json["reply"]
    assert len(analytics_db.get_leads(tenant="ALPHA")) == 1


def test_catalog_does_not_return_unrelated_in_stock_items(platform):
    catalog = platform[0].container.for_tenant("ALPHA").catalog
    assert catalog.search(text="unicornspaceship") == []
    assert catalog.search(text="laptop")[0]["name"] == "Alpha laptop"


def test_agent_uses_saved_business_details_and_refreshes_existing_conversation(platform):
    client = platform[0].test_client()
    csrf = login(client)
    headers = {"X-CSRF-Token": csrf}
    profile = {"name": "Alpha technology", "about": "Repairs and devices.",
               "certifications": ["ISO 9001"], "social": {"instagram": "https://instagram.com/alpha_example"}}
    saved = client.put("/admin/api/profile", json=profile, headers=headers)
    assert saved.status_code == 200, saved.json
    first = client.post("/chat_api", json={"tenant": "ALPHA", "message": "What certifications do you have?"})
    assert "ISO 9001" in first.json["reply"]
    profile["certifications"] = ["B Corp"]
    assert client.put("/admin/api/profile", json=profile, headers=headers).status_code == 200
    updated = client.post("/chat_api", json={"tenant": "ALPHA", "message": "What certifications do you have?",
                         "conversation_token": first.json["conversation_token"]})
    assert "B Corp" in updated.json["reply"]
    assert "ISO 9001" not in updated.json["reply"]
    social = client.post("/chat_api", json={"tenant": "ALPHA", "message": "What is your Instagram?"})
    assert profile["social"]["instagram"] in social.json["reply"]
    branches = [{"id": "west", "name": "Westminster", "postcode": "SW1A 1AA", "lat": None, "lon": None,
                 "hours": {"mon": "10:00-16:00", "sun": "Closed"}, "holidays": ["2099-12-25"]}]
    saved = client.put("/admin/api/branches", json=branches, headers=headers)
    assert saved.status_code == 200, saved.json
    hours = client.post("/chat_api", json={"tenant": "ALPHA", "message": "What are Westminster opening hours?"})
    assert "10:00-16:00" in hours.json["reply"]
    assert "sun: Closed" in hours.json["reply"]
    other = client.post("/chat_api", json={"tenant": "BETA", "message": "What certifications do you have?"})
    assert "B Corp" not in other.json["reply"]


def test_agent_keeps_delivery_conditions_notices_and_collection_setting(platform):
    client = platform[0].test_client()
    csrf = login(client)
    delivery = {
        "zones": [{"area": "E1", "fee": 4, "min_order": 25, "eta_hours": "Next-day",
                   "notes": "Ground-floor delivery only."}],
        "notes": "Free delivery over £60. Orders must be placed before 3pm.", "click_and_collect": False,
        "exceptions": [{"date": "2099-12-25", "note": "No deliveries on Christmas Day."}],
    }
    saved = client.put("/admin/api/delivery", json=delivery, headers={"X-CSRF-Token": csrf})
    assert saved.status_code == 200, saved.json
    policy = client.post("/chat_api", json={"tenant": "ALPHA", "message": "Do you offer free delivery?"})
    assert delivery["notes"] in policy.json["reply"]
    dated = client.post("/chat_api", json={"tenant": "ALPHA", "message": "Can you deliver to E1 6AN on 2099-12-25?"})
    reply = dated.json["reply"]
    for required in ["No deliveries on Christmas Day.", "£4.00", "min £25.00", "Next-day", "Ground-floor delivery only.", delivery["notes"]]:
        assert required in reply
    assert "Yes, we deliver" not in reply
    collection = client.post("/chat_api", json={"tenant": "ALPHA", "message": "Can I collect?"})
    assert "Click and collect is not currently available." in collection.json["reply"]
    other = client.post("/chat_api", json={"tenant": "BETA", "message": "Do you offer free delivery?"})
    assert delivery["notes"] not in other.json["reply"]
