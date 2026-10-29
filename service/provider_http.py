"""Bounded HTTP reuse and content-free timing for one owned provider client."""
import time

import httpx
from openai import DefaultHttpxClient


def _trace_request(request):
    # Never inspect or log the trace payload: it contains headers and sockets.
    # A caller-supplied trace remains the caller's responsibility.
    if 'trace' in request.extensions:
        return
    started = {}
    connected = False
    phases = {'connection.connect_tcp': 'provider_connect_tcp',
              'connection.start_tls': 'provider_tls',
              'http11.receive_response_headers': 'provider_response_headers',
              'http2.receive_response_headers': 'provider_response_headers'}

    def trace(event, info):
        nonlocal connected
        name, _, outcome = event.rpartition('.')
        if name not in phases or outcome not in {'started', 'complete', 'failed'}:
            return
        if outcome == 'started':
            started[name] = time.perf_counter()
            if name == 'connection.connect_tcp':
                connected = True
            return
        before = started.pop(name, None)
        if before is None:
            return
        try:
            from service.chat_diagnostics import emit
            emit('chat_phase', phase=phases[name], outcome=outcome,
                 elapsed_ms=round((time.perf_counter() - before) * 1000, 2))
            if name.endswith('receive_response_headers') and outcome == 'complete':
                emit('provider_connection', outcome='opened' if connected else 'reused')
        except Exception:
            # Optional metrics cannot interrupt an accounted provider request.
            pass

    request.extensions['trace'] = trace


class ProviderHttpClient(DefaultHttpxClient):
    def __init__(self):
        # Preserve SDK TLS, proxy, redirect and timeout defaults. No transport
        # retries are added. A separate instance belongs to each SDK client.
        super().__init__(limits=httpx.Limits(max_connections=16,
            max_keepalive_connections=4, keepalive_expiry=60.0),
            event_hooks={'request': [_trace_request]})

    def __del__(self):
        # Match the SDK's default wrapper ownership on tenant-client eviction.
        try:
            if not self.is_closed:
                self.close()
        except Exception:
            pass
