"""Public-site ingestion boundaries, using local fakes rather than network calls."""
import io
import socket
from email.message import Message
from urllib.parse import urlunsplit

import pytest

from service import website_knowledge as website


# Build synthetic user-info at runtime while preserving the hostile URL case.
_SYNTHETIC_CREDENTIAL_URL = urlunsplit((
    'https', "{}:{}@{}".format('user', 'password', 'business.example'),
    '/', '', '',
))

@pytest.mark.parametrize("url", [
    "http://business.example", "file:///etc/passwd", "https://127.0.0.1/",
    "https://localhost/", "https://service.internal/", "https://business.example:8443/",
    _SYNTHETIC_CREDENTIAL_URL,
    "https://business.example/\r\nInjected:header", "https://business.example/a b",
    "https://business.example\x00/",
])
def test_import_url_rejects_private_schemes_hosts_and_credentials(url):
    with pytest.raises(website.WebsiteImportError):
        website._validate_public_https_url(url)


@pytest.mark.parametrize("addresses", [
    ["127.0.0.1"], ["10.0.0.1"], ["169.254.169.254"], ["::1"],
    ["93.184.216.34", "192.168.1.1"], ["224.0.0.1"], ["ff0e::1"],
    ["64:ff9b::c0a8:101"], ["64:ff9b::a00:1"],
    ["2002:0a00:0001::1"], ["::ffff:127.0.0.1"],
])
def test_dns_resolution_rejects_private_mixed_multicast_and_translated_addresses(monkeypatch, addresses):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443)) for address in addresses
    ])
    with pytest.raises(website.WebsiteImportError):
        website._resolve_public_ip("business.example")


def test_public_ip_is_returned_for_pinned_connection(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
    ])
    assert website._resolve_public_ip("business.example") == "93.184.216.34"


def test_malformed_and_cross_site_links_are_ignored():
    result = website._same_site_links("https://business.example/", [
        "https://[invalid", "https://other.example/", "//127.0.0.1/", "/services", "javascript:alert(1)",
    ], "business.example", set())
    assert result == ["https://business.example/services"]


def test_slow_trickle_body_has_total_read_deadline(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(website.time, "monotonic", lambda: now[0])
    class SlowResponse:
        def read1(self, size):
            now[0] += 2
            return b"x"
    with pytest.raises(TimeoutError):
        website._read_page(SlowResponse())
    assert now[0] == 6


def test_fetch_deadline_shutdown_interrupts_header_and_chunk_line_reads(monkeypatch):
    operations = []
    class Socket:
        def settimeout(self, value):
            operations.append(("timeout", value))
        def close(self):
            operations.append(("close",))
        @staticmethod
        def shutdown(sock, how):
            operations.append(("shutdown", how))
    monkeypatch.setattr(website.socket, "socket", Socket)
    deadline = website._FetchDeadline()
    deadline.watch(Socket())
    deadline._expire()
    assert deadline.expired.is_set()
    assert ("shutdown", socket.SHUT_RDWR) in operations
    with pytest.raises(TimeoutError):
        deadline.watch(Socket())
    assert operations[-1] == ("close",)


def test_fetch_deadline_releases_socket_and_timer_after_request():
    with website._FetchDeadline() as deadline:
        assert 0 < deadline.timeout() <= 3
    assert deadline._socket is None
    assert deadline._timer.finished.is_set()


def test_page_read_is_bounded_to_oversize_detection_byte(monkeypatch):
    monkeypatch.setattr(website, "MAX_PAGE_BYTES", 32)
    assert len(website._read_page(io.BytesIO(b"x" * 100))) == 33


def test_importer_keeps_public_host_pinning_and_proxy_redirect_boundaries(monkeypatch):
    body = b"<html><title>Business</title><p>We offer consultations and product support for customers.</p><script>unsafe()</script></html>"
    handlers = []
    class Response(io.BytesIO):
        status = 200
        headers = Message()
    Response.headers["Content-Type"] = "text/html"
    class Opener:
        def open(self, request, timeout):
            assert request.full_url == "https://business.example/"
            assert timeout == 3
            return Response(body)
    def build(*items):
        handlers.extend(items)
        return Opener()
    monkeypatch.setattr(website, "_resolve_public_ip", lambda host: "93.184.216.34")
    monkeypatch.setattr(website.urllib.request, "build_opener", build)
    result = website.import_website("https://business.example/")
    assert any(isinstance(handler, website._NoRedirect) for handler in handlers)
    assert any(isinstance(handler, website.urllib.request.ProxyHandler) and handler.proxies == {} for handler in handlers)
    assert any(isinstance(handler, website._PinnedHTTPSHandler) and handler.pinned_ip == "93.184.216.34" for handler in handlers)
    assert "unsafe()" not in result["pages"][0]["text"]
