-- Live service controls: a business pausing its own AI, and the platform kill
-- switch (whole platform, one channel everywhere, one business, or one channel of
-- one business). One row per active pause; resuming deletes the row. Like
-- managed_businesses this is platform-level: writes are scoped in application code
-- (an owner can only name their own business; platform scopes need a platform
-- administrator).
BEGIN;
CREATE TABLE v7_private.service_controls (
  scope TEXT PRIMARY KEY CHECK (scope ~ '^(platform|business)(:tenant:[A-Za-z0-9][A-Za-z0-9_-]{0,63})?(:channel:(web|whatsapp|email|phone))?$'),
  reason TEXT NOT NULL CHECK (length(reason) <= 500),
  actor TEXT NOT NULL CHECK (length(actor) BETWEEN 1 AND 200),
  updated BIGINT NOT NULL CHECK (updated > 0)
);
ALTER TABLE v7_private.service_controls ENABLE ROW LEVEL SECURITY;
ALTER TABLE v7_private.service_controls FORCE ROW LEVEL SECURITY;
CREATE POLICY backend_access ON v7_private.service_controls TO v7_backend USING (true) WITH CHECK (true);
REVOKE ALL ON v7_private.service_controls FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON v7_private.service_controls TO v7_backend;
COMMIT;
