"""
Logging setup.

Goals:
- Everything goes to console + logs/chatbot.log
- Errors + tracebacks ALSO go to logs/errors.log
- Analytics-only logs go to logs/analytics.log
- Request-id included when available
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config import Settings


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        return True


def _rotating(path: Path, level: int) -> RotatingFileHandler:
    path.parent.mkdir(parents=True, exist_ok=True)
    h = RotatingFileHandler(
        path,
        maxBytes=5_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    h.setLevel(level)
    h.addFilter(RequestIdFilter())
    h.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s %(request_id)s - %(message)s")
    )
    return h


def configure_logging(settings: Settings) -> None:
    logs_dir = Path(os.getenv("LOG_DIR", "logs"))

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Avoid duplicate handlers on reloads
    root.handlers = []

    # Console
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.addFilter(RequestIdFilter())
    console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s"))
    root.addHandler(console)

    # Main runtime file: catches app.logger + everything unless you override
    runtime = _rotating(logs_dir / "chatbot.log", logging.INFO)
    root.addHandler(runtime)

    # Errors file: only ERROR+ (includes app.logger.exception tracebacks)
    errors = _rotating(logs_dir / "errors.log", logging.ERROR)
    root.addHandler(errors)

    # Analytics file: only analytics logger
    analytics = _rotating(logs_dir / "analytics.log", logging.INFO)
    a = logging.getLogger("Analytics")
    a.setLevel(logging.INFO)
    a.propagate = False  # prevent double-writing into chatbot.log
    a.handlers = []
    a.addHandler(analytics)
    a.addHandler(console)  # optional: show analytics in console too
