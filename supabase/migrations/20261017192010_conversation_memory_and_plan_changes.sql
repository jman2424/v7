BEGIN;
CREATE TABLE IF NOT EXISTS v7_private.conversation_memory (
    tenant TEXT NOT NULL REFERENCES v7_private.tenants(tenant),
    session_hash TEXT NOT NULL CHECK (length(session_hash)=64),
    generation TEXT NOT NULL,
    payload TEXT NOT NULL CHECK (octet_length(payload)<=131072),
    expires DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (tenant,session_hash,generation)
);
CREATE INDEX IF NOT EXISTS conversation_memory_expiry ON v7_private.conversation_memory(tenant,expires);
CREATE TABLE IF NOT EXISTS v7_private.billing_plan_changes (
    ref TEXT PRIMARY KEY,
    tenant TEXT NOT NULL REFERENCES v7_private.tenants(tenant),
    billing_ref TEXT NOT NULL REFERENCES v7_private.billing_references(ref),
    subscription TEXT NOT NULL,
    from_plan TEXT NOT NULL CHECK (from_plan IN ('starter','business','scale')),
    plan_id TEXT NOT NULL CHECK (plan_id IN ('starter','business','scale')),
    price_id TEXT NOT NULL,
    setup_plan TEXT NOT NULL CHECK (setup_plan IN ('starter','business','scale')),
    status TEXT NOT NULL CHECK (status IN ('pending','applied')),
    created BIGINT NOT NULL, expires BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS billing_plan_changes_lookup ON v7_private.billing_plan_changes(tenant,subscription,billing_ref,price_id,status);
ALTER TABLE v7_private.conversation_memory ENABLE ROW LEVEL SECURITY;
ALTER TABLE v7_private.conversation_memory FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS backend_access ON v7_private.conversation_memory;
CREATE POLICY backend_access ON v7_private.conversation_memory TO v7_backend
    USING (tenant=current_setting('v7.tenant',true)) WITH CHECK (tenant=current_setting('v7.tenant',true));
ALTER TABLE v7_private.billing_plan_changes ENABLE ROW LEVEL SECURITY;
ALTER TABLE v7_private.billing_plan_changes FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS backend_access ON v7_private.billing_plan_changes;
CREATE POLICY backend_access ON v7_private.billing_plan_changes TO v7_backend
    USING (tenant=current_setting('v7.tenant',true)) WITH CHECK (tenant=current_setting('v7.tenant',true));
REVOKE ALL ON v7_private.conversation_memory,v7_private.billing_plan_changes FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE,DELETE ON v7_private.conversation_memory,v7_private.billing_plan_changes TO v7_backend;
DO $api_roles$
DECLARE api_role TEXT;
BEGIN
    FOREACH api_role IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=api_role) THEN
            EXECUTE format('REVOKE ALL ON v7_private.conversation_memory,v7_private.billing_plan_changes FROM %I',api_role);
        END IF;
    END LOOP;
END
$api_roles$;
COMMIT;
