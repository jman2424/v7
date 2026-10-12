from datetime import date
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock
import json
import wave
import httpx
from openai import RateLimitError

import pytest

from service import analytics_db, api_usage, plan_usage, speech_transcription, subscriptions
from service import usage_currency, usage_pricing, usage_wallet


@pytest.fixture
def credit(tmp_path, monkeypatch):
    monkeypatch.setenv("SECURITY_DB_PATH", str(tmp_path / "security.db"))
    monkeypatch.setattr(analytics_db, "DB_PATH", str(tmp_path / "analytics.db"))
    monkeypatch.setattr(subscriptions, "internal_business", lambda tenant: False)
    monkeypatch.setattr(usage_currency, "gbp_rate", lambda: {
        "rate": 0.8, "date": date.today().isoformat(), "stale": False})
    monkeypatch.setenv("V7_USAGE_MARKUP_PERCENT", "25")
    monkeypatch.delenv("V7_MODEL_PRICING_JSON", raising=False)
    monkeypatch.delenv("V7_AUDIO_PRICING_JSON", raising=False)
    usage_wallet.adjust("EXAMPLE", 500, "Test prepaid funding", "test-admin", "fund-example")


def response(**changes):
    return SimpleNamespace(**{"model": "gpt-4o-mini", "service_tier": "default",
        "usage": SimpleNamespace(prompt_tokens=2000, completion_tokens=500,
                                  prompt_tokens_details=SimpleNamespace(cached_tokens=1000)), **changes})


def provider(result=None):
    client = Mock()
    client.chat.completions.create.return_value = result or response()
    return client


def request(client, tenant="EXAMPLE", **kwargs):
    with api_usage.usage_context(tenant, "web", "v7"):
        return api_usage.tracked_completion(client, purpose="planning", model="gpt-4o-mini",
            messages=[{"role": "user", "content": "A private customer prompt"}], **kwargs)


def test_exact_cached_token_charge_is_tenant_scoped_with_frozen_fx_markup(credit):
    client = provider()
    request(client)
    report = usage_wallet.report("EXAMPLE")
    assert report["balance_nano_gbp"] == 5_000_000_000 - 525_000
    assert report["reserved_nano_gbp"] == 0
    assert usage_wallet.report("OTHER")["balance_nano_gbp"] == 0
    entry = next(row for row in report["transactions"] if row["kind"] == "usage")
    assert entry["amount_nano_gbp"] == -525_000
    assert entry["usage"]["provider_cost_nano_usd"] == 525_000
    assert entry["usage"]["input_tokens"] == 2000
    assert entry["usage"]["cached_tokens"] == 1000
    assert entry["usage"]["output_tokens"] == 500
    assert entry["usage"]["fx_rate"] == "0.8"
    assert entry["usage"]["markup_percent"] == "25"
    assert entry["usage"]["model"] == "gpt-4o-mini"
    assert entry["created_utc"] and entry["usage"]["price_version"]
    assert "private customer prompt" not in json.dumps(report)


def test_reservation_covers_configured_cached_rate_above_regular_input(credit, monkeypatch):
    monkeypatch.setenv("V7_MODEL_PRICING_JSON", json.dumps({
        "gpt-4o-mini": {"input": 1, "cached": 5000, "output": 1}}))
    options = {"model": "gpt-4o-mini", "max_tokens": 100,
               "messages": [{"role": "user", "content": "Hello"}]}
    pricing = usage_pricing.snapshot()
    ceiling = api_usage.completion_ceiling(options, pricing=pricing)
    encoded = json.dumps({"messages": options["messages"]}, ensure_ascii=False).encode("utf-8")
    assert ceiling == (len(encoded) + 256 + 2048) * 5000 + 100
    actual = api_usage.completion_usage(response(usage=SimpleNamespace(
        prompt_tokens=1000, completion_tokens=100,
        prompt_tokens_details=SimpleNamespace(cached_tokens=1000))),
        "gpt-4o-mini", "planning", "completed", pricing=pricing)
    assert actual["cost_nano_usd"] == 5_000_100 <= ceiling


def test_missing_or_invalid_business_context_never_calls_provider(credit):
    client = provider()
    with pytest.raises(plan_usage.AllowancePaused):
        api_usage.tracked_completion(client, purpose="planning", model="gpt-4o-mini")
    with pytest.raises(plan_usage.AllowancePaused):
        request(client, "../OTHER")
    client.chat.completions.create.assert_not_called()


def test_same_tokens_consume_credit_at_each_selected_models_price(credit,monkeypatch):
    usage_wallet.adjust('OTHER',500,'Same test funding','test-admin','fund-other')
    configuration={'model':'gpt-4o-mini'}
    monkeypatch.setattr('service.model_settings.document',lambda storage,tenant:dict(configuration))
    request(provider(response(model='gpt-4o-mini')))
    configuration['model']='gpt-4o'
    expensive=provider(response(model='gpt-4o'))
    request(expensive,'OTHER')
    assert expensive.chat.completions.create.call_args.kwargs['model']=='gpt-4o'
    cheap=usage_wallet.report('EXAMPLE')
    dear=usage_wallet.report('OTHER')
    assert cheap['spent_nano_gbp']==525_000
    assert dear['spent_nano_gbp']==8_750_000
    assert dear['available_nano_gbp']<cheap['available_nano_gbp']


def test_empty_other_tenant_is_blocked_before_call_even_with_chatgpt_claim(credit):
    client = provider()
    with pytest.raises(plan_usage.AllowancePaused):
        request(client, "OTHER", billing_source="chatgpt")
    client.chat.completions.create.assert_not_called()
    assert usage_wallet.report("EXAMPLE")["balance_pence"] == 500


def test_timeout_keeps_hold_and_blocks_next_chargeable_call(credit):
    client = provider()
    client.chat.completions.create.side_effect = TimeoutError("private timeout details")
    with pytest.raises(TimeoutError):
        request(client)
    report = usage_wallet.report("EXAMPLE")
    assert report["reserved_nano_gbp"] > 0
    assert report["balance_pence"] == 500
    assert report["reconciliation_hold"] and report["unknown_reservations"] == 1
    with pytest.raises(plan_usage.AllowancePaused):
        request(client)
    assert client.chat.completions.create.call_count == 1
    assert "private timeout details" not in json.dumps(report)


def test_explicit_provider_quota_rejection_releases_hold_without_charging(credit):
    client = provider()
    client.chat.completions.create.side_effect = RateLimitError("private provider detail",
        response=httpx.Response(429, request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")),
        body={"code": "insufficient_quota", "type": "insufficient_quota"})
    with pytest.raises(RateLimitError):
        request(client)
    report = usage_wallet.report("EXAMPLE")
    assert report["balance_pence"] == 500 and report["reserved_nano_gbp"] == 0
    assert report["spent_nano_gbp"] == 0 and not report["reconciliation_hold"]
    assert "private provider detail" not in json.dumps(report)
    request(provider())
    assert usage_wallet.report("EXAMPLE")["spent_nano_gbp"] == 525_000


def test_configurable_fx_is_validated_and_frozen(credit, monkeypatch):
    monkeypatch.setenv("V7_USAGE_USD_GBP_RATE", "0.9")
    monkeypatch.setenv("V7_USAGE_RATE_DATE", date.today().isoformat())
    assert usage_currency.cached_gbp_rate()["rate"] == 0.9
    monkeypatch.setenv("V7_USAGE_RATE_DATE", "2000-01-01")
    assert usage_currency.cached_gbp_rate()["stale"] is True
    monkeypatch.setenv("V7_USAGE_USD_GBP_RATE", "NaN")
    assert usage_currency.cached_gbp_rate() is None


def test_financial_settlement_survives_analytics_outage(credit, monkeypatch, caplog):
    def unavailable(*args, **kwargs):
        raise OSError("private database detail")
    monkeypatch.setattr(api_usage, "_record", unavailable)
    request(provider())
    report = usage_wallet.report("EXAMPLE")
    assert report["spent_nano_gbp"] == 525_000
    assert report["reserved_nano_gbp"] == 0
    assert "API usage recording failed (OSError)" in caplog.text
    assert "private database detail" not in caplog.text


def test_pricing_changes_during_request_do_not_reprice_existing_reservation(credit, monkeypatch):
    initial = {"gpt-4o-mini": {"input": 200, "cached": 50, "output": 800}}
    monkeypatch.setenv("V7_MODEL_PRICING_JSON", json.dumps(initial))
    client = provider()
    def complete(**kwargs):
        monkeypatch.setenv("V7_MODEL_PRICING_JSON", json.dumps({
            "gpt-4o-mini": {"input": 900, "cached": 900, "output": 900}}))
        monkeypatch.setenv("V7_USAGE_MARKUP_PERCENT", "100")
        return response()
    client.chat.completions.create.side_effect = complete
    request(client)
    report = usage_wallet.report("EXAMPLE")
    assert report["spent_nano_gbp"] == 650_000
    entry = next(row for row in report["transactions"] if row["kind"] == "usage")
    assert entry["usage"]["rate_snapshot"] == {"input": 200, "cached": 50, "output": 800, "cache_write": 200,
        "long_context_threshold": 0, "long_input_multiplier": 1,
        "long_output_numerator": 1, "long_output_denominator": 1}
    assert entry["usage"]["markup_percent"] == "25"


@pytest.mark.parametrize("pricing", ["invalid", "[]", '{"gpt-4o-mini":{"input":true,"cached":1,"output":1}}',
    '{"gpt-4o-mini":{"input":-1,"cached":1,"output":1}}'])
def test_invalid_configured_price_fails_closed(credit, monkeypatch, pricing):
    monkeypatch.setenv("V7_MODEL_PRICING_JSON", pricing)
    client = provider()
    with pytest.raises(plan_usage.AllowancePaused):
        request(client)
    client.chat.completions.create.assert_not_called()
    assert any(row["code"] == "pricing_unavailable" for row in usage_wallet.report("EXAMPLE")["alerts"])


@pytest.mark.parametrize("kwargs", [{"n": 2}, {"stream": True}, {"service_tier": "priority"}])
def test_unbounded_pricing_options_do_not_call_provider(credit, kwargs):
    client = provider()
    with pytest.raises(plan_usage.AllowancePaused):
        request(client, **kwargs)
    client.chat.completions.create.assert_not_called()


def test_response_usage_above_ceiling_keeps_nonnegative_balance_and_review_hold(credit):
    too_large = SimpleNamespace(prompt_tokens=2000, completion_tokens=1_000_000,
                                prompt_tokens_details=SimpleNamespace(cached_tokens=1000))
    request(provider(response(usage=too_large)))
    report = usage_wallet.report("EXAMPLE")
    assert report["balance_pence"] == 500 and report["reserved_nano_gbp"] > 0
    assert report["reconciliation_hold"] and report["paused"]
    assert report["spent_nano_gbp"] == 0


def test_explicit_internal_workspace_is_tracked_without_customer_charge(credit, monkeypatch):
    monkeypatch.setattr(subscriptions, "internal_business", lambda tenant: tenant == "VERTEX")
    request(provider(), "VERTEX")
    assert api_usage.summary("VERTEX", 30)["totals"]["calls"] == 1
    assert usage_wallet.report("VERTEX")["total"] == 0


def test_cache_writes_and_long_context_price_remain_exact(credit):
    details = api_usage.completion_usage(response(model="gpt-6-luna", usage=SimpleNamespace(
        prompt_tokens=300_000, completion_tokens=501,
        prompt_tokens_details=SimpleNamespace(cached_tokens=50_000, cache_write_tokens=10_000))),
        "gpt-6-luna", "planning", "completed")
    assert details["cost_nano_usd"] == (240_000 * 100 + 50_000 * 10 + 10_000 * 125) * 2 + 501 * 500 * 3 // 2


def test_configured_long_context_fractional_nano_cost_rounds_up(credit, monkeypatch):
    monkeypatch.setenv("V7_MODEL_PRICING_JSON", json.dumps({"gpt-6-luna": {
        "input": 0, "cached": 0, "output": 1, "long_context": True}}))
    details = api_usage.completion_usage(response(model="gpt-6-luna", usage=SimpleNamespace(
        prompt_tokens=272001, completion_tokens=1, prompt_tokens_details=SimpleNamespace(cached_tokens=0))),
        "gpt-6-luna", "planning", "completed")
    assert details["cost_nano_usd"] == 2


def test_paid_transcription_has_same_wallet_gate_and_metadata(credit, monkeypatch):
    audio = BytesIO()
    with wave.open(audio, "wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(8000)
        recording.writeframes(b"\0" * 16000)
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    monkeypatch.setenv("V7_TRANSCRIPTION_MODEL", "gpt-transcribe")
    fake = Mock()
    fake.audio.transcriptions.create.return_value = SimpleNamespace(
        text="Please help", usage=SimpleNamespace(type="duration", seconds=1))
    monkeypatch.setattr(speech_transcription, "OpenAI", lambda **kwargs: fake)
    assert speech_transcription.transcribe_audio(audio.getvalue(), "audio/wav", tenant="EXAMPLE", channel="web") == "Please help"
    assert usage_wallet.report("EXAMPLE")["spent_nano_gbp"] == 75_000
    with pytest.raises(speech_transcription.SpeechTranscriptionError):
        speech_transcription.transcribe_audio(audio.getvalue(), "audio/wav", tenant="OTHER", channel="web")
    assert fake.audio.transcriptions.create.call_count == 1


def test_workspace_credit_notification_is_authenticated_and_discloses_no_amounts(client):
    from tests.conftest import set_test_identity
    usage_wallet.adjust("EXAMPLE", 100, "Test low credit funding", "test-admin", "fund-example")
    usage_wallet.adjust("OTHER", 1000, "Test other credit funding", "test-admin", "fund-other")
    assert client.get("/admin/api/activation?tenant=EXAMPLE").status_code == 401
    with client.session_transaction() as state:
        set_test_identity(client, state, {"id": "wallet-notice-staff", "role": "business_staff",
            "tenant": "EXAMPLE", "permissions": ["integrations.read"]})
    result = client.get("/admin/api/activation?tenant=EXAMPLE")
    assert result.status_code == 200
    assert any(item["code"] == "low_credit" for item in result.json["usage_credit_alerts"])
    assert "pence" not in json.dumps(result.json) and "nano_gbp" not in json.dumps(result.json)
    assert client.get("/admin/api/activation?tenant=OTHER").status_code == 403
