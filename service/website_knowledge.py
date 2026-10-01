"""Bounded, same-site public HTML import for owner supplied business websites."""
from __future__ import annotations

import http.client
import ipaddress
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from threading import Event, Lock, Timer
from typing import Any

MAX_PAGES = 6
MAX_PAGE_BYTES = 512 * 1024
MAX_PAGE_CHARS = 18_000
MAX_TOTAL_CHARS = 60_000
MAX_LINKS = 1000
MAX_PAGE_SECONDS = 5
MAX_FETCH_SECONDS = 10
_NAT64_NETWORK = ipaddress.ip_network("64:ff9b::/96")
_SKIP_TAGS = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form"}


class WebsiteImportError(ValueError):
    """The configured URL could not be imported safely as public HTML."""


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.links: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag == "a" and self._skip_depth == 0 and len(self.links) < MAX_LINKS:
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        value = " ".join((data or "").split())
        if not value:
            return
        if self._in_title:
            self.title_parts.append(value)
        if not self._skip_depth:
            self.text_parts.append(value)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _FetchDeadline:
    """Interrupt socket reads even when a peer trickles HTTP header/chunk lines."""
    def __init__(self):
        self.expires_at = time.monotonic() + MAX_FETCH_SECONDS
        self.expired = Event()
        self._lock = Lock()
        self._socket = None
        self._timer = Timer(MAX_FETCH_SECONDS, self._expire)
        self._timer.daemon = True

    def __enter__(self):
        self._timer.start()
        return self

    def __exit__(self, *args):
        self._timer.cancel()
        with self._lock:
            self._socket = None

    def _expire(self):
        self.expired.set()
        with self._lock:
            sock = self._socket
            if sock is not None:
                try:
                    # Use the base socket operation: do not mutate SSL state
                    # concurrently with the thread blocked in its buffered read.
                    socket.socket.shutdown(sock, socket.SHUT_RDWR)
                except OSError:
                    pass  # The request may already have closed this socket.

    def timeout(self):
        remaining = self.expires_at - time.monotonic()
        if self.expired.is_set() or remaining <= 0:
            raise TimeoutError("Website fetch deadline exceeded")
        return min(3, remaining)

    def watch(self, sock):
        with self._lock:
            self._socket = sock
        try:
            sock.settimeout(self.timeout())
        except TimeoutError:
            sock.close()
            raise


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to a previously validated IP while retaining hostname TLS checks."""

    def __init__(self, host: str, *, pinned_ip: str, deadline=None, **kwargs: Any) -> None:
        self._pinned_ip = pinned_ip
        self._deadline = deadline
        super().__init__(host, **kwargs)

    def connect(self) -> None:
        timeout = self._deadline.timeout() if self._deadline else self.timeout
        sock = socket.create_connection((self._pinned_ip, self.port), timeout, self.source_address)
        if self._deadline:
            self._deadline.watch(sock)
        if self._tunnel_host:
            self.sock = sock
            self._tunnel()
            sock = self.sock
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        if self._deadline:
            self._deadline.watch(self.sock)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, pinned_ip: str, deadline=None) -> None:
        super().__init__()
        self.pinned_ip = pinned_ip
        self.deadline = deadline

    def https_open(self, req):
        return self.do_open(
            lambda host, **kwargs: _PinnedHTTPSConnection(
                host, pinned_ip=self.pinned_ip, deadline=self.deadline, context=self._context, **kwargs
            ),
            req,
        )


def _validate_public_https_url(value: str, *, expected_host: str | None = None) -> str:
    if (not isinstance(value, str) or len(value) > 2048
            or any(ord(character) < 32 or ord(character) == 127 for character in value)):
        raise WebsiteImportError("Enter a valid public HTTPS website URL in Business profile.")
    value = value.strip()
    if any(ord(char) < 33 or ord(char) == 127 for char in value):
        raise WebsiteImportError("Enter a valid public HTTPS website URL in Business profile.")
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise WebsiteImportError("Enter a valid public HTTPS website URL in Business profile.") from exc
    if (parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username
            or parsed.password or port not in (None, 443)):
        raise WebsiteImportError("Only public HTTPS websites on the standard port can be imported.")
    try:
        host = parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise WebsiteImportError("Enter a valid public HTTPS website hostname.") from exc
    if expected_host and host != expected_host:
        raise WebsiteImportError("The imported pages must stay on the configured website host.")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise WebsiteImportError("Private and local website addresses cannot be imported.")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise WebsiteImportError("Enter a public website hostname, not an IP address.")
    path = parsed.path or "/"
    return urllib.parse.urlunsplit(("https", host, path, parsed.query, ""))


def _resolve_public_ip(host: str) -> str:
    """Resolve and return a public IP that the HTTP connection will pin to."""
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise WebsiteImportError("The configured website could not be reached.") from exc
    if not addresses:
        raise WebsiteImportError("The configured website could not be reached.")
    resolved = [ipaddress.ip_address(info[4][0].split("%", 1)[0]) for info in addresses]
    if any(not _public_unicast(address) for address in resolved):
        raise WebsiteImportError("Private or non-public website addresses cannot be imported.")
    return str(resolved[0])


def _public_unicast(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if not address.is_global or address.is_multicast:
        return False
    if isinstance(address, ipaddress.IPv6Address):
        embedded = [address.ipv4_mapped, address.sixtofour]
        if address.teredo:
            embedded.extend(address.teredo)
        if address in _NAT64_NETWORK:
            embedded.append(ipaddress.IPv4Address(int(address) & 0xffffffff))
        if any(ip is not None and (not ip.is_global or ip.is_multicast) for ip in embedded):
            return False
    return True


def _read_page(response) -> bytes:
    """Bound total body-read time as well as size, including slow trickle bodies."""
    deadline = time.monotonic() + MAX_PAGE_SECONDS
    chunks = []
    size = 0
    # HTTPS responses provide read1(), which returns available bytes instead of
    # waiting indefinitely for a malicious server to fill a large read buffer.
    read = response.read1
    while size <= MAX_PAGE_BYTES:
        if time.monotonic() >= deadline:
            raise TimeoutError("Website body deadline exceeded")
        chunk = read(min(8192, MAX_PAGE_BYTES + 1 - size))
        if time.monotonic() >= deadline:
            raise TimeoutError("Website body deadline exceeded")
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
    return b"".join(chunks)


def _same_site_links(base_url: str, links: list[str], host: str, seen: set[str]) -> list[str]:
    found: list[str] = []
    for href in links:
        if len(found) >= MAX_PAGES:
            break
        if (not isinstance(href, str) or len(href) > 2048
                or any(ord(character) < 32 or ord(character) == 127 for character in href)):
            continue
        try:
            absolute = urllib.parse.urljoin(base_url, href)
            parsed_absolute = urllib.parse.urlsplit(absolute)
            link_host = (parsed_absolute.hostname or "").rstrip(".").encode("idna").decode("ascii").lower()
        except (UnicodeError, ValueError):
            continue
        if link_host != host:
            continue
        try:
            normalized = _validate_public_https_url(absolute, expected_host=host)
        except (WebsiteImportError, ValueError):
            continue
        parsed = urllib.parse.urlsplit(normalized)
        if parsed.query or parsed.path.lower().endswith((
            ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".zip", ".xml"
        )):
            continue
        if normalized not in seen and normalized not in found:
            found.append(normalized)
    return found


def import_website(url: str) -> dict[str, Any]:
    """Fetch up to six public same-host HTML pages with bounded size and no redirects."""
    start_url = _validate_public_https_url(url)
    host = urllib.parse.urlsplit(start_url).hostname or ""
    queue = [start_url]
    seen: set[str] = set()
    pages: list[dict[str, str]] = []
    total_chars = 0

    while queue and len(seen) < MAX_PAGES and len(pages) < MAX_PAGES and total_chars < MAX_TOTAL_CHARS:
        page_url = queue.pop(0)
        if page_url in seen:
            continue
        seen.add(page_url)
        page_url = _validate_public_https_url(page_url, expected_host=host)
        pinned_ip = _resolve_public_ip(host)
        request = urllib.request.Request(page_url, headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "V7-Business-Knowledge-Importer/1.0",
        })
        try:
            with _FetchDeadline() as deadline:
                opener = urllib.request.build_opener(
                    urllib.request.ProxyHandler({}), _NoRedirect(), _PinnedHTTPSHandler(pinned_ip, deadline)
                )
                with opener.open(request, timeout=3) as response:
                    content_type = (response.headers.get("Content-Type") or "").lower()
                    if response.status != 200 or not ("text/html" in content_type or "application/xhtml+xml" in content_type):
                        continue
                    raw = _read_page(response)
                    if deadline.expired.is_set():
                        raise TimeoutError("Website fetch deadline exceeded")
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
            continue
        if len(raw) > MAX_PAGE_BYTES:
            continue
        parser = _PageParser()
        try:
            parser.feed(raw.decode("utf-8", errors="replace"))
        except Exception:
            continue
        text = "\n".join(parser.text_parts)
        text = "\n".join(line for line in text.splitlines() if line)[:MAX_PAGE_CHARS]
        if len(text) < 40:
            continue
        title = " ".join(parser.title_parts).strip()[:200]
        room = MAX_TOTAL_CHARS - total_chars
        text = text[:room]
        pages.append({"url": page_url, "title": title, "text": text})
        total_chars += len(text)
        if len(pages) < MAX_PAGES:
            queue.extend(_same_site_links(page_url, parser.links, host, seen))

    if not pages:
        raise WebsiteImportError("No readable public pages were found. Check the website URL and try again.")
    return {
        "source_url": start_url,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "pages": pages,
    }


def relevant_passages(knowledge: Any, question: str, *, limit: int = 2) -> list[dict[str, str]]:
    """Return the most relevant imported page text for a customer question."""
    if not isinstance(knowledge, dict) or not isinstance(knowledge.get("pages"), list):
        return []
    stop_words = {"about", "are", "could", "does", "from", "have", "help", "into", "that", "them", "there",
                  "they", "this", "what", "when", "where", "which", "with", "would", "your", "business",
                  "you", "our", "the", "for", "and", "how", "can", "tell", "please", "me"}
    words = {word.lower() for word in re.findall(r"[a-z0-9]{3,}", question) if word.lower() not in stop_words}
    if not words:
        return []
    for topic in (
        {"location", "locations", "located", "address", "addresses", "branch", "branches", "office", "offices", "visit"},
        {"hours", "opening", "open", "closing", "close", "closed"},
        {"delivery", "deliver", "delivers", "shipping", "ship", "shipped"},
        {"refund", "refunds", "return", "returns", "exchange", "exchanges"},
    ):
        if words.intersection(topic):
            words.update(topic)
    scored: list[tuple[float, int, int, dict[str, str]]] = []
    for page in knowledge["pages"]:
        if not isinstance(page, dict) or not isinstance(page.get("text"), str):
            continue
        text = page["text"][:MAX_PAGE_CHARS]
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        title_words = {word.lower() for word in re.findall(r"[a-z0-9]{3,}", str(page.get("title") or ""))}
        for index in range(len(lines)):
            excerpt = "\n".join(lines[index:index + 3])
            if len(excerpt) < 20:
                continue
            excerpt_words = {word.lower() for word in re.findall(r"[a-z0-9]{3,}", excerpt)}
            overlap = words & excerpt_words
            if not overlap:
                continue
            if len(excerpt) > 2800:
                matches = [match.start() for match in re.finditer(r"[a-z0-9]{3,}", excerpt.lower())
                           if match.group() in overlap]
                start = max(0, (matches[0] if matches else 0) - 300)
                excerpt = excerpt[start:start + 2800]
            score = len(overlap) / len(words) + (0.05 if title_words & words else 0)
            scored.append((score, id(page), index, {
                "url": str(page.get("url") or ""),
                "title": str(page.get("title") or ""),
                "text": excerpt,
            }))
    scored.sort(key=lambda item: item[0], reverse=True)
    selected: list[dict[str, str]] = []
    positions: list[tuple[int, int]] = []
    for _, page_id, index, passage in scored:
        if any(existing_page == page_id and abs(existing_index - index) <= 2
               for existing_page, existing_index in positions):
            continue
        selected.append(passage)
        positions.append((page_id, index))
        if len(selected) >= limit:
            break
    return selected
