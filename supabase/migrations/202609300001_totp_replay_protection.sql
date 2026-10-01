-- Single-use authenticator steps are private server security state.
BEGIN;
CREATE TABLE IF NOT EXISTS v7_private.totp_steps (
  account_hash TEXT PRIMARY KEY,
  step BIGINT NOT NULL CHECK (step >= 0)
);
ALTER TABLE v7_private.totp_steps ENABLE ROW LEVEL SECURITY;
ALTER TABLE v7_private.totp_steps FORCE ROW LEVEL SECURITY;
CREATE POLICY backend_access ON v7_private.totp_steps TO v7_backend
  USING (true) WITH CHECK (true);
GRANT SELECT, INSERT, UPDATE, DELETE ON v7_private.totp_steps TO v7_backend;
REVOKE ALL ON v7_private.totp_steps FROM PUBLIC;
DO $api_roles$
DECLARE api_role TEXT;
BEGIN
  FOREACH api_role IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=api_role) THEN
      EXECUTE format('REVOKE ALL ON v7_private.totp_steps FROM %I', api_role);
    END IF;
  END LOOP;
END
$api_roles$;
INSERT INTO v7_private.schema_version VALUES (9) ON CONFLICT DO NOTHING;
COMMIT;
