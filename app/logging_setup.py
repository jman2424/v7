from __future__ import annotations

import logging
import os
import re
import traceback
from copy import copy
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import quote, quote_plus

from flask import g, has_request_context

from app.config import Settings


class SafeFormatter(logging.Formatter):
    """Keep exception types/frames while excluding secret values and messages."""

    def formatException(self, exc_info) -> str:
        frames = traceback.extract_tb(exc_info[2])
        return "\n".join(f"{frame.filename}:{frame.lineno} in {frame.name}" for frame in frames) + "\n" + exc_info[0].__name__

    def format(self, record: logging.LogRecord) -> str:
        record = copy(record)
        # Other handlers may have cached an exception containing private text.
        record.exc_text = None
        if isinstance(record.args, tuple):
            record.args = tuple(type(value).__name__ if isinstance(value, BaseException) else value for value in record.args)
        elif isinstance(record.args, dict):
            record.args = {key: type(value).__name__ if isinstance(value, BaseException) else value for key, value in record.args.items()}
        output = super().format(record)
        for key, value in os.environ.items():
            if value and len(value) >= 8 and any(marker in key.upper() for marker in ("SECRET", "TOKEN", "PASSWORD", "API_KEY", "SERVICE_JSON", "DSN", "DATABASE_URL")):
                for spelling in {value, quote(value, safe=""), quote_plus(value)}:
                    output = output.replace(spelling, "[REDACTED]")
        return re.sub(r"(?i)([?&](?:token|access_token|refresh_token|api_key|hub(?:\.|%2e)verify_token|code|password|client_secret)=)[^&\s]+", r"\1[REDACTED]", output)


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = getattr(g, "request_id", "-") if has_request_context() else "-"
        return True


def _mk_handler(path: Path, level: int) -> RotatingFileHandler:
    path.parent.mkdir(parents=True, exist_ok=True)
    h = RotatingFileHandler(path, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    h.setLevel(level)
    h.setFormatter(
        SafeFormatter("%(asctime)s [%(levelname)s] %(name)s %(request_id)s - %(message)s")
    )
    h.addFilter(RequestIdFilter())
    return h


def configure_logging(settings: Settings) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)

    # Console (Render shows stdout/stderr)
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(SafeFormatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s"))
    console.addFilter(RequestIdFilter())
    root.addHandler(console)

    console_err = logging.StreamHandler()
    console_err.setLevel(logging.ERROR)
    console_err.setFormatter(SafeFormatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s"))
    root.addHandler(console_err)

    # Optional file logs (useful locally; Render won’t show them)
    data_root = (os.getenv("V7_DATA_DIR") or "").strip()
    logs_dir = Path(os.environ.get("LOG_DIR") or (str(Path(data_root) / "logs") if data_root else "logs"))
    runtime = _mk_handler(logs_dir / "chatbot.log", logging.INFO)
    errors = _mk_handler(logs_dir / "errors.log", logging.ERROR)
    analytics = _mk_handler(logs_dir / "analytics.log", logging.INFO)

    logging.getLogger("Runtime").addHandler(runtime)
    logging.getLogger("Analytics").addHandler(analytics)
    root.addHandler(errors)

    # Make Flask/Gunicorn loggers propagate to root
    logging.getLogger("gunicorn.error").propagate = True
    logging.getLogger("gunicorn.access").propagate = True
