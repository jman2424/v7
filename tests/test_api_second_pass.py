"""Public origin, website import and fail-closed management write regressions."""
import http.client
import io
import json
import socket
import time
from dataclasses import replace
from threading import Event, Thread
from unittest.mock import Mock

import pytest
import test_platform_security

from service import website_knowledge as website
from service import analytics_db

platform = test_platform_security.platform


@pytest.mark.parametrize("method", ["POST", "OPTIONS"])
def test_chat_origin_cannot_be_approved_by_caller_host(platform, method):
    app = platform[0]
    app.container.settings = replace(app.container.settings, BASE_URL="https://platform.example.test")
    response = app.test_client().open(
        "/chat_api", method=method, base_url="https://attacker.example.test",
        headers={"Origin": "https://attacker.example.test"},
        json={"tenant": "ALPHA", "message": "Opening hours?"} if method == "POST" else None,
    )
    assert response.status_code == 403
    assert "Access-Control-Allow-Origin" not in response.headers


def test_chat_allows_configured_and_explicit_tenant_origins(platform):
    app = platform[0]
    app.container.settings = replace(app.container.settings, BASE_URL="https://platform.example.test")
    app.container.storage.write_json("ALPHA", "branding.json", {
        "allowed_origins": ["https://shop.example.test"],
    })
    client = app.test_client()
    for origin in ("https://platform.example.test", "https://shop.example.test"):
        response = client.post("/chat_api", json={"tenant": "ALPHA", "message": "Opening hours?"},
                               headers={"Origin": origin})
        assert response.status_code == 200
        assert response.headers["Access-Control-Allow-Origin"] == origin
    assert client.post("/chat_api", json={"message": "Hello"}, headers={
        "Origin": "https://shop.example.test.attacker.test",
    }).status_code == 403


def test_chat_retains_loopback_preview_and_server_clients(platform):
    client = platform[0].test_client()
    body = {"tenant": "ALPHA", "message": "Opening hours?"}
    assert client.post("/chat_api", json=body, base_url="http://127.0.0.1:5000",
                       headers={"Origin": "http://127.0.0.1:5000"}).status_code == 200
    assert client.post("/chat_api", json=body).status_code == 200
    assert client.post("/chat_api", json=body,
                       headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


@pytest.mark.parametrize("url", ["https://exam\tple.test/", "https://example.test/\npath",
                                  "https://example.test/\rpath", "https://example.test/\x7fpath"])
def test_website_import_rejects_control_characters_before_url_normalization(url):
    with pytest.raises(website.WebsiteImportError):
        website._validate_public_https_url(url)


def test_scraped_malformed_and_off_site_urls_do_not_abort_import():
    links = ["https://[", "https://example.test:invalid/path", "https://other.test/",
             "https://example.test@other.test/", "http://example.test/", "/terms?secret=x",
             "/catalog.pdf", "/bad\tpath", "/about", "/about#team"]
    assert website._same_site_links("https://example.test/", links, "example.test", set()) == [
        "https://example.test/about",
    ]


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1",
                                      "::ffff:127.0.0.1", "fc00::1"])
def test_website_import_rejects_any_private_dns_result(monkeypatch, address):
    addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
                 (socket.AF_INET6 if ":" in address else socket.AF_INET,
                  socket.SOCK_STREAM, 6, "", (address, 443))]
    monkeypatch.setattr(website.socket, "getaddrinfo", lambda *args, **kwargs: addresses)
    with pytest.raises(website.WebsiteImportError, match="non-public"):
        website._resolve_public_ip("example.test")


def test_website_connection_uses_validated_ip_and_hostname_tls(monkeypatch):
    context = Mock()
    connection = website._PinnedHTTPSConnection("example.test", pinned_ip="8.8.8.8",
                                                timeout=3, context=context)
    connect = Mock(return_value=Mock())
    monkeypatch.setattr(website.socket, "create_connection", connect)
    connection.connect()
    connect.assert_called_once_with(("8.8.8.8", 443), 3, None)
    context.wrap_socket.assert_called_once_with(connect.return_value, server_hostname="example.test")
    assert website._NoRedirect().redirect_request(None, None, 302, "redirect", {},
                                                 "https://127.0.0.1/") is None


def test_incomplete_website_response_returns_safe_import_error(monkeypatch):
    monkeypatch.setattr(website, "_resolve_public_ip", lambda _: "8.8.8.8")
    opener = Mock()
    opener.open.side_effect = http.client.IncompleteRead(b"private response content", 100)
    monkeypatch.setattr(website.urllib.request, "build_opener", lambda *args: opener)
    with pytest.raises(website.WebsiteImportError, match="No readable public pages") as raised:
        website.import_website("https://example.test/")
    assert "private response content" not in str(raised.value)


def _knowledge():
    return {"source_url": "https://example.test/", "fetched_at": "2026-09-30T12:00:00Z",
            "pages": [{"url": "https://example.test/", "title": "Private draft title",
                       "text": "Website content should never be copied into the audit log."}]}


@pytest.mark.parametrize("resource", ["widget", "website"])
@pytest.mark.parametrize("stage", ["attempted", "prepared"])
def test_management_audit_failure_prevents_widget_and_website_writes(platform, monkeypatch, resource, stage):
    app = platform[0]
    storage = app.container.storage
    client = app.test_client()
    csrf = test_platform_security.login(client, "admin@example.test")
    if resource == "website":
        filename = "website_knowledge.json"
        previous = _knowledge()
        storage.write_json("ALPHA", "store_info.json", {"name": "ALPHA", "website": "https://example.test/"})
        monkeypatch.setattr("routes.admin_api_routes.import_website", lambda _: _knowledge())
    else:
        filename = "branding.json"
        previous = {"widget": {"greeting": "Original welcome"}, "allowed_origins": []}
    storage.write_json("ALPHA", filename, previous)
    fail = Mock(side_effect=OSError("audit disk unavailable") if stage == "attempted"
                else [None, OSError("audit disk unavailable")])
    monkeypatch.setattr("routes.admin_api_routes.AuditService.record", fail)
    if resource == "widget":
        response = client.put("/admin/api/widget", json={
            "chat_title": "Sales Assistant", "greeting": "Updated welcome", "allowed_origins": [],
        }, headers={"X-CSRF-Token": csrf})
    else:
        response = client.post("/admin/api/website-knowledge/import", json={},
                               headers={"X-CSRF-Token": csrf})
    assert response.status_code == 503
    assert storage.read_json("ALPHA", filename) == previous
    assert fail.call_args.kwargs["extra"]["result"] == stage


@pytest.mark.parametrize("resource", ["widget", "website"])
def test_management_writes_have_scoped_prepared_and_success_audit(platform, monkeypatch, resource):
    app = platform[0]
    storage = app.container.storage
    client = app.test_client()
    csrf = test_platform_security.login(client, "admin@example.test")
    records = Mock()
    monkeypatch.setattr("routes.admin_api_routes.AuditService.record", records)
    if resource == "website":
        filename = "website_knowledge.json"
        storage.write_json("ALPHA", "store_info.json", {"name": "ALPHA", "website": "https://example.test/"})
        monkeypatch.setattr("routes.admin_api_routes.import_website", lambda _: _knowledge())
        response = client.post("/admin/api/website-knowledge/import", json={},
                               headers={"X-CSRF-Token": csrf})
    else:
        filename = "branding.json"
        response = client.put("/admin/api/widget", json={
            "chat_title": "Sales Assistant", "greeting": "Updated welcome", "allowed_origins": [],
        }, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200
    assert [call.kwargs["extra"]["result"] for call in records.call_args_list] == ["attempted", "prepared", "success"]
    for call in records.call_args_list:
        assert call.kwargs["extra"]["tenant"] == "ALPHA"
        if call.kwargs["extra"]["result"] != "attempted":
            assert call.kwargs["target"] == "ALPHA/" + filename
    prepared = records.call_args_list[1].kwargs["extra"]
    assert len(prepared["before_revision"]) == len(prepared["after_revision"]) == 64
    assert "Private draft title" not in json.dumps([call.kwargs for call in records.call_args_list])
    assert "Website content" not in json.dumps([call.kwargs for call in records.call_args_list])
    assert "Updated welcome" not in json.dumps([call.kwargs for call in records.call_args_list])


def test_website_change_during_fetch_cannot_commit_old_knowledge(platform, monkeypatch):
    app = platform[0]
    storage = app.container.storage
    storage.write_json("ALPHA", "store_info.json", {"name": "ALPHA", "website": "https://example.test/"})

    def changing_source(_):
        storage.write_json("ALPHA", "store_info.json", {"name": "ALPHA", "website": "https://new.example.test/"})
        return _knowledge()

    monkeypatch.setattr("routes.admin_api_routes.import_website", changing_source)
    client = app.test_client()
    csrf = test_platform_security.login(client)
    response = client.post("/admin/api/website-knowledge/import", json={},
                           headers={"X-CSRF-Token": csrf})
    assert response.status_code == 409
    assert not storage.file_path("ALPHA", "website_knowledge.json").exists()


@pytest.mark.parametrize("method", ["GET", "POST", "OPTIONS"])
def test_action_origin_cannot_be_approved_by_caller_host(platform, method):
    app = platform[0]
    app.container.settings = replace(app.container.settings, BASE_URL="https://platform.example.test")
    response = app.test_client().open(
        "/chat/actions?tenant=ALPHA", method=method, base_url="https://attacker.example.test",
        headers={"Origin": "https://attacker.example.test"},
        json={"tenant": "ALPHA"} if method == "POST" else None,
    )
    assert response.status_code == 403
    assert "Access-Control-Allow-Origin" not in response.headers


def test_withheld_insights_sections_are_never_queried(platform, monkeypatch):
    app, registry, _ = platform
    accounts = json.loads(registry.read_text())
    accounts["users"][1]["permissions"] = ["analytics.read"]
    registry.write_text(json.dumps(accounts))
    client = app.test_client()
    test_platform_security.login(client)

    def forbidden_query(**kwargs):
        pytest.fail("A withheld data section must not be queried")

    for name in ("get_errors", "get_common_questions", "get_leads"):
        monkeypatch.setattr("routes.admin_api_routes." + name, forbidden_query)
    response = client.get("/admin/api/insights")
    assert response.status_code == 200
    assert response.json["errors"] == response.json["common_questions"] == response.json["leads"] == []
    for route in ("errors", "questions", "leads", "catalog", "website-knowledge"):
        assert client.get("/admin/api/" + route).status_code == 403


def test_conversation_cursors_reveal_only_the_selected_company(platform):
    client = platform[0].test_client()
    test_platform_security.login(client)
    for index in range(55):
        analytics_db.log_message(tenant="ALPHA", channel="web", direction="inbound",
                                 session_id="a-session", text=f"A message {index}")
        analytics_db.log_message(tenant="BETA", channel="web", direction="inbound",
                                 session_id="b-session", text=f"B private message {index}")
    first = client.get("/admin/api/conversations?minutes=60").json
    assert first["has_more"] and first["next_before"] == 6
    assert [message["id"] for message in first["messages"]] == list(range(55, 5, -1))
    second = client.get("/admin/api/conversations?minutes=60&before=6").json
    assert not second["has_more"] and second["next_before"] is None
    assert [message["id"] for message in second["messages"]] == [5, 4, 3, 2, 1]
    assert "B private" not in json.dumps([first, second])
    analytics_db.log_message(tenant="BETA", channel="web", direction="inbound",
                             session_id="b-session", text="B additional message")
    assert client.get("/admin/api/conversations?minutes=60").json == first


@pytest.mark.parametrize("address", ["224.0.0.1", "ff02::1", "64:ff9b::a00:1", "2002:7f00:1::"])
def test_website_resolver_rejects_multicast_and_private_translation_addresses(monkeypatch, address):
    monkeypatch.setattr(website.socket, "getaddrinfo", lambda *args, **kwargs: [
        (socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443)),
    ])
    with pytest.raises(website.WebsiteImportError, match="non-public"):
        website._resolve_public_ip("example.test")


def test_website_body_budget_expires_even_when_data_continues(monkeypatch):
    ticks = iter([0, 0, website.MAX_PAGE_SECONDS + 1])
    monkeypatch.setattr(website.time, "monotonic", lambda: next(ticks))
    response = Mock()
    response.read1.return_value = b"x"
    with pytest.raises(TimeoutError, match="body deadline"):
        website._read_page(response)
    response.read1.assert_called_once_with(8192)


def test_website_body_reader_bounds_size_before_accumulating_more(monkeypatch):
    monkeypatch.setattr(website, "MAX_PAGE_BYTES", 8)
    response = Mock()
    response.read1.side_effect = lambda amount: b"x" * amount
    assert website._read_page(response) == b"x" * 9
    response.read1.assert_called_once_with(9)


@pytest.mark.parametrize("phase", ["status_line", "headers", "chunk_line"])
def test_website_watchdog_interrupts_continuously_trickled_protocol_lines(monkeypatch, phase):
    monkeypatch.setattr(website, "MAX_FETCH_SECONDS", 0.15)
    monkeypatch.setattr(website, "_resolve_public_ip", lambda _: "8.8.8.8")
    receiver, sender = socket.socketpair()
    stop = Event()
    deadlines = []
    responses = []

    def build_opener(*handlers):
        handler = next(item for item in handlers if isinstance(item, website._PinnedHTTPSHandler))
        deadline = handler.deadline
        deadlines.append(deadline)
        deadline.watch(receiver)
        response = http.client.HTTPResponse(receiver)
        responses.append(response)

        def open_response(*args, **kwargs):
            response.begin()
            return response

        opener = Mock()
        opener.open.side_effect = open_response
        return opener

    monkeypatch.setattr(website.urllib.request, "build_opener", build_opener)

    def trickle():
        try:
            initial = {
                "status_line": b"HTTP/1.1 200 ",
                "headers": b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nX-Slow: ",
                "chunk_line": b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nTransfer-Encoding: chunked\r\n\r\n1;",
            }[phase]
            sender.sendall(initial)
            while not stop.wait(0.005):
                sender.sendall(b"a")
        except OSError:
            pass

    writer = Thread(target=trickle, daemon=True)
    writer.start()
    started = time.monotonic()
    try:
        # Shutdown may become EOF rather than an exception. The importer must
        # reject the expired fetch on either platform, including tolerated EOF.
        with pytest.raises(website.WebsiteImportError, match="No readable public pages"):
            website.import_website("https://example.test/")
        assert deadlines[0].expired.is_set()
        with pytest.raises(TimeoutError, match="fetch deadline"):
            deadlines[0].timeout()
        assert time.monotonic() - started < 3
    finally:
        stop.set()
        for response in responses:
            response.close()
        receiver.close()
        sender.close()
        writer.join(3)
    assert not writer.is_alive()


def test_expired_website_fetch_rejects_buffered_body_returned_at_eof(monkeypatch):
    monkeypatch.setattr(website, "_resolve_public_ip", lambda _: "8.8.8.8")
    body = b"<html><p>Readable business information must not be accepted after the fetch deadline.</p></html>"

    class Response(io.BytesIO):
        status = 200
        headers = {"Content-Type": "text/html"}

    def build_opener(*handlers):
        handler = next(item for item in handlers if isinstance(item, website._PinnedHTTPSHandler))
        handler.deadline._expire()
        opener = Mock()
        opener.open.return_value = Response(body)
        return opener

    monkeypatch.setattr(website.urllib.request, "build_opener", build_opener)
    with pytest.raises(website.WebsiteImportError, match="No readable public pages"):
        website.import_website("https://example.test/")
