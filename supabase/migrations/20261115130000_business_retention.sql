-- Thirty days of kept data after a subscription ends. One row per ended
-- business; a new active subscription removes it. Past 30 days the business
-- appears in the platform review queue. Nothing here deletes business data.
-- Platform-level, like managed_businesses: written only by verified Stripe
-- syncs and by platform administrators.
BEGIN;
CREATE TABLE v7_private.business_retention (
  tenant TEXT PRIMARY KEY REFERENCES v7_private.tenants(tenant),
  ended BIGINT NOT NULL CHECK (ended > 0),
  decision TEXT NOT NULL DEFAULT 'pending' CHECK (decision IN ('pending','keep')),
  decided BIGINT CHECK (decided IS NULL OR decided > 0),
  actor TEXT CHECK (actor IS NULL OR length(actor) BETWEEN 1 AND 200)
);
ALTER TABLE v7_private.business_retention ENABLE ROW LEVEL SECURITY;
ALTER TABLE v7_private.business_retention FORCE ROW LEVEL SECURITY;
CREATE POLICY backend_access ON v7_private.business_retention TO v7_backend USING (true) WITH CHECK (true);
REVOKE ALL ON v7_private.business_retention FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON v7_private.business_retention TO v7_backend;
COMMIT;
