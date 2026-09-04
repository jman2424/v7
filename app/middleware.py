"""
Middleware installers for Flask.

- Request ID injection
- Simple IP rate limiting
- CSRF protection (supports: header, query, form, JSON)
- Timing metrics -> AnalyticsService
"""

from __future__ import annotations

import time
import uuid
import os
from collections import defaultdict
from typing import Dict, Optional

from flask import Flask, current_app, g, request, abort, session

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
        # ProxyFix only accepts forwarded headers from explicitly configured
        # trusted proxies. Reading X-Forwarded-For directly lets clients evade
        # rate limiting by inventing an address.
        ip = (request.remote_addr or "unknown").strip()
        if not allow(ip):
            abort(429)


def _read_csrf_from_request() -> Optional[str]:
    # 1) Header
    token = request.headers.get("X-CSRF-Token")
    if token:
        return token

    # 2) Query
    token = request.args.get("_csrf")
    if token:
        return token

    # 3) Form
    token = request.form.get("csrf_token")
    if token:
        return token

    # 4) JSON
    if request.is_json:
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return None
        token = data.get("csrf_token")
        if token:
            return token

    return None


def install_csrf(app: Flask, settings: Settings) -> None:
    SAFE = {"GET", "HEAD", "OPTIONS"}

    @app.before_request
    def _csrf():
        # Always ensure session has a token (needed for first POST)
        if "_csrf" not in session:
            session["_csrf"] = f"csrf_{uuid.uuid4().hex}"

        if request.method in SAFE:
            return

        if current_app.config.get("TESTING") or os.getenv("TESTING") == "1":
            return

        path = (request.path or "").lower()

        # ✅ Allow public endpoints / webhooks
        if (
            path.startswith("/chat_api")
            or path.startswith("/whatsapp")
            or path.startswith("/catalog_webhook")
            or path.startswith("/export_catalog_csv")
            or path.startswith("/health")
        ):
            return

        # ✅ Allow login endpoints (otherwise you lock yourself out)
        if path.startswith("/auth/login") or path.startswith("/admin/login"):
            return

        expected = session.get("_csrf")
        got = _read_csrf_from_request()

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
