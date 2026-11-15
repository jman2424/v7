-- Seven-day grace after a failed subscription renewal. One row per business,
-- opened at the first failed renewal and removed when Stripe reports it paid.
BEGIN;
CREATE TABLE v7_private.billing_payment_recovery (
  tenant TEXT PRIMARY KEY REFERENCES v7_private.tenants(tenant),
  subscription TEXT NOT NULL CHECK (subscription ~ '^sub_[A-Za-z0-9]+$'),
  started BIGINT NOT NULL CHECK (started > 0),
  reminded INTEGER NOT NULL DEFAULT 0 CHECK (reminded BETWEEN 0 AND 3)
);
ALTER TABLE v7_private.billing_payment_recovery ENABLE ROW LEVEL SECURITY;
ALTER TABLE v7_private.billing_payment_recovery FORCE ROW LEVEL SECURITY;
CREATE POLICY backend_access ON v7_private.billing_payment_recovery TO v7_backend
    USING (tenant = current_setting('v7.tenant', true))
    WITH CHECK (tenant = current_setting('v7.tenant', true));
REVOKE ALL ON v7_private.billing_payment_recovery FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON v7_private.billing_payment_recovery TO v7_backend;
COMMIT;
