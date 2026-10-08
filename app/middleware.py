"""Request identity, bounded rate limits, CSRF and response protections."""
from __future__ import annotations

import hmac
import json
import math
import secrets
import time
import os
from urllib.parse import urlsplit
from threading import Lock

from flask import abort, g, request, session
from werkzeug.wsgi import get_host


# Operational routes and tenant conversations are not public search content.
NON_INDEXABLE_PREFIXES = (
    "/admin", "/auth", "/billing", "/files", "/analytics", "/__diag", "/console",
    "/mcp", "/oauth", "/api/", "/mode", "/version", "/export_catalog_csv",
    "/catalog_webhook", "/chat_ui", "/chat_api", "/chat/", "/webchat", "/widget",
    "/whatsapp", "/health", "/ready", "/.well-known/",
)


def install_request_boundaries(app, settings):
    """Reject hostile hosts and cross-origin management writes before parsing data."""
    production = settings.ENVIRONMENT == "production" or os.getenv("RENDER") == "true"
    base = urlsplit(settings.BASE_URL)
    hosts = [base.hostname] if base.hostname else []
    render_host = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()
    if render_host:
        hosts.append(render_host)
    if production and not hosts:
        raise RuntimeError("Set BASE_URL or RENDER_EXTERNAL_HOSTNAME for production host validation")
    # Check after request identity is initialized so rejected hosts still get
    # safe response headers. Never trust caller-supplied forwarded host headers.
    app.config["V7_TRUSTED_HOSTS"] = hosts if production else []
    origins = {f"{base.scheme}://{base.netloc}"} if base.scheme in {"http", "https"} and base.netloc else set()
    if render_host:
        origins.add("https://" + render_host)

    @app.before_request
    def boundaries():
        trusted = app.config["V7_TRUSTED_HOSTS"]
        if trusted:
            get_host(request.environ, trusted_hosts=trusted)
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return
        management = request.path.startswith(("/admin/", "/auth/", "/files/", "/analytics/", "/__diag/", "/billing/")) or request.path in {"/mode", "/oauth/authorize"}
        if not management or request.path == "/billing/stripe/webhook":
            return
        if request.headers.get("Sec-Fetch-Site") == "cross-site":
            abort(403, description="cross_origin_write")
        origin = request.headers.get("Origin")
        allowed = origins if production else {request.host_url.rstrip("/")}
        if origin is not None and origin not in allowed:
            abort(403, description="cross_origin_write")


def install_request_id(app):
    @app.before_request
    def request_id():
        g.request_id = secrets.token_hex(12)
        g.csp_nonce = secrets.token_urlsafe(24)

    @app.after_request
    def protect_response(response):
        response.headers["X-Request-ID"] = g.get("request_id", "-")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if response.status_code == 429:
            response.headers.setdefault("Retry-After", "60")
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'nonce-" + g.csp_nonce + "'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' https: data:; "
            "connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'"
        )
        if (request.path.startswith(NON_INDEXABLE_PREFIXES)
                or (request.path == "/privacy" and "tenant" in request.args)):
            response.headers["X-Robots-Tag"] = "noindex, nofollow"
        if request.path.startswith(("/admin", "/auth", "/billing", "/files", "/analytics", "/__diag", "/console", "/mcp", "/oauth", "/api/v1", "/mode", "/version", "/export_catalog_csv", "/catalog_webhook")):
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Content-Security-Policy"] += "; frame-ancestors 'none'"
        elif request.path == "/chat_ui":
            origins = g.get("chat_origins", [])
            response.headers["Content-Security-Policy"] += "; frame-ancestors 'self' " + " ".join(origins)
        if app.config["SESSION_COOKIE_SECURE"]:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response


def install_request_validation(app):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    def finite_number(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("nonfinite_number")
        return number

    def reject_constant(_value):
        raise ValueError("nonfinite_number")

    @app.before_request
    def validate_request():
        if any(len(request.args.getlist(key)) > 1 for key in request.args):
            abort(400, description="duplicate_query_parameter")
        if request.path.startswith("/api/v1/"):
            request.max_content_length = 65536
        if not request.is_json or request.path.startswith("/whatsapp/") or request.path == "/mcp":
            return
        try:
            value = json.loads(request.get_data(), object_pairs_hook=unique_object,
                               parse_constant=reject_constant, parse_float=finite_number)
        except (ValueError, RecursionError):
            abort(400, description="invalid_json")
        pending = [(value, 0)]
        while pending:
            item, depth = pending.pop()
            if depth > 32:
                abort(400, description="json_too_deep")
            if isinstance(item, dict):
                pending.extend((child, depth + 1) for child in item.values())
            elif isinstance(item, list):
                pending.extend((child, depth + 1) for child in item)


def install_rate_limit(app, settings):
    buckets = {}
    lock = Lock()

    @app.before_request
    def limit():
        # Do not trust caller-supplied forwarded IP headers.
        ip = request.remote_addr or "unknown"
        login = request.method == "POST" and request.path in {"/auth/login", "/admin/login", "/auth/mfa/confirm", "/auth/register", "/auth/register/confirm"}
        if login:
            from service.session_store import allow_login
            if not allow_login(ip):
                abort(429)
        general_rate = max(1, settings.RATE_LIMIT_PER_MIN)
        general_capacity = general_rate + max(0, settings.RATE_LIMIT_BURST)
        limits = [((ip, "request"), general_rate, general_capacity)]
        key, rate, capacity = (ip, "login"), 5, 5
        if not login and request.path in {"/chat_api", "/chat/actions", "/chat/transcribe"}:
            key, rate, capacity = (ip, "public_chat"), 30, 40
        elif not login and request.path.startswith(("/analytics", "/admin/api/")) and request.method == "GET":
            key, rate, capacity = (ip, "analytics"), 30, 40
        elif not login and request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.path.startswith(("/admin", "/files")):
            key, rate, capacity = (ip, "management_write"), 20, 25
        else:
            key = (ip, "login") if login else None
        if key is not None:
            limits.append((key, rate, capacity))
        now = time.monotonic()
        with lock:
            if len(buckets) > 10000:
                for stale in [k for k, (_, timestamp) in buckets.items() if now - timestamp > 600]:
                    buckets.pop(stale, None)
                if any(key not in buckets for key, _, _ in limits) and len(buckets) > 10000:
                    abort(429)
            available = []
            for key, rate, capacity in limits:
                tokens, previous = buckets.get(key, (capacity, now))
                tokens = min(capacity, tokens + (now - previous) * rate / 60)
                if tokens < 1:
                    buckets[key] = (tokens, now)
                    app.logger.warning("SECURITY rate_limited scope=%s", key[1])
                    abort(429)
                available.append((key, tokens))
            for key, tokens in available:
                buckets[key] = (tokens - 1, now)


def install_csrf(app, settings):
    @app.before_request
    def csrf():
        # Webhooks and chat have separate authentication.
        if request.path in {"/chat_api", "/chat/actions", "/chat/transcribe", "/whatsapp/webhook", "/whatsapp/status", "/catalog_webhook", "/billing/stripe/webhook", "/mcp", "/oauth/token"} or request.blueprint == 'vertex_api':
            return
        if "_csrf" not in session:
            session["_csrf"] = secrets.token_urlsafe(32)
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return
        data = request.get_json(silent=True) if request.is_json else None
        supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
        if not supplied and isinstance(data, dict):
            supplied = data.get("csrf_token")
        if not isinstance(supplied, str) or not hmac.compare_digest(supplied.encode(), session["_csrf"].encode()):
            abort(403, description="csrf_failed")


def install_timing_metrics(app, container):
    @app.before_request
    def start_timer():
        g.started = time.monotonic()

    @app.after_request
    def elapsed(response):
        if hasattr(g, "started"):
            response.headers["Server-Timing"] = f'app;dur={(time.monotonic() - g.started) * 1000:.1f}'
        return response
