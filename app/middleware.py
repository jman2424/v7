from __future__ import annotations

import time
import uuid
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
        ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "unknown").split(",")[0].strip()
        if not allow(ip):
            abort(429)


def _read_csrf_from_request() -> Optional[str]:
    token = request.headers.get("X-CSRF-Token")
    if token:
        return token

    token = request.args.get("_csrf")
    if token:
        return token

    token = request.form.get("csrf_token")
    if token:
        return token

    if request.is_json:
        data = request.get_json(silent=True) or {}
        token = data.get("csrf_token")
        if token:
            return token

    return None


def install_csrf(app: Flask, settings: Settings) -> None:
    SAFE = {"GET", "HEAD", "OPTIONS"}

    @app.before_request
    def _csrf():
        if request.method in SAFE:
            return

        path = (request.path or "").lower()

        # allow public/webhook endpoints
        if (
            path.startswith("/chat_api")
            or path.startswith("/whatsapp")
            or path.startswith("/catalog_webhook")
            or path.startswith("/export_catalog_csv")
            or path.startswith("/health")
        ):
            return

        # IMPORTANT:
        # CSRF is required for admin form posts (including /admin/login)
        expected = session.get("_csrf")
        got = _read_csrf_from_request()

        if not expected or not got or got != expected:
            app.logger.warning("CSRF blocked: method=%s path=%s token=%r", request.method, path, got)
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
