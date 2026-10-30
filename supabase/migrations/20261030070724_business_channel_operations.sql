BEGIN;
CREATE TABLE v7_private.business_operations (
    id TEXT PRIMARY KEY,
    tenant TEXT NOT NULL REFERENCES v7_private.tenants(tenant) ON DELETE CASCADE,
    channel TEXT NOT NULL CHECK (channel IN ('email','phone','workflow')),
    event_key TEXT NOT NULL, conversation_id TEXT NOT NULL, source_address TEXT NOT NULL,
    payload TEXT NOT NULL, state TEXT NOT NULL, reply TEXT NOT NULL DEFAULT '',
    provider_id TEXT NOT NULL DEFAULT '', error_code TEXT NOT NULL DEFAULT '',
    lease TEXT NOT NULL DEFAULT '', lease_until DOUBLE PRECISION NOT NULL DEFAULT 0,
    created DOUBLE PRECISION NOT NULL, updated DOUBLE PRECISION NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    UNIQUE(tenant,channel,event_key)
);
CREATE INDEX business_operation_due ON v7_private.business_operations(tenant,state,created);
CREATE INDEX business_operation_conversation ON v7_private.business_operations(tenant,conversation_id,created);
ALTER TABLE v7_private.business_operations ENABLE ROW LEVEL SECURITY;
ALTER TABLE v7_private.business_operations FORCE ROW LEVEL SECURITY;
CREATE POLICY backend_access ON v7_private.business_operations TO v7_backend
    USING (tenant=current_setting('v7.tenant',true))
    WITH CHECK (tenant=current_setting('v7.tenant',true));
REVOKE ALL ON v7_private.business_operations FROM PUBLIC,anon,authenticated,service_role;
GRANT SELECT,INSERT,UPDATE,DELETE ON v7_private.business_operations TO v7_backend;
COMMIT;
