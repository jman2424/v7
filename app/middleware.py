"""Request identity, bounded rate limits, CSRF and response protections."""
from __future__ import annotations

import hmac
import secrets
import time
from threading import Lock

from flask import abort, g, request, session


def install_request_id(app):
    @app.before_request
    def request_id():
        g.request_id = secrets.token_hex(12)
        g.csp_nonce = secrets.token_urlsafe(24)

    @app.after_request
    def protect_response(response):
        response.headers["X-Request-ID"] = g.get("request_id", "-")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'nonce-" + g.csp_nonce + "'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' https: data:; "
            "connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'"
        )
        if request.path.startswith(("/admin", "/auth", "/billing", "/files", "/analytics", "/__diag", "/console")):
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Content-Security-Policy"] += "; frame-ancestors 'none'"
        elif request.path == "/chat_ui":
            origins = g.get("chat_origins", [])
            response.headers["Content-Security-Policy"] += "; frame-ancestors 'self' " + " ".join(origins)
        if app.config["SESSION_COOKIE_SECURE"]:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response


def install_rate_limit(app, settings):
    buckets = {}
    lock = Lock()

    @app.before_request
    def limit():
        # Do not trust caller-supplied forwarded IP headers.
        ip = request.remote_addr or "unknown"
        login = request.method == "POST" and request.path in {"/auth/login", "/admin/login", "/auth/mfa/confirm"}
        if login:
            from service.session_store import allow_login
            if not allow_login(ip):
                abort(429)
        key = (ip, "login" if login else "request")
        rate = 5 if login else max(1, settings.RATE_LIMIT_PER_MIN)
        capacity = 5 if login else rate + max(0, settings.RATE_LIMIT_BURST)
        now = time.monotonic()
        with lock:
            if len(buckets) > 10000:
                for stale in [k for k, (_, timestamp) in buckets.items() if now - timestamp > 600]:
                    buckets.pop(stale, None)
                if key not in buckets and len(buckets) > 10000:
                    abort(429)
            tokens, previous = buckets.get(key, (capacity, now))
            tokens = min(capacity, tokens + (now - previous) * rate / 60)
            if tokens < 1:
                buckets[key] = (tokens, now)
                abort(429)
            buckets[key] = (tokens - 1, now)


def install_csrf(app, settings):
    @app.before_request
    def csrf():
        # Webhooks and chat have separate authentication.
        if request.path in {"/chat_api", "/whatsapp/webhook", "/whatsapp/status", "/catalog_webhook", "/billing/stripe/webhook"}:
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
