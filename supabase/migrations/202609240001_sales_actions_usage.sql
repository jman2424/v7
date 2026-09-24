BEGIN;

ALTER TABLE v7_private.api_usage
  ADD COLUMN IF NOT EXISTS mode TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE v7_private.api_usage
  ADD COLUMN IF NOT EXISTS cache_write_tokens BIGINT;

CREATE TABLE IF NOT EXISTS v7_private.sales_action_requests (
  reference TEXT PRIMARY KEY,
  tenant TEXT NOT NULL,
  action TEXT NOT NULL,
  slot_id TEXT,
  slot_start_at TEXT,
  slot_label TEXT,
  name TEXT NOT NULL,
  contact TEXT NOT NULL,
  details TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  idempotency_key TEXT,
  request_hash TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS sales_action_slot_once
  ON v7_private.sales_action_requests (tenant, slot_id)
  WHERE action = 'consultation' AND slot_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS sales_action_idempotency
  ON v7_private.sales_action_requests (tenant, idempotency_key)
  WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS sales_action_owner_list
  ON v7_private.sales_action_requests (tenant, created_at DESC);
ALTER TABLE v7_private.sales_action_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE v7_private.sales_action_requests FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS backend_access ON v7_private.sales_action_requests;
CREATE POLICY backend_access ON v7_private.sales_action_requests TO v7_backend
  USING (tenant = current_setting('v7.tenant', true))
  WITH CHECK (tenant = current_setting('v7.tenant', true));
REVOKE ALL ON v7_private.sales_action_requests FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON v7_private.sales_action_requests TO v7_backend;

CREATE TABLE IF NOT EXISTS v7_private.sales_action_attempts (
  ip_digest TEXT NOT NULL,
  attempted DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS sales_action_attempts_ip
  ON v7_private.sales_action_attempts (ip_digest, attempted);
ALTER TABLE v7_private.sales_action_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE v7_private.sales_action_attempts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS backend_access ON v7_private.sales_action_attempts;
CREATE POLICY backend_access ON v7_private.sales_action_attempts TO v7_backend
  USING (true) WITH CHECK (true);
REVOKE ALL ON v7_private.sales_action_attempts FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON v7_private.sales_action_attempts TO v7_backend;

DO $api_roles$
DECLARE api_role TEXT;
BEGIN
  FOREACH api_role IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=api_role) THEN
      EXECUTE format('REVOKE ALL ON v7_private.sales_action_requests, v7_private.sales_action_attempts FROM %I', api_role);
    END IF;
  END LOOP;
END
$api_roles$;

INSERT INTO v7_private.schema_version VALUES (3) ON CONFLICT DO NOTHING;
COMMIT;
