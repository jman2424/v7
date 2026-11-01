-- Additive AI Budget controls. Existing wallet balances and ledgers are unchanged.

BEGIN;

SET LOCAL search_path = v7_private, pg_catalog;

CREATE TABLE IF NOT EXISTS ai_budget_settings (
        tenant TEXT PRIMARY KEY, revision BIGINT NOT NULL DEFAULT 1,
        recharge_enabled INTEGER NOT NULL DEFAULT 0 CHECK(recharge_enabled IN(0,1)),
        recharge_cap_pence BIGINT NOT NULL DEFAULT 2500 CHECK(recharge_cap_pence IN(2500,5000,10000)),
        authorisation TEXT NOT NULL DEFAULT '', blocked_reason TEXT NOT NULL DEFAULT '',
        alerts_enabled INTEGER NOT NULL DEFAULT 1 CHECK(alerts_enabled IN(0,1)),
        email_alerts INTEGER NOT NULL DEFAULT 0 CHECK(email_alerts IN(0,1)),
        alert_threshold_pence BIGINT NOT NULL DEFAULT 200 CHECK(alert_threshold_pence IN(200,500,1000)),
        low_state INTEGER NOT NULL DEFAULT 0 CHECK(low_state IN(0,1)), alert_epoch BIGINT NOT NULL DEFAULT 0,
        observed_balance_nano BIGINT, initial_pack TEXT NOT NULL DEFAULT '', fees_check_after DOUBLE PRECISION NOT NULL DEFAULT 0,
        updated DOUBLE PRECISION NOT NULL);

CREATE TABLE IF NOT EXISTS ai_budget_authorisations (
        id TEXT PRIMARY KEY, tenant TEXT NOT NULL, revision BIGINT NOT NULL, request_id TEXT NOT NULL,
        actor TEXT NOT NULL, actor_revision TEXT NOT NULL, consent_terms TEXT NOT NULL, cap_pence BIGINT NOT NULL,
        customer TEXT NOT NULL DEFAULT '', checkout TEXT UNIQUE, checkout_url TEXT NOT NULL DEFAULT '',
        setup_intent TEXT UNIQUE, payment_method TEXT NOT NULL DEFAULT '',
        livemode INTEGER NOT NULL CHECK(livemode IN(0,1)),
        status TEXT NOT NULL CHECK(status IN('pending','active','revoked','failed')),
        created DOUBLE PRECISION NOT NULL, updated DOUBLE PRECISION NOT NULL,
        UNIQUE(tenant,revision), UNIQUE(tenant,id), UNIQUE(tenant,request_id));

CREATE TABLE IF NOT EXISTS ai_budget_recharges (
        reference TEXT PRIMARY KEY, tenant TEXT NOT NULL, authorisation TEXT NOT NULL,
        month TEXT NOT NULL, amount_pence BIGINT NOT NULL CHECK(amount_pence=500),
        credit_pence BIGINT NOT NULL CHECK(credit_pence=500),
        subtotal_pence BIGINT NOT NULL, tax_pence BIGINT NOT NULL, vat_percent INTEGER NOT NULL,
        customer TEXT NOT NULL, payment_method TEXT NOT NULL, livemode INTEGER NOT NULL CHECK(livemode IN(0,1)),
        payment_id TEXT UNIQUE, charge_id TEXT UNIQUE,
        status TEXT NOT NULL CHECK(status IN('reserved','dispatching','processing','succeeded','failed','requires_action','cancelled','unknown')),
        failure_code TEXT NOT NULL DEFAULT '', attempts INTEGER NOT NULL DEFAULT 0,
        lease_until DOUBLE PRECISION NOT NULL DEFAULT 0, created DOUBLE PRECISION NOT NULL,
        updated DOUBLE PRECISION NOT NULL, CHECK(subtotal_pence+tax_pence=amount_pence),
        FOREIGN KEY(tenant,authorisation) REFERENCES ai_budget_authorisations(tenant,id));

CREATE TABLE IF NOT EXISTS ai_budget_notifications (
        id TEXT PRIMARY KEY, tenant TEXT NOT NULL, kind TEXT NOT NULL, event_key TEXT NOT NULL,
        payload TEXT NOT NULL, email_enabled INTEGER NOT NULL CHECK(email_enabled IN(0,1)),
        state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN('pending','sending','sent','dashboard_only','needs_review')),
        seen INTEGER NOT NULL DEFAULT 0 CHECK(seen IN(0,1)), attempts INTEGER NOT NULL DEFAULT 0,
        available DOUBLE PRECISION NOT NULL, created DOUBLE PRECISION NOT NULL,
        UNIQUE(tenant,event_key));

CREATE TABLE IF NOT EXISTS ai_budget_events (
        id TEXT PRIMARY KEY, tenant TEXT NOT NULL, kind TEXT NOT NULL, actor TEXT NOT NULL,
        details TEXT NOT NULL, created DOUBLE PRECISION NOT NULL);

CREATE TABLE IF NOT EXISTS ai_budget_payment_costs (
        tenant TEXT NOT NULL, payment_id TEXT NOT NULL, balance_transaction TEXT NOT NULL,
        currency TEXT NOT NULL, gross_pence BIGINT NOT NULL, fee_pence BIGINT NOT NULL,
        net_pence BIGINT NOT NULL, fee_details TEXT NOT NULL, observed DOUBLE PRECISION NOT NULL,
        PRIMARY KEY(tenant,payment_id), CHECK(gross_pence-fee_pence=net_pence));

CREATE TABLE IF NOT EXISTS ai_provider_funding_settings (
        id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL, updated DOUBLE PRECISION NOT NULL);

CREATE TABLE IF NOT EXISTS ai_provider_health (
        id INTEGER PRIMARY KEY CHECK(id=1), status TEXT NOT NULL, error_code TEXT NOT NULL DEFAULT '',
        observed DOUBLE PRECISION NOT NULL, retry_after DOUBLE PRECISION NOT NULL DEFAULT 0);

CREATE TABLE IF NOT EXISTS ai_provider_cost_snapshots (
        id TEXT PRIMARY KEY, start_utc BIGINT NOT NULL, end_utc BIGINT NOT NULL,
        source TEXT NOT NULL, currency TEXT NOT NULL, amount_decimal TEXT NOT NULL,
        project_id TEXT NOT NULL DEFAULT '', observed DOUBLE PRECISION NOT NULL,
        UNIQUE(start_utc,end_utc,source,currency,project_id));

CREATE INDEX IF NOT EXISTS ai_budget_auth_tenant ON ai_budget_authorisations(tenant,status,created);

CREATE INDEX IF NOT EXISTS ai_budget_recharge_month ON ai_budget_recharges(tenant,month,status);

CREATE UNIQUE INDEX IF NOT EXISTS ai_budget_one_open_recharge ON ai_budget_recharges(tenant) WHERE status IN('reserved','dispatching','processing','requires_action','unknown');

CREATE INDEX IF NOT EXISTS ai_budget_recharge_work ON ai_budget_recharges(tenant,status,lease_until);

CREATE INDEX IF NOT EXISTS ai_budget_notice_queue ON ai_budget_notifications(tenant,state,available);

CREATE INDEX IF NOT EXISTS ai_budget_events_tenant ON ai_budget_events(tenant,created);

ALTER TABLE ai_budget_settings ADD CONSTRAINT ai_budget_settings_tenant_fk FOREIGN KEY(tenant) REFERENCES v7_private.tenants(tenant);

ALTER TABLE ai_budget_settings ENABLE ROW LEVEL SECURITY;

ALTER TABLE ai_budget_settings FORCE ROW LEVEL SECURITY;

CREATE POLICY backend_tenant ON ai_budget_settings TO v7_backend USING (tenant=current_setting('v7.tenant',true)) WITH CHECK (tenant=current_setting('v7.tenant',true));

REVOKE ALL ON ai_budget_settings FROM PUBLIC,anon,authenticated,service_role;

GRANT SELECT,INSERT,UPDATE ON ai_budget_settings TO v7_backend;

ALTER TABLE ai_budget_authorisations ADD CONSTRAINT ai_budget_authorisations_tenant_fk FOREIGN KEY(tenant) REFERENCES v7_private.tenants(tenant);

ALTER TABLE ai_budget_authorisations ENABLE ROW LEVEL SECURITY;

ALTER TABLE ai_budget_authorisations FORCE ROW LEVEL SECURITY;

CREATE POLICY backend_tenant ON ai_budget_authorisations TO v7_backend USING (tenant=current_setting('v7.tenant',true)) WITH CHECK (tenant=current_setting('v7.tenant',true));

REVOKE ALL ON ai_budget_authorisations FROM PUBLIC,anon,authenticated,service_role;

GRANT SELECT,INSERT,UPDATE ON ai_budget_authorisations TO v7_backend;

ALTER TABLE ai_budget_recharges ADD CONSTRAINT ai_budget_recharges_tenant_fk FOREIGN KEY(tenant) REFERENCES v7_private.tenants(tenant);

ALTER TABLE ai_budget_recharges ENABLE ROW LEVEL SECURITY;

ALTER TABLE ai_budget_recharges FORCE ROW LEVEL SECURITY;

CREATE POLICY backend_tenant ON ai_budget_recharges TO v7_backend USING (tenant=current_setting('v7.tenant',true)) WITH CHECK (tenant=current_setting('v7.tenant',true));

REVOKE ALL ON ai_budget_recharges FROM PUBLIC,anon,authenticated,service_role;

GRANT SELECT,INSERT,UPDATE ON ai_budget_recharges TO v7_backend;

ALTER TABLE ai_budget_notifications ADD CONSTRAINT ai_budget_notifications_tenant_fk FOREIGN KEY(tenant) REFERENCES v7_private.tenants(tenant);

ALTER TABLE ai_budget_notifications ENABLE ROW LEVEL SECURITY;

ALTER TABLE ai_budget_notifications FORCE ROW LEVEL SECURITY;

CREATE POLICY backend_tenant ON ai_budget_notifications TO v7_backend USING (tenant=current_setting('v7.tenant',true)) WITH CHECK (tenant=current_setting('v7.tenant',true));

REVOKE ALL ON ai_budget_notifications FROM PUBLIC,anon,authenticated,service_role;

GRANT SELECT,INSERT,UPDATE ON ai_budget_notifications TO v7_backend;

ALTER TABLE ai_budget_events ADD CONSTRAINT ai_budget_events_tenant_fk FOREIGN KEY(tenant) REFERENCES v7_private.tenants(tenant);

ALTER TABLE ai_budget_events ENABLE ROW LEVEL SECURITY;

ALTER TABLE ai_budget_events FORCE ROW LEVEL SECURITY;

CREATE POLICY backend_tenant ON ai_budget_events TO v7_backend USING (tenant=current_setting('v7.tenant',true)) WITH CHECK (tenant=current_setting('v7.tenant',true));

REVOKE ALL ON ai_budget_events FROM PUBLIC,anon,authenticated,service_role;

GRANT SELECT,INSERT ON ai_budget_events TO v7_backend;

ALTER TABLE ai_budget_payment_costs ADD CONSTRAINT ai_budget_payment_costs_tenant_fk FOREIGN KEY(tenant) REFERENCES v7_private.tenants(tenant);

ALTER TABLE ai_budget_payment_costs ENABLE ROW LEVEL SECURITY;

ALTER TABLE ai_budget_payment_costs FORCE ROW LEVEL SECURITY;

CREATE POLICY backend_tenant ON ai_budget_payment_costs TO v7_backend USING (tenant=current_setting('v7.tenant',true)) WITH CHECK (tenant=current_setting('v7.tenant',true));

REVOKE ALL ON ai_budget_payment_costs FROM PUBLIC,anon,authenticated,service_role;

GRANT SELECT,INSERT,UPDATE ON ai_budget_payment_costs TO v7_backend;

ALTER TABLE ai_provider_funding_settings ENABLE ROW LEVEL SECURITY;

ALTER TABLE ai_provider_funding_settings FORCE ROW LEVEL SECURITY;

REVOKE ALL ON ai_provider_funding_settings FROM PUBLIC,anon,authenticated,service_role;

CREATE POLICY backend_read ON ai_provider_funding_settings FOR SELECT TO v7_backend USING (true);

CREATE POLICY operator_insert ON ai_provider_funding_settings FOR INSERT TO v7_backend WITH CHECK (v7_private.business_application_operator());

CREATE POLICY operator_update ON ai_provider_funding_settings FOR UPDATE TO v7_backend USING (v7_private.business_application_operator()) WITH CHECK (v7_private.business_application_operator());

GRANT SELECT,INSERT,UPDATE ON ai_provider_funding_settings TO v7_backend;

ALTER TABLE ai_provider_health ENABLE ROW LEVEL SECURITY;

ALTER TABLE ai_provider_health FORCE ROW LEVEL SECURITY;

REVOKE ALL ON ai_provider_health FROM PUBLIC,anon,authenticated,service_role;

CREATE POLICY backend_control ON ai_provider_health TO v7_backend USING (true) WITH CHECK (true);

GRANT SELECT,INSERT,UPDATE ON ai_provider_health TO v7_backend;

ALTER TABLE ai_provider_cost_snapshots ENABLE ROW LEVEL SECURITY;

ALTER TABLE ai_provider_cost_snapshots FORCE ROW LEVEL SECURITY;

REVOKE ALL ON ai_provider_cost_snapshots FROM PUBLIC,anon,authenticated,service_role;

CREATE POLICY backend_control ON ai_provider_cost_snapshots TO v7_backend USING (true) WITH CHECK (true);

GRANT SELECT,INSERT,UPDATE ON ai_provider_cost_snapshots TO v7_backend;

COMMENT ON TABLE ai_budget_authorisations IS 'Explicit customer consent and canonical Stripe setup references; no raw card details.';

COMMENT ON TABLE ai_budget_recharges IS 'Fixed GBP 5 attempts; pending/uncertain attempts retain calendar-month cap capacity.';

CREATE TABLE IF NOT EXISTS ai_provider_limit_snapshots (
    scope TEXT PRIMARY KEY, value TEXT NOT NULL, observed DOUBLE PRECISION NOT NULL);
ALTER TABLE ai_provider_limit_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_provider_limit_snapshots FORCE ROW LEVEL SECURITY;
REVOKE ALL ON ai_provider_limit_snapshots FROM PUBLIC,anon,authenticated,service_role;
CREATE POLICY backend_control ON ai_provider_limit_snapshots TO v7_backend USING (true) WITH CHECK (true);
GRANT SELECT,INSERT,UPDATE ON ai_provider_limit_snapshots TO v7_backend;

COMMIT;
