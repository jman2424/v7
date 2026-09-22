BEGIN;
CREATE TABLE IF NOT EXISTS v7_private.billing_discounts (
  tenant TEXT PRIMARY KEY,
  campaign TEXT NOT NULL
);
ALTER TABLE v7_private.billing_discounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE v7_private.billing_discounts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS backend_access ON v7_private.billing_discounts;
CREATE POLICY backend_access ON v7_private.billing_discounts TO v7_backend
  USING (tenant = current_setting('v7.tenant', true))
  WITH CHECK (tenant = current_setting('v7.tenant', true));
REVOKE ALL ON v7_private.billing_discounts FROM PUBLIC;
DO $roles$
DECLARE api_role TEXT;
BEGIN
  FOREACH api_role IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=api_role) THEN
      EXECUTE format('REVOKE ALL ON v7_private.billing_discounts FROM %I', api_role);
    END IF;
  END LOOP;
END
$roles$;
GRANT SELECT, INSERT, UPDATE, DELETE ON v7_private.billing_discounts TO v7_backend;
INSERT INTO v7_private.schema_version VALUES (2) ON CONFLICT DO NOTHING;
COMMIT;
