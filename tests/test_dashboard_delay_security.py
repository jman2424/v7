"""Slow public rate refreshes must not stall unrelated dashboard reads."""
from contextlib import contextmanager
from datetime import date
import io
import json
from threading import Event, Thread

import pytest

from service import analytics_db, session_store, usage_currency
from tests.conftest import set_test_identity


def reference_rate(rate=0.75):
    return io.BytesIO(json.dumps({"base": "USD", "quote": "GBP", "rate": rate,
                                 "date": date.today().isoformat()}).encode())


def test_empty_usage_dashboard_does_not_contact_exchange_provider(client, monkeypatch):
    with client.session_transaction() as state:
        set_test_identity(client, state, {"id": "empty-cost-owner", "role": "business_owner",
                                         "tenant": "EXAMPLE"})
    monkeypatch.setattr(usage_currency, "gbp_rate",
                        lambda: pytest.fail("Empty accounting contacted the exchange provider"))
    response = client.get("/admin/api/api-usage")
    assert response.status_code == 200
    assert response.json["totals"]["calls"] == 0
    assert response.json["totals"]["estimated_cost_gbp"] == 0
    assert response.json["exchange_rate"] is None
    assert response.headers["Cache-Control"] == "no-store"


def test_empty_usage_preserves_saved_reference_and_stale_marker(client, monkeypatch):
    with client.session_transaction() as state:
        set_test_identity(client, state, {"id": "empty-cost-owner", "role": "business_owner",
                                         "tenant": "EXAMPLE"})
    monkeypatch.setattr(usage_currency, "_next_refresh", 0)
    monkeypatch.setattr(usage_currency, "urlopen", lambda *args, **kwargs: reference_rate())
    assert usage_currency.gbp_rate()["rate"] == 0.75
    with analytics_db._conn() as con:
        con.execute("UPDATE usage_exchange_rate SET rate_date='2000-01-01'")
    monkeypatch.setattr(usage_currency, "gbp_rate",
                        lambda: pytest.fail("Empty accounting refreshed the saved reference"))
    response = client.get("/admin/api/api-usage")
    assert response.status_code == 200
    assert response.json["totals"]["estimated_cost_gbp"] == 0
    assert response.json["exchange_rate"] == {"rate": 0.75, "date": "2000-01-01",
                                              "source": "ECB via Frankfurter", "stale": True}


@pytest.mark.parametrize("kind", ["boolean_rate", "oversized_body"])
def test_malformed_exchange_response_preserves_saved_rate(tmp_path, monkeypatch, kind):
    monkeypatch.setattr(analytics_db, "DB_PATH", str(tmp_path / "rates.db"))
    monkeypatch.setattr(usage_currency, "_next_refresh", 0)
    monkeypatch.setattr(usage_currency, "urlopen", lambda *args, **kwargs: reference_rate())
    assert usage_currency.gbp_rate()["rate"] == 0.75
    body = reference_rate(0.76).getvalue()
    if kind == "boolean_rate":
        data = json.loads(body)
        data["rate"] = True
        body = json.dumps(data).encode()
    else:
        body += b" " * (16384 - len(body)) + b"x"
    monkeypatch.setattr(usage_currency, "_next_refresh", 0)
    monkeypatch.setattr(usage_currency, "urlopen", lambda *args, **kwargs: io.BytesIO(body))
    result = usage_currency.gbp_rate()
    assert result["rate"] == 0.75
    assert result["stale"] is False


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
def test_saved_rate_reads_do_not_wait_for_inflight_provider_refresh(tmp_path, monkeypatch, backend):
    monkeypatch.setattr(usage_currency, "_next_refresh", 0)
    monkeypatch.setattr(session_store, "_using_postgres", lambda: backend == "postgres")
    monkeypatch.setattr(analytics_db, "DB_PATH", str(tmp_path / "rates.db"))
    saved = {"rate": None}
    active_connections = []

    class Database:
        def execute(self, sql, parameters=()):
            if sql.startswith("INSERT"):
                saved["rate"] = parameters
            return self

        def fetchone(self):
            return saved["rate"]

    @contextmanager
    def postgres_connection():
        active_connections.append(True)
        try:
            yield Database()
        finally:
            active_connections.pop()

    monkeypatch.setattr(session_store, "postgres_connection", postgres_connection)
    monkeypatch.setattr(usage_currency, "urlopen", lambda *args, **kwargs: reference_rate())
    assert usage_currency.gbp_rate()["rate"] == 0.75
    monkeypatch.setattr(usage_currency, "_next_refresh", 0)
    entered, release, returned = Event(), Event(), Event()
    results, failures = [], []
    connections_during_fetch = []

    def blocked_fetch(*args, **kwargs):
        connections_during_fetch.append(len(active_connections))
        entered.set()
        if not release.wait(5):
            raise TimeoutError()
        return reference_rate(0.76)

    def read_saved_rate():
        try:
            results.append(usage_currency.gbp_rate())
        except Exception as error:
            failures.append(error)
        finally:
            returned.set()

    monkeypatch.setattr(usage_currency, "urlopen", blocked_fetch)
    refresher = Thread(target=read_saved_rate)
    reader = Thread(target=read_saved_rate)
    try:
        refresher.start()
        assert entered.wait(2), "Reference refresh did not start"
        reader.start()
        assert returned.wait(2), "Saved rate read queued behind the external provider"
        assert results[0]["rate"] == 0.75
        assert connections_during_fetch == [0]
    finally:
        release.set()
        refresher.join(3)
        if reader.ident is not None:
            reader.join(3)
    assert not refresher.is_alive() and not reader.is_alive()
    assert not failures
    assert len(results) == 2 and results[-1]["rate"] == 0.76
