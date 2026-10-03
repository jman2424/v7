"""Cached public reference rate; no customer data is sent to the rate provider."""
from __future__ import annotations

import json
import logging
import math
import threading
import time
from contextlib import closing, contextmanager
from datetime import date
from urllib.request import Request, urlopen

from service import analytics_db, session_store

URL = "https://api.frankfurter.dev/v2/providers/ecb/rate/usd/gbp"
_lock = threading.Lock()
_next_refresh = 0.0


@contextmanager
def _rate_connection():
    if session_store._using_postgres():
        with session_store.postgres_connection() as con:
            yield con
    else:
        with closing(analytics_db._conn()) as con, con:
            con.execute("""CREATE TABLE IF NOT EXISTS usage_exchange_rate (
                pair TEXT PRIMARY KEY, rate REAL NOT NULL, rate_date TEXT NOT NULL)""")
            yield con


def cached_gbp_rate() -> dict | None:
    """Read an existing public reference without waiting for a provider refresh."""
    table = "v7_private.usage_exchange_rate" if session_store._using_postgres() else "usage_exchange_rate"
    with _rate_connection() as con:
        row = con.execute(f"SELECT rate, rate_date FROM {table} WHERE pair='USD/GBP'").fetchone()
    if row is None:
        return None
    return {"rate": row[0], "date": row[1], "source": "ECB via Frankfurter",
            "stale": (date.today() - date.fromisoformat(row[1])).days > 4}


def gbp_rate() -> dict | None:
    global _next_refresh
    # Reserve one refresh under a short lock. Other dashboard reads use the
    # saved rate instead of queueing behind an external request or its DB lease.
    with _lock:
        refresh = time.monotonic() >= _next_refresh
        if refresh:
            _next_refresh = time.monotonic() + 900
    if refresh:
        try:
            request = Request(URL, headers={"User-Agent": "V7-Usage/1.0", "Accept": "application/json"})
            with urlopen(request, timeout=3) as response:
                body = response.read(16385)
            if len(body) > 16384:
                raise ValueError("invalid_reference_rate")
            data = json.loads(body)
            if not isinstance(data, dict) or isinstance(data.get("rate"), bool):
                raise ValueError("invalid_reference_rate")
            rate = float(data["rate"])
            rate_date = date.fromisoformat(data["date"])
            if (data.get("base") != "USD" or data.get("quote") != "GBP"
                    or not math.isfinite(rate) or not 0 < rate < 10 or rate_date > date.today()):
                raise ValueError("invalid_reference_rate")
        except (OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
            logging.getLogger(__name__).warning("Usage currency refresh unavailable (%s)", type(exc).__name__)
        else:
            with _rate_connection() as con:
                if session_store._using_postgres():
                    con.execute(
                        "INSERT INTO v7_private.usage_exchange_rate (pair, rate, rate_date) "
                        "VALUES ('USD/GBP', %s, %s) ON CONFLICT (pair) DO UPDATE "
                        "SET rate=excluded.rate, rate_date=excluded.rate_date",
                        (rate, rate_date.isoformat()),
                    )
                else:
                    con.execute("INSERT OR REPLACE INTO usage_exchange_rate VALUES ('USD/GBP', ?, ?)",
                                (rate, rate_date.isoformat()))
            with _lock:
                _next_refresh = time.monotonic() + 3600
    return cached_gbp_rate()
