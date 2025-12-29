"""
Middleware installers for Flask.

- Request ID injection
- IP-based rate limiting (simple token bucket)
- CSRF protection (session token; supports form + JSON + header)
- Timing metrics → AnalyticsService
"""

from __future__ import annotations
import time
import uuid
import secrets
from collections import defaultdict
from typing import Dict

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


def _ensure_csrf_token() -> str:
    tok = session.get("csrf_token")
    if not tok:
        tok = secrets.token_urlsafe(32)
        session["csrf_token"] = tok
    return tok


def install_csrf(app: Flask, settings: Settings) -> None:
    SAFE = {"GET", "HEAD", "OPTIONS"}
    HEADER = "X-CSRF-Token"

    @app.before_request
    def _csrf():
        # Ensure token exists for pages that will render forms
        if request.method in SAFE:
            _ensure_csrf_token()
            return

        path = (request.path or "").lower()

        # Skip CSRF for public/webhook endpoints
        if (
            path.startswith("/chat_api")
            or path.startswith("/whatsapp")
            or path.startswith("/catalog_webhook")
            or path.startswith("/export_catalog_csv")
        ):
            return

        expected = session.get("csrf_token")
        if not expected:
            abort(403, description="csrf_missing_session")

        token = None

        # 1) header
        token = request.headers.get(HEADER) or token

        # 2) query (rare, but ok)
        token = request.args.get("_csrf") or token

        # 3) form field
        if token is None and request.form:
            token = request.form.get("csrf_token")

        # 4) JSON body
        if token is None and request.is_json:
            data = request.get_json(silent=True) or {}
            token = data.get("csrf_token")

        if not token or token != expected:
            app.logger.warning(
                "CSRF blocked: method=%s path=%s token=%r",
                request.method,
                path,
                token,
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
