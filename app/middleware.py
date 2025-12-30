"""
Middleware installers for Flask.

- Request ID injection
- Simple IP rate limiting
- CSRF protection (supports: header, query, form, JSON)
- Timing metrics -> AnalyticsService
"""

from __future__ import annotations

import secrets
import time
import uuid
from collections import defaultdict
from typing import Dict, Optional, Set

from flask import Flask, g, request, abort, session

from app.config import Settings


# ----------------------------
# Request ID
# ----------------------------

def install_request_id(app: Flask) -> None:
    @app.before_request
    def _req_id():
        g.request_id = request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex[:12]}"

    @app.after_request
    def _stamp(response):
        response.headers["X-Request-ID"] = g.get("request_id", "-")
        return response


# ----------------------------
# Rate limiting (simple token bucket)
# ----------------------------

def _client_ip() -> str:
    # Render puts the real client in X-Forwarded-For (comma separated)
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip() or "unknown"
    return request.remote_addr or "unknown"


def install_rate_limit(app: Flask, settings: Settings) -> None:
    buckets: Dict[str, Dict[str, float]] = defaultdict(
        lambda: {"tokens": float(settings.RATE_LIMIT_PER_MIN), "ts": time.time()}
    )

    def allow(ip: str) -> bool:
        now = time.time()
        b = buckets[ip]
        refill = (now - b["ts"]) * (float(settings.RATE_LIMIT_PER_MIN) / 60.0)

        cap = float(settings.RATE_LIMIT_PER_MIN) + float(settings.RATE_LIMIT_BURST)
        b["tokens"] = min(cap, b["tokens"] + refill)
        b["ts"] = now

        if b["tokens"] >= 1.0:
            b["tokens"] -= 1.0
            return True
        return False

    @app.before_request
    def _rl():
        ip = _client_ip()
        if not allow(ip):
            abort(429)


# ----------------------------
# CSRF
# ----------------------------

def _ensure_csrf_token() -> str:
    """
    Create per-session CSRF token if missing.
    Must be called on safe requests too, so forms can render a token.
    """
    tok = session.get("_csrf")
    if not tok:
        tok = secrets.token_urlsafe(32)
        session["_csrf"] = tok
    return tok


def _read_csrf_from_request() -> Optional[str]:
    # 1) header (fetch / ajax)
    token = request.headers.get("X-CSRF-Token")
    if token:
        return token

    # 2) query string (?_csrf=...)
    token = request.args.get("_csrf")
    if token:
        return token

    # 3) HTML forms
    token = request.form.get("csrf_token")
    if token:
        return token

    # 4) JSON body
    if request.is_json:
        data = request.get_json(silent=True) or {}
        token = data.get("csrf_token")
        if token:
            return token

    return None


def install_csrf(app: Flask, settings: Settings) -> None:
    SAFE: Set[str] = {"GET", "HEAD", "OPTIONS"}

    # Make csrf_token available in ALL templates: {{ csrf_token }}
    @app.context_processor
    def _inject_csrf():
        return {"csrf_token": _ensure_csrf_token()}

    @app.before_request
    def _csrf():
        # Always ensure token exists so login page can render it
        _ensure_csrf_token()

        if request.method in SAFE:
            return

        path = (request.path or "").lower()

        # Skip CSRF for webhooks and public endpoints
        if (
            path.startswith("/whatsapp")
            or path.startswith("/chat_api")
            or path.startswith("/health")
            or path.startswith("/__diag")
        ):
            return

        expected = session.get("_csrf")
        got = _read_csrf_from_request()

        if not expected or not got or got != expected:
            app.logger.warning(
                "CSRF blocked: method=%s path=%s token=%r expected=%r",
                request.method,
                request.path,
                got,
                (expected[:6] + "...") if expected else None,
            )
            abort(403, description="csrf_failed")


# ----------------------------
# Timing metrics
# ----------------------------

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
