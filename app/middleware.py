"""
Middleware installers for Flask.

- Request ID injection
- IP-based rate limiting (simple token bucket)
- CSRF token check for admin/auth/dashboard mutations
- Timing metrics → AnalyticsService
"""

from __future__ import annotations

import time
import uuid
import secrets
from collections import defaultdict
from typing import Dict, Optional

from flask import Flask, g, request, abort, session

from app.config import Settings


def install_request_id(app: Flask) -> None:
    @app.before_request
    def _req_id():
        g.request_id = request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex[:12]}"

    @app.after_request
    def _stamp(response):
        response.headers["X-Request-ID"] = g.get("request_id", "-")
        return response


def install_rate_limit(app: Flask, settings: Settings) -> None:
    buckets: Dict[str, Dict[str, float]] = defaultdict(
        lambda: {"tokens": settings.RATE_LIMIT_PER_MIN, "ts": time.time()}
    )

    def allow(ip: str) -> bool:
        now = time.time()
        b = buckets[ip]
        refill = (now - b["ts"]) * (settings.RATE_LIMIT_PER_MIN / 60.0)
        b["tokens"] = min(
            settings.RATE_LIMIT_PER_MIN + settings.RATE_LIMIT_BURST,
            b["tokens"] + refill,
        )
        b["ts"] = now
        if b["tokens"] >= 1.0:
            b["tokens"] -= 1.0
            return True
        return False

    @app.before_request
    def _rl():
        ip = request.headers.get("X-Forwarded-For", request.remote_addr) or "unknown"
        if not allow(ip):
            abort(429)


def install_csrf(app: Flask, settings: Settings) -> None:
    SAFE = {"GET", "HEAD", "OPTIONS"}
    HEADER = "X-CSRF-Token"

    def ensure_token() -> str:
        tok = session.get("_csrf")
        if not tok:
            tok = secrets.token_urlsafe(24)
            session["_csrf"] = tok
        return tok

    def read_token() -> Optional[str]:
        # 1) header (AJAX)
        tok = request.headers.get(HEADER)
        if tok:
            return tok

        # 2) query param
        tok = request.args.get("_csrf")
        if tok:
            return tok

        # 3) form field (HTML forms)
        if request.form:
            tok = request.form.get("csrf_token")
            if tok:
                return tok

        # 4) json body (API clients)
        if request.is_json:
            try:
                data = request.get_json(silent=True) or {}
                tok = data.get("csrf_token")
                if tok:
                    return tok
            except Exception:
                pass

        return None

    @app.context_processor
    def _inject_csrf():
        # makes {{ csrf_token }} available in templates
        return {"csrf_token": ensure_token()}

    @app.before_request
    def _csrf():
        ensure_token()

        if request.method in SAFE:
            return

        path = (request.path or "").lower()

        # Skip CSRF for public/webhook endpoints
        if (
            path.startswith("/chat_api")
            or path.startswith("/whatsapp")
            or path.startswith("/catalog_webhook")
            or path.startswith("/export_catalog_csv")
            or path.startswith("/health")
        ):
            return

        # We DO want CSRF for admin/auth/dashboard writes
        expected = session.get("_csrf")
        got = read_token()

        if not expected or not got or got != expected:
            app.logger.warning(
                "CSRF blocked: method=%s path=%s token_present=%s",
                request.method,
                path,
                bool(got),
            )
            abort(403, description="csrf_failed")


def install_timing_metrics(app: Flask, container) -> None:
    @app.before_request
    def _start_timer():
        g._t0 = time.time()

    @app.after_request
    def _stop_timer(response):
        try:
            t0 = getattr(g, "_t0", None)
            if t0 is not None:
                dt = int((time.time() - t0) * 1000)
                container.analytics.record_timing(path=request.path, ms=dt)
        except Exception:
            pass
        return response
