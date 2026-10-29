"""Real loopback reuse, cleanup and content-free provider diagnostics."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import ssl
from threading import Thread
from types import SimpleNamespace

import httpx
import pytest
from openai import DefaultHttpxClient

from service import chat_diagnostics, performance_metrics, provider_http


@pytest.fixture
def endpoint():
    received = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def do_GET(self):
            received.append((self.client_address, self.headers.get('Authorization')))
            self.send_response(200)
            self.send_header('Content-Length', '2')
            if self.path == '/close':
                self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(b'OK')

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', received
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize('client_type,reused', [(DefaultHttpxClient, False), (provider_http.ProviderHttpClient, True)])
def test_real_socket_survives_customer_pause_but_still_expires(endpoint, monkeypatch, client_type, reused):
    import httpcore._sync.http11 as http11
    # Advance only the connection expiry clock; no real sleeps or global clock patch.
    clock = [1000.0]
    monkeypatch.setattr(http11, 'time', SimpleNamespace(monotonic=lambda: clock[0]))
    for variable in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'):
        monkeypatch.delenv(variable, raising=False)
    url, requests = endpoint
    with client_type() as client:
        assert client.get(url).text == 'OK'
        clock[0] += 8
        assert client.get(url).text == 'OK'
        assert (requests[0][0] == requests[1][0]) is reused
        clock[0] += 61
        assert client.get(url).text == 'OK'
        assert requests[1][0] != requests[2][0]


def test_distinct_client_credentials_never_share_a_socket(endpoint, monkeypatch):
    monkeypatch.setenv('NO_PROXY', '*')
    url, received = endpoint
    with provider_http.ProviderHttpClient() as first, provider_http.ProviderHttpClient() as second:
        first.get(url, headers={'Authorization': 'Bearer synthetic-tenant-a'})
        second.get(url, headers={'Authorization': 'Bearer synthetic-tenant-b'})
        first.get(url, headers={'Authorization': 'Bearer synthetic-tenant-a'})
        assert received[0][0] != received[1][0]
        assert received[0][0] == received[2][0]
        assert [row[1] for row in received] == ['Bearer synthetic-tenant-a', 'Bearer synthetic-tenant-b', 'Bearer synthetic-tenant-a']


def test_tls_verification_and_explicit_close_preserved():
    client = provider_http.ProviderHttpClient()
    context = client._transport._pool._ssl_context
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    client.close()
    assert client.is_closed


def test_server_closed_connection_is_replaced(endpoint, monkeypatch):
    monkeypatch.setenv('NO_PROXY', '*')
    url, received = endpoint
    with provider_http.ProviderHttpClient() as client:
        assert client.get(url + '/close').text == 'OK'
        assert client.get(url).text == 'OK'
    assert len(received) == 2 and received[0][0] != received[1][0]


def test_trace_ignores_sensitive_payload_and_optional_failure(caplog, monkeypatch):
    request = httpx.Request('POST', 'https://provider.invalid/private?secret=not-for-logs',
                            headers={'Authorization': 'Bearer synthetic-private-token'}, content=b'private customer text')
    provider_http._trace_request(request)
    trace = request.extensions['trace']
    payload = {'headers': request.headers, 'request': request, 'exception': RuntimeError('private exception')}
    with caplog.at_level('INFO'), chat_diagnostics.turn_scope('web', 'b' * 24, 'private-session', tenant='TRACE_TEST'):
        for event in ('connection.connect_tcp.started', 'connection.connect_tcp.complete',
                      'connection.start_tls.started', 'connection.start_tls.complete',
                      'http11.receive_response_headers.started', 'http11.receive_response_headers.complete',
                      'http11.receive_response_body.started', 'http11.receive_response_body.complete'):
            trace(event, payload)
    logs = '\n'.join(row.message for row in caplog.records if row.name == 'Chat.Diagnostics')
    assert all(secret not in logs for secret in ('provider.invalid', 'private?', 'synthetic-private-token', 'private customer', 'private exception', 'private-session'))
    events = [json.loads(row.message) for row in caplog.records if row.name == 'Chat.Diagnostics']
    assert {row.get('phase') for row in events if row['event'] == 'chat_phase'} == {
        'provider_connect_tcp', 'provider_tls', 'provider_response_headers'}
    assert performance_metrics.snapshot('TRACE_TEST')['metrics']['provider_new_connections']['sum'] == 1
    assert performance_metrics.snapshot('OTHER_TRACE_TEST')['metrics'] == {}
    monkeypatch.setattr(chat_diagnostics, 'emit', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('metrics unavailable')))
    trace('connection.start_tls.started', payload)
    trace('connection.start_tls.failed', payload)


def test_existing_trace_is_not_overridden():
    original = lambda event, info: None
    request = httpx.Request('GET', 'https://provider.invalid', extensions={'trace': original})
    provider_http._trace_request(request)
    assert request.extensions['trace'] is original


def test_failed_sdk_construction_closes_transport(monkeypatch):
    from service import rewriter
    closed = []
    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-key-not-live')
    monkeypatch.setattr(provider_http, 'ProviderHttpClient', lambda: SimpleNamespace(close=lambda: closed.append(True)))
    monkeypatch.setattr(rewriter, 'OpenAI', lambda **kwargs: (_ for _ in ()).throw(ValueError('configuration')))
    assert rewriter.Rewriter()._client is None
    assert closed == [True]
