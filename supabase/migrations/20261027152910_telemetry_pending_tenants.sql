-- Ownership index only. Event payloads remain under the existing tenant RLS.
CREATE INDEX idx_events_pending_telemetry ON v7_private.events(tenant,id)
  WHERE event_type='pipeline_pending';
CREATE TABLE v7_private.telemetry_pending_tenants (
  tenant TEXT PRIMARY KEY REFERENCES v7_private.tenants(tenant) ON DELETE CASCADE
);
ALTER TABLE v7_private.telemetry_pending_tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE v7_private.telemetry_pending_tenants FORCE ROW LEVEL SECURITY;
REVOKE ALL ON v7_private.telemetry_pending_tenants FROM PUBLIC, anon, authenticated, service_role;
-- The trusted worker may enumerate ownership keys, never cross-tenant events.
CREATE POLICY worker_ownership_read ON v7_private.telemetry_pending_tenants FOR SELECT TO v7_backend USING (true);
CREATE POLICY tenant_enqueue ON v7_private.telemetry_pending_tenants FOR INSERT TO v7_backend
  WITH CHECK (tenant = current_setting('v7.tenant', true));
CREATE POLICY tenant_dequeue ON v7_private.telemetry_pending_tenants FOR DELETE TO v7_backend
  USING (tenant = current_setting('v7.tenant', true));
GRANT SELECT, INSERT, DELETE ON v7_private.telemetry_pending_tenants TO v7_backend;
INSERT INTO v7_private.telemetry_pending_tenants(tenant)
  SELECT DISTINCT tenant FROM v7_private.events WHERE event_type='pipeline_pending'
  ON CONFLICT DO NOTHING;
