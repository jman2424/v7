from concurrent.futures import ThreadPoolExecutor
from datetime import date
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock
import wave

import pytest

from service import analytics_db, api_usage, plan_usage, speech_transcription, subscriptions, usage_currency, usage_wallet


@pytest.fixture
def plan_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("SECURITY_DB_PATH", str(tmp_path / "security.db"))
    monkeypatch.setattr(analytics_db, "DB_PATH", str(tmp_path / "analytics.db"))
    plan = {"website_conversations": 2, "whatsapp_messages": 2, "ai_budget_pence": 100}
    monkeypatch.setattr(plan_usage, "_plan", lambda tenant: dict(plan))
    monkeypatch.setattr(usage_currency, "gbp_rate", lambda: {"rate": 1, "date": date.today().isoformat(), "stale": False})
    monkeypatch.setenv("V7_USAGE_MARKUP_PERCENT", "0")
    monkeypatch.setattr(subscriptions, "internal_business", lambda tenant: False)
    return plan


def test_website_counts_once_and_existing_conversation_continues_at_limit(plan_ledger):
    assert plan_usage.use_resource("EXAMPLE", "website_conversations", "signed-session-1")
    assert plan_usage.use_resource("EXAMPLE", "website_conversations", "signed-session-1")
    assert plan_usage.use_resource("EXAMPLE", "website_conversations", "signed-session-2")
    assert not plan_usage.use_resource("EXAMPLE", "website_conversations", "signed-session-3")
    assert plan_usage.use_resource("EXAMPLE", "website_conversations", "signed-session-1")
    report = plan_usage.report("EXAMPLE")
    assert report["website_conversations"] == {"used": 2, "limit": 2, "paused": True}
    assert report["whatsapp_messages"]["used"] == 0
    assert report["alerts"][0]["resource"] == "website_conversations"
    with plan_usage._connection("EXAMPLE") as db:
        rows = [dict(row) for row in db.execute("SELECT * FROM billing_plan_events").fetchall()]
    assert "signed-session" not in str(rows)


def test_atomic_parallel_requests_and_provider_retry_dedupe(plan_ledger):
    with ThreadPoolExecutor(max_workers=8) as pool:
        accepted = list(pool.map(lambda index: plan_usage.use_resource("EXAMPLE", "whatsapp_messages", str(index)), range(20)))
    assert sum(accepted) == 2
    assert plan_usage.report("EXAMPLE")["whatsapp_messages"]["used"] == 2
    assert plan_usage.use_resource("BETA", "whatsapp_messages", "0")
    assert plan_usage.report("BETA")["whatsapp_messages"]["used"] == 1


def test_money_based_whatsapp_counts_beyond_previous_cap_and_deduplicates(plan_ledger):
    plan_ledger["message_usage_model"] = "ai_cost"
    with ThreadPoolExecutor(max_workers=8) as pool:
        accepted = list(pool.map(lambda index: plan_usage.use_resource("EXAMPLE", "whatsapp_messages", str(index)), range(20)))
    assert all(accepted)
    assert plan_usage.use_resource("EXAMPLE", "whatsapp_messages", "0")
    report = plan_usage.report("EXAMPLE")
    assert report["whatsapp_messages"] == {
        "used": 20, "limit": 2, "paused": False, "enforced": False, "measured_by": "ai_cost"}
    assert not any(alert["resource"] == "whatsapp_messages" for alert in report["alerts"])
    assert plan_usage.use_resource("BETA", "whatsapp_messages", "0")
    assert plan_usage.report("BETA")["whatsapp_messages"]["used"] == 1


def test_money_based_mode_ignores_previous_message_pause_and_keeps_website_capacity(plan_ledger):
    for identity in ("one", "two"):
        assert plan_usage.use_resource("EXAMPLE", "whatsapp_messages", identity)
    assert not plan_usage.use_resource("EXAMPLE", "whatsapp_messages", "three")
    plan_ledger["message_usage_model"] = "ai_cost"
    assert plan_usage.report("EXAMPLE")["whatsapp_messages"]["paused"] is False
    assert plan_usage.use_resource("EXAMPLE", "whatsapp_messages", "three")
    assert plan_usage.report("EXAMPLE")["whatsapp_messages"]["used"] == 3
    for identity in ("one", "two"):
        assert plan_usage.use_resource("EXAMPLE", "website_conversations", identity)
    assert not plan_usage.use_resource("EXAMPLE", "website_conversations", "three")
    assert plan_usage.report("EXAMPLE")["website_conversations"]["paused"] is True


def test_prepaid_plan_report_ignores_legacy_monthly_budget_and_redacts_costs(plan_ledger):
    held = plan_usage.reserve_ai("EXAMPLE", 1_000_000_000)
    plan_usage.settle_ai(held, None)
    plan_ledger.update(message_usage_model="ai_cost", ai_credit_model="prepaid", ai_budget_pence=0)
    usage_wallet.adjust("EXAMPLE", 100, "Test prepaid funding", "test-admin", "funding")
    result = plan_usage.report("EXAMPLE")
    assert result["ai_budget"] == {"limit_pence": 0, "paused": False, "active": False}
    assert result["usage_credit"]["available_pence"] == 100
    assert result["usage_credit"]["paused"] is False
    assert all(alert["resource"] != "ai_budget" for alert in result["alerts"])
    hidden = plan_usage.report("EXAMPLE", include_costs=False)["usage_credit"]
    assert "transactions" not in hidden and "available_pence" not in hidden


def test_quota_dedupe_is_scoped_to_month_tenant_and_resource(plan_ledger, monkeypatch):
    monkeypatch.setattr(plan_usage, "_month", lambda: "2026-10")
    for tenant in ("EXAMPLE", "BETA"):
        for resource in ("website_conversations", "whatsapp_messages"):
            assert plan_usage.use_resource(tenant, resource, "same-id")
    monkeypatch.setattr(plan_usage, "_month", lambda: "2026-11")
    assert plan_usage.report("EXAMPLE")["website_conversations"]["used"] == 0
    assert plan_usage.use_resource("EXAMPLE", "website_conversations", "same-id")


def test_atomic_ai_reservations_prevent_parallel_overspend(plan_ledger):
    def reserve(_index):
        try:
            return plan_usage.reserve_ai("EXAMPLE", 500_000_000)
        except plan_usage.AllowancePaused:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        reservations = [item for item in pool.map(reserve, range(12)) if item]
    assert len(reservations) == 2
    report = plan_usage.report("EXAMPLE")
    assert report["ai_budget"]["reserved_pence"] == 100
    assert report["ai_budget"]["paused"]
    for item in reservations:
        plan_usage.settle_ai(item, 100_000_000)
        plan_usage.settle_ai(item, 100_000_000)  # duplicate settlement does not add cost
    assert plan_usage.report("EXAMPLE")["ai_budget"]["used_pence"] == 20
    recovered = plan_usage.reserve_ai("EXAMPLE", 100_000_000)
    assert recovered
    assert not plan_usage.report("EXAMPLE")["ai_budget"]["paused"]


def test_unknown_paid_call_keeps_reservation_and_alerts_admin(plan_ledger):
    reservation = plan_usage.reserve_ai("EXAMPLE", 500_000_000)
    plan_usage.settle_ai(reservation, None)
    report = plan_usage.report("EXAMPLE")
    assert report["ai_budget"]["reserved_pence"] == 50
    assert report["ai_budget"]["unknown_calls"] == 1
    assert report["ai_budget"]["paused"]
    with pytest.raises(plan_usage.AllowancePaused):
        plan_usage.reserve_ai("EXAMPLE", 1)
    assert plan_usage.reserve_ai("BETA", 1)
    assert "used_pence" not in plan_usage.report("EXAMPLE", include_costs=False)["ai_budget"]


@pytest.mark.parametrize("reference", [None, {"rate": 1, "stale": True}, {"rate": float("nan")}, {"rate": -1}])
def test_unknown_conversion_blocks_provider_work_and_notifies(plan_ledger, monkeypatch, reference):
    monkeypatch.setattr(usage_currency, "gbp_rate", lambda: reference)
    with pytest.raises(plan_usage.AllowancePaused):
        plan_usage.reserve_ai("EXAMPLE", 100)
    assert plan_usage.report("EXAMPLE")["ai_budget"]["paused"]


def test_internal_and_legacy_tenants_keep_existing_behavior(plan_ledger, monkeypatch):
    monkeypatch.setattr(plan_usage, "_plan", lambda tenant: None)
    assert plan_usage.use_resource("VERTEX", "website_conversations", "signed-session")
    assert plan_usage.reserve_ai("VERTEX", None) is None
    assert plan_usage.report("VERTEX") is None


@pytest.mark.parametrize("channel", ["web", "whatsapp"])
def test_exhausted_ai_budget_never_calls_provider_and_brain_uses_saved_fallback(plan_ledger, monkeypatch, channel):
    from brain_v7 import BrainV7
    from service import model_settings
    monkeypatch.setattr(model_settings, "document", lambda *args: {})
    usage_wallet.adjust("EXAMPLE", 100, "Test prepaid funding", "test-admin", "funding")
    held = usage_wallet.reserve_usage("EXAMPLE", 1_000_000_000)
    provider = Mock()
    with api_usage.usage_context("EXAMPLE", channel):
        response = BrainV7(client=provider).plan("Do you deliver?", session={})
    assert isinstance(response, dict)
    assert response["action"]
    provider.chat.completions.create.assert_not_called()
    assert api_usage.summary("EXAMPLE", 30)["totals"]["calls"] == 0
    assert usage_wallet.report("EXAMPLE")["paused"]
    usage_wallet.settle_usage(held, 0)


def test_unknown_model_fails_closed_without_a_fake_api_usage_event(plan_ledger, monkeypatch):
    from service import model_settings
    monkeypatch.setattr(model_settings, "document", lambda *args: {})
    provider = Mock()
    with pytest.raises(plan_usage.AllowancePaused), api_usage.usage_context("EXAMPLE", "web"):
        api_usage.tracked_completion(provider, purpose="planning", model="unknown-model")
    provider.chat.completions.create.assert_not_called()
    assert api_usage.summary("EXAMPLE", 30)["totals"]["calls"] == 0
    assert usage_wallet.report("EXAMPLE")["paused"]
    assert usage_wallet.report("EXAMPLE")["alerts"][0]["code"] == "pricing_unavailable"


def test_text_ceiling_rejects_multimodal_or_unbounded_inputs():
    options = {"model": "gpt-4o-mini", "max_tokens": 1024, "messages": [{"role": "user", "content": "é" * 100}]}
    assert api_usage.completion_ceiling(options) > 1024 * 600 + 200 * 150
    assert api_usage.completion_ceiling({**options, "messages": [{"role": "user", "content": [{"type": "image_url"}]}]}) is None
    assert api_usage.completion_ceiling({**options, "max_tokens": None}) is None
    assert api_usage.completion_ceiling({**options, "service_tier": "priority"}) is None


def test_webchat_enforces_new_signed_conversations_before_handler(client, app, monkeypatch):
    from service import subscriptions
    monkeypatch.setattr(subscriptions, "configured_plan", lambda tenant: {"website_conversations": 1, "whatsapp_messages": 2, "ai_budget_pence": 100})
    handler = Mock(return_value={"reply": "Available answer", "intent": "faq"})
    app.container.for_tenant("EXAMPLE").handler.handle = handler
    first = client.post("/chat_api", json={"tenant": "EXAMPLE", "message": "hello"})
    assert first.status_code == 200
    token = first.get_json()["conversation_token"]
    assert client.post("/chat_api", json={"tenant": "EXAMPLE", "message": "again", "conversation_token": token}).status_code == 200
    denied = client.post("/chat_api", json={"tenant": "EXAMPLE", "message": "new visitor"})
    assert denied.status_code == 429
    assert denied.get_json()["error"] == "website_allowance_paused"
    assert handler.call_count == 2


def test_whatsapp_pause_skips_handler_and_provider_send(client, app, monkeypatch):
    from dataclasses import replace
    from service import subscriptions
    from tests.test_whatsapp_webhook import cloud_post, _cloud_payload
    monkeypatch.setattr(subscriptions, "configured_plan", lambda tenant: {"website_conversations": 1, "whatsapp_messages": 1, "ai_budget_pence": 100})
    monkeypatch.setattr(subscriptions, "whatsapp_enabled", lambda tenant: True)
    app.container.settings = replace(app.container.settings, WHATSAPP_APP_SECRET="configured-secret", WHATSAPP_TOKEN="test-token", WHATSAPP_PHONE_ID="phone-id")
    handler = Mock(return_value={"reply": "Available answer", "intent": "faq"})
    sender = Mock()
    app.container.for_tenant("EXAMPLE").handler.handle = handler
    monkeypatch.setattr("routes.whatsapp_routes.send_reply", sender)
    payload = _cloud_payload()
    assert cloud_post(client, payload).status_code == 200
    assert cloud_post(client, payload).status_code == 200
    payload["entry"][0]["changes"][0]["value"]["messages"][0]["id"] = "wamid.test-2"
    assert cloud_post(client, payload).status_code == 200
    assert handler.call_count == sender.call_count == 1
    assert plan_usage.report("EXAMPLE")["whatsapp_messages"]["used"] == 1


def test_money_based_whatsapp_keeps_saved_replies_after_old_message_cap_and_ai_pause(client, app, monkeypatch):
    from dataclasses import replace
    from service import subscriptions
    from tests.test_whatsapp_webhook import cloud_post, _cloud_payload
    monkeypatch.setattr(subscriptions, "configured_plan", lambda tenant: {
        "website_conversations": 1, "whatsapp_messages": 1,
        "ai_budget_pence": 100, "message_usage_model": "ai_cost"})
    monkeypatch.setattr(usage_currency, "gbp_rate", lambda: {"rate": 1, "stale": False})
    monkeypatch.setattr(subscriptions, "whatsapp_enabled", lambda tenant: True)
    app.container.settings = replace(app.container.settings, WHATSAPP_APP_SECRET="configured-secret",
        WHATSAPP_TOKEN="test-token", WHATSAPP_PHONE_ID="phone-id")
    held = plan_usage.reserve_ai("EXAMPLE", 1_000_000_000)
    handler = Mock(return_value={"reply": "Saved business answer", "intent": "faq"})
    sender = Mock()
    app.container.for_tenant("EXAMPLE").handler.handle = handler
    monkeypatch.setattr("routes.whatsapp_routes.send_reply", sender)
    payload = _cloud_payload()
    assert cloud_post(client, payload).status_code == 200
    assert cloud_post(client, payload).status_code == 200
    payload["entry"][0]["changes"][0]["value"]["messages"][0]["id"] = "wamid.test-2"
    assert cloud_post(client, payload).status_code == 200
    assert handler.call_count == sender.call_count == 2
    report = plan_usage.report("EXAMPLE")
    assert report["whatsapp_messages"]["used"] == 2
    assert report["whatsapp_messages"]["paused"] is False
    assert report["ai_budget"]["paused"] is True
    assert {alert["resource"] for alert in report["alerts"]} == {"ai_budget"}
    plan_usage.settle_ai(held, 0)


def _wav(seconds=1):
    output = BytesIO()
    with wave.open(output, "wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(8000)
        recording.writeframes(b"\0" * int(16000 * seconds))
    return output.getvalue()


def test_tiered_transcription_bounds_duration_and_settles_known_spend(plan_ledger, monkeypatch):
    usage_wallet.adjust("EXAMPLE", 100, "Test prepaid funding", "test-admin", "funding")
    provider = Mock()
    provider.audio.transcriptions.create.return_value = SimpleNamespace(text="Please help", usage=SimpleNamespace(type="duration", seconds=1))
    monkeypatch.setattr(speech_transcription, "OpenAI", Mock(return_value=provider))
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setenv("V7_TRANSCRIPTION_MODEL", "gpt-transcribe")
    assert speech_transcription.transcribe_audio(_wav(), "audio/wav", tenant="EXAMPLE", channel="web") == "Please help"
    assert provider.audio.transcriptions.create.call_count == 1
    assert usage_wallet.report("EXAMPLE")["reserved_pence"] == 0
    assert usage_wallet.report("EXAMPLE")["spent_pence"] == pytest.approx(.0075)


@pytest.mark.parametrize("audio,mime", [(_wav(61), "audio/wav"), (_wav()[:-10], "audio/wav")],
                         ids=["too-long", "truncated"])
def test_tiered_transcription_rejects_unverified_or_long_audio_before_provider(plan_ledger, monkeypatch, audio, mime):
    provider = Mock()
    monkeypatch.setattr(speech_transcription, "OpenAI", provider)
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setenv("V7_TRANSCRIPTION_MODEL", "gpt-transcribe")
    with pytest.raises(speech_transcription.SpeechTranscriptionError) as error:
        speech_transcription.transcribe_audio(audio, mime, tenant="EXAMPLE", channel="web")
    assert error.value.code == "audio_duration_unverified"
    provider.assert_not_called()


def test_native_usage_rls_and_concurrent_limits(pg_runtime, monkeypatch):
    monkeypatch.setattr(plan_usage, "_plan", lambda tenant: {"website_conversations": 2, "whatsapp_messages": 1, "ai_budget_pence": 100})
    tenant, other = pg_runtime["tenant"], pg_runtime["other"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda index: plan_usage.use_resource(tenant, "website_conversations", str(index)), range(6)))
    assert sum(results) == 2
    assert plan_usage.use_resource(other, "website_conversations", "0")
    with plan_usage._connection(tenant) as db:
        assert not db.execute("SELECT 1 FROM billing_plan_usage WHERE tenant=?", (other,)).fetchone()
    assert plan_usage.report(tenant)["website_conversations"]["used"] == 2
    assert plan_usage.report(other)["website_conversations"]["used"] == 1
