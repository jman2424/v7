-- Yearly billing. Binds a subscription checkout or plan change to the interval it
-- was created with, so a provider callback can never pick a different price.
-- A reference without a row is monthly, which keeps every existing subscription.
BEGIN;
CREATE TABLE v7_private.billing_interval_choices (
  ref TEXT PRIMARY KEY CHECK (length(ref) BETWEEN 16 AND 128),
  tenant TEXT NOT NULL REFERENCES v7_private.tenants(tenant),
  billing_interval TEXT NOT NULL CHECK (billing_interval IN ('month','year'))
);
CREATE INDEX billing_interval_choices_tenant ON v7_private.billing_interval_choices(tenant);
ALTER TABLE v7_private.billing_interval_choices ENABLE ROW LEVEL SECURITY;
ALTER TABLE v7_private.billing_interval_choices FORCE ROW LEVEL SECURITY;
CREATE POLICY backend_access ON v7_private.billing_interval_choices TO v7_backend
    USING (tenant = current_setting('v7.tenant', true))
    WITH CHECK (tenant = current_setting('v7.tenant', true));
REVOKE ALL ON v7_private.billing_interval_choices FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON v7_private.billing_interval_choices TO v7_backend;
COMMIT;
