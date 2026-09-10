from __future__ import annotations

from service import analytics_db


def test_sales_funnel_is_tenant_scoped_and_separates_pipeline_from_handoffs(tmp_path, monkeypatch):
    monkeypatch.setattr(analytics_db, "DB_PATH", str(tmp_path / "analytics.db"))
    monkeypatch.setattr(analytics_db, "_INIT_DONE", False)

    analytics_db.upsert_lead(tenant="EXAMPLE", lead_id="lead-open", name="Alex")
    analytics_db.upsert_lead(tenant="EXAMPLE", lead_id="lead-won", name="Jordan")
    analytics_db.upsert_lead(tenant="OTHER", lead_id="other-lead", name="Casey")
    assert analytics_db.update_lead_status(tenant="EXAMPLE", lead_id="lead-won", status="Won")

    analytics_db.log_message(
        tenant="EXAMPLE",
        channel="web",
        direction="outbound",
        session_id="session-handoff",
        intent="human_handoff",
        lead_id="lead-open",
    )
    analytics_db.log_message(
        tenant="EXAMPLE",
        channel="web",
        direction="outbound",
        session_id="session-handoff",
        intent="handoff_contact_captured",
        lead_id="lead-open",
    )

    funnel = analytics_db.get_sales_funnel(tenant="EXAMPLE", minutes=60)

    assert funnel == {
        "total": 2,
        "active": 1,
        "open": 1,
        "contacted": 0,
        "qualified": 0,
        "won": 1,
        "lost": 0,
        "other": 0,
        "handoffs": 1,
        "contacts_captured": 1,
    }
