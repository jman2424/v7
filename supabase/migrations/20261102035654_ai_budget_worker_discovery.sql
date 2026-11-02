-- Private worker ownership metadata, following the existing telemetry queue.
-- No financial rows or administrator inventory permissions are changed.
BEGIN;
CREATE TABLE v7_private.ai_budget_work_tenants (
    tenant TEXT PRIMARY KEY REFERENCES v7_private.tenants(tenant)
);
ALTER TABLE v7_private.ai_budget_work_tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE v7_private.ai_budget_work_tenants FORCE ROW LEVEL SECURITY;
REVOKE ALL ON v7_private.ai_budget_work_tenants FROM PUBLIC,anon,authenticated,service_role;
CREATE POLICY worker_ownership_read ON v7_private.ai_budget_work_tenants
    FOR SELECT TO v7_backend USING (true);
CREATE POLICY tenant_enqueue ON v7_private.ai_budget_work_tenants
    FOR INSERT TO v7_backend WITH CHECK (tenant=current_setting('v7.tenant',true));
GRANT SELECT,INSERT ON v7_private.ai_budget_work_tenants TO v7_backend;
INSERT INTO v7_private.ai_budget_work_tenants(tenant)
    SELECT tenant FROM v7_private.usage_wallets
    UNION SELECT tenant FROM v7_private.ai_budget_settings;
COMMIT;
