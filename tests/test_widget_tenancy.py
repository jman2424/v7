from __future__ import annotations
from tests.conftest import set_test_identity

import json
import logging
import shutil
import pytest
from pathlib import Path


def _add_tenant(app, name: str = "ALT") -> None:
    business_root = Path(app.container.storage.business_root)
    source = business_root / "EXAMPLE"
    target = business_root / name
    if not target.exists():
        shutil.copytree(source, target)


def _as_platform_admin(client, tenant: str = "EXAMPLE") -> None:
    with client.session_transaction() as sess:
        set_test_identity(client, sess, {"id": "platform", "roles": ["platform_admin"], "tenant": tenant})


def test_chat_api_uses_the_requested_tenant_runtime(client, app):
    _add_tenant(app)

    default_container = app.container.for_tenant("EXAMPLE")
    alternate_container = app.container.for_tenant("ALT")
    default_container.handler.handle = lambda *_args, **_kwargs: {"reply": "example reply", "intent": "faq"}
    alternate_container.handler.handle = lambda *_args, **kwargs: {
        "reply": f"alternate reply for {kwargs['tenant']}",
        "intent": "faq",
    }

    response = client.post(
        "/chat_api",
        data=json.dumps({"tenant": "ALT", "message": "hello", "session_id": "tenant-test"}),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 200
    assert response.get_json()["reply"] == "alternate reply for ALT"


def test_tenant_runtimes_do_not_share_session_memory(app):
    _add_tenant(app)
    session_id = "same-session-id"

    primary = app.container.for_tenant("EXAMPLE").handler
    alternate = app.container.for_tenant("ALT").handler
    primary.handle(
        "Do you deliver to E1 6AN?",
        tenant="EXAMPLE",
        session_id=session_id,
        channel="web",
    )
    response = alternate.handle(
        "Do you deliver?",
        tenant="ALT",
        session_id=session_id,
        channel="web",
    )

    assert response["intent"] == "check_delivery_needs_postcode"
    assert "E1 6AN" not in response["reply"]


def test_chat_api_rejects_path_like_tenant_values(client):
    response = client.post(
        "/chat_api",
        data=json.dumps({"tenant": "../../EXAMPLE", "message": "hello"}),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 404
    assert response.get_json()["error"] == "unknown_tenant"


def test_chat_api_only_returns_cors_headers_for_tenant_allowlist(client, app):
    storage = app.container.storage
    branding = storage.read_json("EXAMPLE", "branding.json")
    branding["widget"]["allowed_origins"] = ["https://www.example.test"]
    storage.write_json("EXAMPLE", "branding.json", branding, snapshot=False)

    app.container.handler.handle = lambda *_args, **_kwargs: {"reply": "ok", "intent": "faq"}
    allowed = client.post(
        "/chat_api",
        data=json.dumps({"tenant": "EXAMPLE", "message": "hello"}),
        headers={"Content-Type": "application/json", "Origin": "https://www.example.test"},
    )
    denied = client.post(
        "/chat_api",
        data=json.dumps({"tenant": "EXAMPLE", "message": "hello"}),
        headers={"Content-Type": "application/json", "Origin": "https://other.example.test"},
    )

    assert allowed.status_code == 200
    assert allowed.headers["Access-Control-Allow-Origin"] == "https://www.example.test"
    assert denied.status_code == 403
    assert denied.get_json()["error"] == "origin_forbidden"


def test_chat_api_keeps_customer_content_out_of_operational_logs(client, caplog):
    caplog.set_level(logging.INFO)
    caplog.clear()
    message = "Please call +447123456789 or email customer@example.test"
    session_id = "web-session-private"

    response = client.post(
        "/chat_api",
        data=json.dumps({"tenant": "EXAMPLE", "message": message, "session_id": session_id}),
        headers={"Content-Type": "application/json"},
    )

    logs = "\n".join(record.getMessage() for record in caplog.records)
    assert response.status_code == 200
    assert message not in logs
    assert "+447123456789" not in logs
    assert "customer@example.test" not in logs
    assert session_id not in logs
    assert "text_len=" in logs


def test_chat_api_handoff_updates_one_dashboard_lead(client, app):
    first = client.post(
        "/chat_api",
        data=json.dumps({"tenant": "EXAMPLE", "message": "I need to speak to someone"}),
        headers={"Content-Type": "application/json"},
    )
    session_id = first.get_json()["session_id"]
    response = client.post(
        "/chat_api",
        data=json.dumps(
            {
                "tenant": "EXAMPLE",
                "message": "My name is Alex Morgan and you can reach me at alex@example.test",
                "conversation_token": first.get_json()["conversation_token"],
            }
        ),
        headers={"Content-Type": "application/json"},
    )

    leads = [
        lead for lead in app.container.analytics.get_leads(tenant="EXAMPLE", limit=200)
        if lead["last_session_id"] == session_id
    ]

    assert response.status_code == 200
    assert len(leads) == 1
    assert leads[0]["lead_id"] == f"web:{session_id}"
    assert leads[0]["name"] == "Alex Morgan"


def test_embed_script_and_hosted_chat_are_tenant_scoped(client):
    script = client.get("/widget.js?tenant=EXAMPLE")
    chat = client.get("/chat_ui?tenant=EXAMPLE&embed=1")

    assert script.status_code == 200
    assert script.mimetype == "application/javascript"
    assert '"tenant": "EXAMPLE"' in script.get_data(as_text=True)
    assert "/chat_ui?tenant=" in script.get_data(as_text=True)
    assert chat.status_code == 200
    assert "Example Butchers Assistant" in chat.get_data(as_text=True)
    assert "frame-ancestors" in chat.headers["Content-Security-Policy"]


def test_business_owner_cannot_request_another_tenant_admin_data(client, app):
    _add_tenant(app)
    with client.session_transaction() as sess:
        set_test_identity(client, sess, {"id": "owner", "roles": ["business_owner"], "tenant": "EXAMPLE"})

    response = client.get("/admin/api/catalog?tenant=ALT")
    assert response.status_code == 403

    insights = client.get("/admin/api/insights?tenant=ALT")
    files = client.get("/files/raw/catalog.json?tenant=ALT")
    assert insights.status_code == 403
    assert files.status_code == 403


def test_owner_agent_mode_is_saved_only_for_their_tenant(client, app):
    _add_tenant(app)
    with client.session_transaction() as sess:
        set_test_identity(client, sess, {"id": "owner", "roles": ["business_owner"], "tenant": "EXAMPLE"})

    denied = client.post("/admin/api/mode?tenant=ALT", json={"mode": "V6"})
    updated = client.post("/admin/api/mode", json={"mode": "V6"})

    assert denied.status_code == 403
    assert updated.status_code == 200
    assert updated.get_json()["mode"] == "v6"
    assert app.container.storage.read_json("EXAMPLE", "overrides.json")["ai"]["mode"] == "v6"
    assert "mode" not in app.container.storage.read_json("ALT", "overrides.json").get("ai", {})


def test_chat_api_generates_distinct_sessions_when_clients_omit_them(client):
    first = client.post("/chat_api", json={"tenant": "EXAMPLE", "message": "hello"})
    second = client.post("/chat_api", json={"tenant": "EXAMPLE", "message": "hello again"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.get_json()["session_id"].startswith("web_")
    assert first.get_json()["session_id"] != second.get_json()["session_id"]


def test_chat_api_never_returns_handler_facts_or_customer_entities(client, app):
    app.container.handler.handle = lambda *_args, **_kwargs: {
        "reply": "We will be in touch.",
        "entities": {"name": "Alex Morgan", "email": "alex@example.test"},
        "facts": {"private_note": "owner-only"},
        "meta": {"request_id": "internal-request-id"},
        "agent": {"suggested_replies": ["Browse options", "Speak to someone", "Browse options", "x" * 121]},
    }

    response = client.post(
        "/chat_api",
        json={"tenant": "EXAMPLE", "message": "Please contact me", "session_id": "public-contract-test"},
    )

    body = response.get_json()
    assert response.status_code == 200
    assert body["reply"] == "We will be in touch."
    assert body["agent"] == {"suggested_replies": ["Browse options", "Speak to someone"]}
    assert "raw" not in body
    assert "entities" not in body
    assert "facts" not in body
    assert "meta" not in body


def test_widget_settings_are_saved_by_an_authorized_owner(client):
    _as_platform_admin(client)
    payload = {
        "chat_title": "Example sales team",
        "greeting": "Ask us about today's cuts.",
        "avatar": "https://assets.example.test/avatar.png",
        "allowed_origins": ["https://www.example.test", "http://localhost:5173"],
    }
    response = client.put("/admin/api/widget", json=payload)

    assert response.status_code == 200
    body = response.get_json()
    assert body["widget"]["chat_title"] == payload["chat_title"]
    assert body["widget"]["allowed_origins"] == payload["allowed_origins"]
    assert "widget.js?tenant=EXAMPLE" in body["embed"]["snippet"]
    assert body["embed"]["chat_url"] == "http://localhost/chat_ui?tenant=EXAMPLE"
    assert 'chat_ui?tenant=EXAMPLE&amp;embed=1' in body["embed"]["iframe_snippet"]
    assert 'width="100%"' in body["embed"]["iframe_snippet"]


@pytest.mark.parametrize("origin", [
    "http://localhost.evil.test", "http://127.0.0.1.evil.test",
    "http://localhost@evil.test", "https://name:password@example.test",
    "https://example.test:99999", "https://example.test:notaport",
    "javascript://example.test", "http://example.test",
])
def test_widget_origins_reject_insecure_and_malformed_addresses(client, app, origin):
    _as_platform_admin(client)
    before = app.container.storage.read_json("EXAMPLE", "branding.json")
    response = client.put("/admin/api/widget", json={"allowed_origins": [origin]})
    assert response.status_code == 400
    assert app.container.storage.read_json("EXAMPLE", "branding.json") == before


@pytest.mark.parametrize("origins", [[], ["http://localhost:5173", "http://127.0.0.1:10000", "http://[::1]:8000", "https://shop.example.test"]])
def test_widget_origins_allow_exact_development_hosts_and_removal(client, origins):
    _as_platform_admin(client)
    response = client.put("/admin/api/widget", json={"allowed_origins": origins})
    assert response.status_code == 200
    assert response.json["widget"]["allowed_origins"] == origins


def test_installation_data_cannot_be_read_for_another_company(client, app):
    _add_tenant(app)
    with client.session_transaction() as sess:
        set_test_identity(client, sess, {"id": "owner", "roles": ["business_owner"], "tenant": "EXAMPLE"})
    for endpoint in ("widget", "integrations"):
        assert client.get(f"/admin/api/{endpoint}?tenant=ALT").status_code == 403
        own = client.get(f"/admin/api/{endpoint}?tenant=EXAMPLE")
        assert own.status_code == 200
        assert own.json["tenant"] == "EXAMPLE"


def test_embedded_chat_uses_full_frame_layout(client):
    embedded = client.get("/chat_ui?tenant=EXAMPLE&embed=1")
    standalone = client.get("/chat_ui?tenant=EXAMPLE")
    assert embedded.status_code == standalone.status_code == 200
    assert 'class="widget-page--embedded"' in embedded.text
    assert 'class="widget-page--embedded"' not in standalone.text


def test_platform_operator_can_create_a_clean_starter_tenant(client, app):
    _as_platform_admin(client)
    response = client.post("/admin/api/tenants", json={"key": "NORTHSTAR", "name": "Northstar Homewares"})

    assert response.status_code == 201
    created = response.get_json()["tenant"]
    assert created["key"] == "NORTHSTAR"
    assert created["valid"] is True

    tenants = client.get("/admin/api/tenants").get_json()["tenants"]
    northstar = next(tenant for tenant in tenants if tenant["key"] == "NORTHSTAR")
    overrides = app.container.storage.read_json("NORTHSTAR", "overrides.json")
    assert northstar["name"] == "Northstar Homewares"
    assert northstar["widget_configured"] is False
    assert overrides["sales_playbook"]["offering_type"] == "mixed"


def test_business_owner_cannot_onboard_tenants(client):
    with client.session_transaction() as sess:
        set_test_identity(client, sess, {"id": "owner", "roles": ["business_owner"], "tenant": "EXAMPLE"})

    response = client.post("/admin/api/tenants", json={"key": "OTHER", "name": "Other Company"})
    assert response.status_code == 403
