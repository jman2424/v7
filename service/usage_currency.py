"""Cached public reference rate; no customer data is sent to the rate provider."""
from __future__ import annotations

import json
import logging
import math
import threading
import time
from contextlib import closing
from datetime import date
from urllib.request import Request, urlopen

from service import analytics_db, session_store

URL = "https://api.frankfurter.dev/v2/providers/ecb/rate/usd/gbp"
_lock = threading.Lock()
_next_refresh = 0.0


def gbp_rate() -> dict | None:
    global _next_refresh
    if session_store._using_postgres():
        with _lock, session_store.postgres_connection() as con:
            if time.monotonic() >= _next_refresh:
                _next_refresh = time.monotonic() + 900
                try:
                    request = Request(URL, headers={"User-Agent": "V7-Usage/1.0", "Accept": "application/json"})
                    with urlopen(request, timeout=3) as response:
                        data = json.loads(response.read(16384))
                    rate = float(data["rate"])
                    rate_date = date.fromisoformat(data["date"])
                    if (data.get("base") != "USD" or data.get("quote") != "GBP"
                            or not math.isfinite(rate) or not 0 < rate < 10 or rate_date > date.today()):
                        raise ValueError("invalid_reference_rate")
                    con.execute(
                        "INSERT INTO v7_private.usage_exchange_rate (pair, rate, rate_date) "
                        "VALUES ('USD/GBP', %s, %s) ON CONFLICT (pair) DO UPDATE "
                        "SET rate=excluded.rate, rate_date=excluded.rate_date",
                        (rate, rate_date.isoformat()),
                    )
                    _next_refresh = time.monotonic() + 3600
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    logging.getLogger(__name__).warning("Usage currency refresh unavailable (%s)", type(exc).__name__)
            row = con.execute(
                "SELECT rate, rate_date FROM v7_private.usage_exchange_rate WHERE pair='USD/GBP'"
            ).fetchone()
            if row is None:
                return None
            return {"rate": row[0], "date": row[1], "source": "ECB via Frankfurter",
                    "stale": (date.today() - date.fromisoformat(row[1])).days > 4}
    with _lock, closing(analytics_db._conn()) as con, con:
        con.execute("""CREATE TABLE IF NOT EXISTS usage_exchange_rate (
            pair TEXT PRIMARY KEY, rate REAL NOT NULL, rate_date TEXT NOT NULL)""")
        if time.monotonic() >= _next_refresh:
            # Retry outages after 15 minutes; refresh successful lookups hourly.
            _next_refresh = time.monotonic() + 900
            try:
                request = Request(URL, headers={"User-Agent": "V7-Usage/1.0", "Accept": "application/json"})
                with urlopen(request, timeout=3) as response:
                    data = json.loads(response.read(16384))
                rate = float(data["rate"])
                rate_date = date.fromisoformat(data["date"])
                if (data.get("base") != "USD" or data.get("quote") != "GBP"
                        or not math.isfinite(rate) or not 0 < rate < 10 or rate_date > date.today()):
                    raise ValueError("invalid_reference_rate")
                con.execute("INSERT OR REPLACE INTO usage_exchange_rate VALUES ('USD/GBP', ?, ?)",
                            (rate, rate_date.isoformat()))
                _next_refresh = time.monotonic() + 3600
            except (OSError, ValueError, KeyError, TypeError) as exc:
                logging.getLogger(__name__).warning("Usage currency refresh unavailable (%s)", type(exc).__name__)
        row = con.execute("SELECT rate, rate_date FROM usage_exchange_rate WHERE pair = 'USD/GBP'").fetchone()
        if row is None:
            return None
        return {"rate": row["rate"], "date": row["rate_date"], "source": "ECB via Frankfurter",
                "stale": (date.today() - date.fromisoformat(row["rate_date"])).days > 4}
