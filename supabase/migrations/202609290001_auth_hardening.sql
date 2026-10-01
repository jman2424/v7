-- Shared account attempt reservations and single-use authenticator timesteps.
BEGIN;
CREATE TABLE IF NOT EXISTS v7_private.auth_login_failures (
  attempt TEXT PRIMARY KEY,
  subject_hash TEXT NOT NULL CHECK (subject_hash ~ '^[a-f0-9]{64}$'),
  attempted DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS auth_login_failures_subject_time
  ON v7_private.auth_login_failures (subject_hash, attempted);
CREATE TABLE IF NOT EXISTS v7_private.mfa_code_uses (
  account TEXT NOT NULL,
  secret_hash TEXT NOT NULL CHECK (secret_hash ~ '^[a-f0-9]{64}$'),
  timestep BIGINT NOT NULL CHECK (timestep >= 0),
  PRIMARY KEY (account, secret_hash, timestep)
);
CREATE INDEX IF NOT EXISTS mfa_code_uses_timestep ON v7_private.mfa_code_uses (timestep);

ALTER TABLE v7_private.auth_login_failures ENABLE ROW LEVEL SECURITY;
ALTER TABLE v7_private.auth_login_failures FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS backend_access ON v7_private.auth_login_failures;
CREATE POLICY backend_access ON v7_private.auth_login_failures TO v7_backend
  USING (true) WITH CHECK (true);
ALTER TABLE v7_private.mfa_code_uses ENABLE ROW LEVEL SECURITY;
ALTER TABLE v7_private.mfa_code_uses FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS backend_access ON v7_private.mfa_code_uses;
CREATE POLICY backend_access ON v7_private.mfa_code_uses TO v7_backend
  USING (true) WITH CHECK (true);
REVOKE ALL ON v7_private.auth_login_failures, v7_private.mfa_code_uses FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON v7_private.auth_login_failures, v7_private.mfa_code_uses TO v7_backend;
DO $api_roles$
DECLARE api_role TEXT;
BEGIN
  FOREACH api_role IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=api_role) THEN
      EXECUTE format('REVOKE ALL ON v7_private.auth_login_failures, v7_private.mfa_code_uses FROM %I', api_role);
    END IF;
  END LOOP;
END
$api_roles$;
INSERT INTO v7_private.schema_version VALUES (6) ON CONFLICT DO NOTHING;
COMMIT;
