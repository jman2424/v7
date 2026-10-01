-- Opt-in 30-day device proofs remain revocable and require the account password.
BEGIN;
CREATE TABLE IF NOT EXISTS v7_private.trusted_devices (
  token_hash TEXT PRIMARY KEY CHECK (token_hash ~ '^[a-f0-9]{64}$'),
  account TEXT NOT NULL,
  revision TEXT NOT NULL CHECK (revision ~ '^[a-f0-9]{64}$'),
  expires DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS trusted_devices_account ON v7_private.trusted_devices (account);
CREATE INDEX IF NOT EXISTS trusted_devices_expires ON v7_private.trusted_devices (expires);
ALTER TABLE v7_private.trusted_devices ENABLE ROW LEVEL SECURITY;
ALTER TABLE v7_private.trusted_devices FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS backend_access ON v7_private.trusted_devices;
CREATE POLICY backend_access ON v7_private.trusted_devices TO v7_backend
  USING (true) WITH CHECK (true);
REVOKE ALL ON v7_private.trusted_devices FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON v7_private.trusted_devices TO v7_backend;
DO $api_roles$
DECLARE api_role TEXT;
BEGIN
  FOREACH api_role IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=api_role) THEN
      EXECUTE format('REVOKE ALL ON v7_private.trusted_devices FROM %I', api_role);
    END IF;
  END LOOP;
END
$api_roles$;
INSERT INTO v7_private.schema_version VALUES (7) ON CONFLICT DO NOTHING;
COMMIT;
