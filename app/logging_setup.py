"""
Logging setup.

- Rotating file handlers for runtime, analytics, errors
- Request ID aware formatter
"""

from __future__ import annotations
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config import Settings


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Middleware stores request_id in record if present
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        return True


def _mk_handler(path: Path, level: int) -> RotatingFileHandler:
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(path, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    handler.setLevel(level)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s %(request_id)s - %(message)s"
    )
    handler.setFormatter(fmt)
    handler.addFilter(RequestIdFilter())
    return handler


def configure_logging(settings: Settings) -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Console (dev)
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s"))
    root.addHandler(console)

    # Files
    logs_dir = Path("logs")
    runtime = _mk_handler(logs_dir / "chatbot.log", logging.INFO)
    errors = _mk_handler(logs_dir / "errors.log", logging.ERROR)
    analytics = _mk_handler(logs_dir / "analytics.log", logging.INFO)

    logging.getLogger("Runtime").addHandler(runtime)
    logging.getLogger("Heartbeat").addHandler(runtime)
    logging.getLogger("Probes").addHandler(runtime)
    logging.getLogger("Analytics").addHandler(analytics)
    logging.getLogger().addHandler(errors)
