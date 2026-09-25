from types import SimpleNamespace
from unittest.mock import Mock
from datetime import date
import io
import json

import pytest

from service import api_usage, analytics_db, usage_currency
from tests.conftest import set_test_identity


def completion(**overrides):
    return SimpleNamespace(**{
        "model": "gpt-4o-mini-2024-07-18", "service_tier": "default",
        "usage": SimpleNamespace(prompt_tokens=2000, completion_tokens=500,
                                 prompt_tokens_details=SimpleNamespace(cached_tokens=1000)),
        "choices": [SimpleNamespace(message=SimpleNamespace(content='{"intent":"unknown","action":"DO_NOTHING"}'))],
        **overrides,
    })


@pytest.fixture(autouse=True)
def fake_exchange(monkeypatch):
    monkeypatch.setattr(usage_currency, "_next_refresh", 0)
    data = {"base": "USD", "quote": "GBP", "rate": 0.75, "date": date.today().isoformat()}
    monkeypatch.setattr(usage_currency, "urlopen", lambda *a, **kw: io.BytesIO(json.dumps(data).encode()))


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(analytics_db, "DB_PATH", str(tmp_path / "usage.db"))


def record(tenant="EXAMPLE", channel="web", response=None):
    client = Mock()
    client.chat.completions.create.return_value = response or completion()
    with api_usage.usage_context(tenant, channel):
        api_usage.tracked_completion(client, purpose="planning", model="gpt-4o-mini")
    return client


def test_cached_input_is_not_double_counted_and_cost_is_stored(ledger, monkeypatch):
    record()
    monkeypatch.setitem(api_usage.RATES, "gpt-4o-mini-2024-07-18", (1, 1, 1))
    result = api_usage.summary("EXAMPLE", 30)
    totals = result["totals"]
    assert totals["total_tokens"] == 2500
    assert totals["cached_tokens"] == 1000
    assert totals["estimated_cost_usd"] == pytest.approx(0.000525)
    assert totals["unpriced_calls"] == 0
    assert result["breakdown"][0]["model"] == "gpt-4o-mini-2024-07-18"


def test_transcription_duration_and_tokens_are_attributed_without_audio(ledger):
    with api_usage.usage_context("EXAMPLE", "whatsapp"):
        api_usage.record_transcription(
            SimpleNamespace(usage=SimpleNamespace(type="duration", seconds=30)),
            "gpt-transcribe", "completed",
        )
        api_usage.record_transcription(
            SimpleNamespace(usage=SimpleNamespace(type="tokens", input_tokens=100,
                                                  output_tokens=20)),
            "gpt-4o-mini-transcribe", "completed",
        )
    result = api_usage.summary("EXAMPLE", 30)
    assert result["totals"]["calls"] == 2
    assert result["totals"]["audio_seconds"] == 30
    assert result["totals"]["missing_usage_calls"] == 0
    assert result["totals"]["estimated_cost_usd"] == pytest.approx(0.002475)
    assert {item["purpose"] for item in result["breakdown"]} == {"transcription"}


def test_empty_period_has_zero_recorded_cost_but_unpriced_calls_remain_unknown(ledger):
    empty = api_usage.summary("EXAMPLE", 30)
    assert empty["totals"]["calls"] == 0
    assert empty["totals"]["estimated_cost_usd"] == 0
    assert empty["first_recorded_at"] is None
    record(response=completion(usage=None))
    assert api_usage.summary("EXAMPLE", 30)["totals"]["estimated_cost_usd"] is None


def test_empty_gbp_cost_does_not_require_exchange_rate(client, monkeypatch):
    monkeypatch.setattr(usage_currency, "gbp_rate", lambda: None)
    with client.session_transaction() as state:
        set_test_identity(client, state, {"id": "empty-owner", "role": "business_owner", "tenant": "EXAMPLE"})
    report = client.get("/admin/api/api-usage").get_json()
    assert report["totals"]["estimated_cost_gbp"] == 0
    assert report["exchange_rate"] is None
    record()
    assert client.get("/admin/api/api-usage").get_json()["totals"]["estimated_cost_gbp"] is None


@pytest.mark.parametrize("response", [completion(model="new-unpriced-model"),
    completion(model="gpt-4o-mini-2099-01-01"), completion(model="ft:gpt-4o-mini:custom"),
    completion(usage=None), completion(service_tier="priority")])
def test_unknown_prices_or_usage_are_not_reported_as_free(ledger, response):
    record(response=response)
    totals = api_usage.summary("EXAMPLE", 30)["totals"]
    assert totals["estimated_cost_usd"] is None
    assert totals["unpriced_calls"] == 1


def test_failures_keep_existing_exception_and_reset_tenant_context(ledger):
    client = Mock()
    client.chat.completions.create.side_effect = TimeoutError("private-provider-details")
    with pytest.raises(TimeoutError), api_usage.usage_context("EXAMPLE", "test"):
        api_usage.tracked_completion(client, purpose="rewriting", model="gpt-4o-mini")
    assert api_usage._context.get() is None
    totals = api_usage.summary("EXAMPLE", 30)["totals"]
    assert totals["failed_calls"] == totals["missing_usage_calls"] == 1
    assert "private-provider-details" not in str(api_usage.summary("EXAMPLE", 30))


def test_tenants_channels_and_time_window_are_separate(ledger):
    record("EXAMPLE", "test")
    record("BETA", "whatsapp")
    record("EXAMPLE", "web")
    with analytics_db._conn() as con:
        con.execute("UPDATE api_usage SET ts_utc = '2000-01-01T00:00:00+00:00' WHERE channel = 'web'")
    result = api_usage.summary("EXAMPLE", 7)
    assert result["totals"]["calls"] == 1
    assert result["breakdown"][0]["channel"] == "test"
    assert api_usage.summary(None, 7)["totals"]["calls"] == 2


def test_brain_and_rewriter_record_real_completion_metadata(ledger):
    from brain_v7 import BrainV7
    from service.rewriter import Rewriter
    client = Mock()
    client.chat.completions.create.return_value = completion()
    brain = BrainV7(client=client)
    rewriter = Rewriter()
    rewriter._client = client
    with api_usage.usage_context("EXAMPLE", "test"):
        brain.plan("Can I get something suitable for a large dinner?")
        rewriter.rewrite("Here are the products available for your dinner.")
    rows = api_usage.summary("EXAMPLE", 30)["breakdown"]
    assert {row["purpose"] for row in rows} == {"planning", "rewriting"}
    assert sum(row["calls"] for row in rows) == 2


def test_usage_endpoint_enforces_company_and_platform_permissions(client):
    record("EXAMPLE")
    record("BETA")
    assert client.get("/admin/api/api-usage").status_code == 401
    with client.session_transaction() as state:
        set_test_identity(client, state, {"id": "usage-owner", "role": "business_owner", "tenant": "EXAMPLE"})
    own = client.get("/admin/api/api-usage?tenant=EXAMPLE").get_json()
    assert own["totals"]["calls"] == 1
    assert own["totals"]["estimated_cost_gbp"] == pytest.approx(0.00039375)
    assert own["currency"] == "GBP"
    assert own["configuration"]["planning_enabled"] is False
    assert client.get("/admin/api/api-usage?tenant=BETA").status_code == 403
    assert client.get("/admin/api/api-usage?scope=all").status_code == 403
    with client.session_transaction() as state:
        set_test_identity(client, state, {"id": "usage-staff", "role": "business_staff", "tenant": "EXAMPLE"})
    assert client.get("/admin/api/api-usage").status_code == 403
    with client.session_transaction() as state:
        set_test_identity(client, state, {"id": "usage-admin", "role": "platform_admin"})
    assert client.get("/admin/api/api-usage?scope=all").get_json()["totals"]["calls"] == 2
    assert client.get("/admin/api/api-usage?days=999").status_code == 400
    assert client.get("/admin/api/api-usage?scope=oops").status_code == 400


def test_test_agent_dispatch_accounts_for_paid_calls_without_customer_events(client, monkeypatch):
    from routes import get_container
    with client.application.app_context():
        container = get_container().for_tenant("EXAMPLE")
    client_stub = Mock()
    client_stub.chat.completions.create.return_value = completion()

    def handle(text, ctx, sess):
        api_usage.tracked_completion(client_stub, purpose="planning", model="gpt-4o-mini")
        return {"reply": "Test reply.", "intent": "store_info", "facts": {}, "resolved": True}

    monkeypatch.setattr(container.handler.h_v7, "handle", handle)
    with client.session_transaction() as state:
        set_test_identity(client, state, {"id": "test-owner", "role": "business_owner", "tenant": "EXAMPLE"})
    assert client.post("/admin/api/test-agent", json={"message": "Tell me about the business"}).status_code == 200
    result = client.get("/admin/api/api-usage").get_json()
    assert result["totals"]["calls"] == 1
    assert result["breakdown"][0]["channel"] == "test"
    assert api_usage._context.get() is None
    with analytics_db._conn() as con:
        assert con.execute("SELECT COUNT(*) FROM leads").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


def test_accounting_storage_failure_does_not_discard_paid_response(ledger, monkeypatch, caplog):
    def fail(*args, **kwargs):
        raise OSError("private filesystem detail")
    monkeypatch.setattr(api_usage, "_record", fail)
    client = record()
    assert client.chat.completions.create.call_count == 1
    assert "API usage recording failed (OSError)" in caplog.text
    assert "private filesystem detail" not in caplog.text


def test_currency_outage_uses_saved_rate_and_does_not_invent_rate(ledger, monkeypatch):
    def fail(*args, **kwargs):
        raise TimeoutError()
    assert usage_currency.gbp_rate()["rate"] == 0.75
    monkeypatch.setattr(usage_currency, "_next_refresh", 0)
    monkeypatch.setattr(usage_currency, "urlopen", fail)
    assert usage_currency.gbp_rate()["rate"] == 0.75
    with analytics_db._conn() as con:
        con.execute("DELETE FROM usage_exchange_rate")
    assert usage_currency.gbp_rate() is None


def test_currency_request_is_public_and_bounded(ledger, monkeypatch):
    def fetch(request, *, timeout):
        assert request.full_url == usage_currency.URL
        assert request.get_header("User-agent") == "V7-Usage/1.0"
        assert request.get_header("Accept") == "application/json"
        assert request.data is None
        assert timeout == 3
        return io.BytesIO(json.dumps({"base": "USD", "quote": "GBP", "rate": 0.74,
                                      "date": date.today().isoformat()}).encode())
    monkeypatch.setattr(usage_currency, "urlopen", fetch)
    assert usage_currency.gbp_rate()["rate"] == 0.74
