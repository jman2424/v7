"""Bounded JSON requests to one authorised public HTTPS host, with no redirects."""
from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from service.website_knowledge import (
    WebsiteImportError, _FetchDeadline, _NoRedirect, _PinnedHTTPSHandler,
    _resolve_public_ip, _validate_public_https_url,
)

MAX_BYTES = 4 * 1024 * 1024
USER_AGENT = 'V7-Business-Sync/1.0'


class SyncHttpError(Exception):
    """A safe code only; provider bodies and credentials are never kept."""

    def __init__(self, code, *, retry=False):
        self.code, self.retry = code, retry
        super().__init__(code)


def public_host(value):
    """Return the validated lower-case host of a public HTTPS address."""
    try:
        return urllib.parse.urlsplit(_validate_public_https_url(value)).hostname
    except WebsiteImportError:
        raise SyncHttpError('invalid_source_address') from None


def request_json(url, *, host, headers=None, body=None, method=None):
    """Call `url` only if it is on `host`; return (json, response headers).

    The address is resolved once, checked to be public and pinned for the
    connection, so a DNS change cannot redirect the request to a private host.
    """
    try:
        url = _validate_public_https_url(url, expected_host=host)
        pinned = _resolve_public_ip(host)
    except WebsiteImportError:
        raise SyncHttpError('source_unreachable', retry=True) from None
    data = None
    send = {'Accept': 'application/json', 'User-Agent': USER_AGENT, **(headers or {})}
    if body is not None:
        data = json.dumps(body).encode()
        send['Content-Type'] = 'application/json'
    request = urllib.request.Request(url, data=data, headers=send, method=method or ('POST' if data else 'GET'))
    try:
        with _FetchDeadline() as deadline:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect(),
                                                 _PinnedHTTPSHandler(pinned, deadline))
            with opener.open(request, timeout=5) as response:
                started, chunks, size = time.monotonic(), [], 0
                while size <= MAX_BYTES:
                    if time.monotonic() - started > 8:
                        raise TimeoutError
                    chunk = response.read1(min(65536, MAX_BYTES + 1 - size))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                if size > MAX_BYTES:
                    raise SyncHttpError('source_response_too_large')
                response_headers = {key.lower(): value for key, value in response.headers.items()}
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            raise SyncHttpError('source_access_denied') from None
        if exc.code == 404:
            raise SyncHttpError('source_not_found') from None
        raise SyncHttpError('source_unavailable', retry=exc.code == 429 or exc.code >= 500) from None
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
        raise SyncHttpError('source_unreachable', retry=True) from None
    try:
        return json.loads(b''.join(chunks).decode('utf-8')), response_headers
    except (ValueError, UnicodeError):
        raise SyncHttpError('source_invalid_response', retry=True) from None
