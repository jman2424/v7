-- Explicit provider subjects can sign in only to existing linked V7 accounts.
BEGIN;
CREATE TABLE IF NOT EXISTS v7_private.oidc_states (
  state_hash TEXT PRIMARY KEY CHECK (state_hash ~ '^[a-f0-9]{64}$'),
  provider TEXT NOT NULL CHECK (provider IN ('google','microsoft')),
  configuration_hash TEXT NOT NULL CHECK (configuration_hash ~ '^[a-f0-9]{64}$'),
  browser_hash TEXT NOT NULL CHECK (browser_hash ~ '^[a-f0-9]{64}$'),
  intent TEXT NOT NULL CHECK (intent IN ('login','link')),
  verifier TEXT NOT NULL,
  nonce TEXT NOT NULL,
  tenant TEXT NOT NULL CHECK (tenant ~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$'),
  identity TEXT,
  revision TEXT,
  session_hash TEXT,
  created DOUBLE PRECISION NOT NULL,
  expires DOUBLE PRECISION NOT NULL,
  CHECK ((intent='login' AND identity IS NULL AND revision IS NULL AND session_hash IS NULL)
    OR (intent='link' AND identity IS NOT NULL AND revision ~ '^[a-f0-9]{64}$'
      AND session_hash ~ '^[a-f0-9]{64}$'))
);
CREATE INDEX IF NOT EXISTS oidc_states_expires ON v7_private.oidc_states (expires);
CREATE TABLE IF NOT EXISTS v7_private.oidc_links (
  provider TEXT NOT NULL CHECK (provider IN ('google','microsoft')),
  client_id TEXT NOT NULL,
  issuer TEXT NOT NULL,
  subject TEXT NOT NULL,
  account TEXT NOT NULL,
  identity TEXT NOT NULL,
  created DOUBLE PRECISION NOT NULL,
  PRIMARY KEY(provider,client_id,issuer,subject),
  UNIQUE(provider,client_id,account)
);
CREATE INDEX IF NOT EXISTS oidc_links_account ON v7_private.oidc_links (account);
ALTER TABLE v7_private.oidc_states ENABLE ROW LEVEL SECURITY;
ALTER TABLE v7_private.oidc_states FORCE ROW LEVEL SECURITY;
ALTER TABLE v7_private.oidc_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE v7_private.oidc_links FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS backend_access ON v7_private.oidc_states;
DROP POLICY IF EXISTS backend_access ON v7_private.oidc_links;
CREATE POLICY backend_access ON v7_private.oidc_states TO v7_backend USING (true) WITH CHECK (true);
CREATE POLICY backend_access ON v7_private.oidc_links TO v7_backend USING (true) WITH CHECK (true);
REVOKE ALL ON v7_private.oidc_states, v7_private.oidc_links FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON v7_private.oidc_states, v7_private.oidc_links TO v7_backend;
DO $api_roles$
DECLARE api_role TEXT;
BEGIN
  FOREACH api_role IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=api_role) THEN
      EXECUTE format('REVOKE ALL ON v7_private.oidc_states, v7_private.oidc_links FROM %I', api_role);
    END IF;
  END LOOP;
END
$api_roles$;
INSERT INTO v7_private.schema_version VALUES (8) ON CONFLICT DO NOTHING;
COMMIT;
