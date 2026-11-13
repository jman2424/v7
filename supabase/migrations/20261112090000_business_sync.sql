-- Business Sync Engine: authorised data sources, the sync queue, item links and
-- change history. Private tables with forced tenant row-level security.
-- Credentials in sync_sources.secret are application-encrypted before storage.
BEGIN;
CREATE TABLE v7_private.sync_sources (
    id TEXT PRIMARY KEY,
    tenant TEXT NOT NULL REFERENCES v7_private.tenants(tenant) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('woocommerce','shopify','custom_feed','upload')),
    label TEXT NOT NULL, config TEXT NOT NULL, secret TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('connected','attention','reconnect','disconnected')),
    authorisation TEXT NOT NULL,
    auto_sync INTEGER NOT NULL DEFAULT 0, auto_apply INTEGER NOT NULL DEFAULT 0,
    interval_minutes INTEGER NOT NULL DEFAULT 60 CHECK (interval_minutes BETWEEN 15 AND 1440),
    last_success DOUBLE PRECISION NOT NULL DEFAULT 0, last_attempt DOUBLE PRECISION NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '', next_poll DOUBLE PRECISION NOT NULL DEFAULT 0,
    created DOUBLE PRECISION NOT NULL, updated DOUBLE PRECISION NOT NULL,
    version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX sync_sources_tenant ON v7_private.sync_sources(tenant,created);

CREATE TABLE v7_private.sync_jobs (
    id TEXT PRIMARY KEY,
    tenant TEXT NOT NULL REFERENCES v7_private.tenants(tenant) ON DELETE CASCADE,
    source_id TEXT NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('full','event')),
    event_key TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0, run_after DOUBLE PRECISION NOT NULL DEFAULT 0,
    lease TEXT NOT NULL DEFAULT '', lease_until DOUBLE PRECISION NOT NULL DEFAULT 0,
    error_code TEXT NOT NULL DEFAULT '',
    created DOUBLE PRECISION NOT NULL, updated DOUBLE PRECISION NOT NULL,
    UNIQUE(tenant,source_id,event_key)
);
CREATE INDEX sync_jobs_due ON v7_private.sync_jobs(tenant,state,run_after);

CREATE TABLE v7_private.sync_items (
    tenant TEXT NOT NULL REFERENCES v7_private.tenants(tenant) ON DELETE CASCADE,
    source_id TEXT NOT NULL, kind TEXT NOT NULL, external_id TEXT NOT NULL,
    local_ref TEXT NOT NULL, fields TEXT NOT NULL,
    source_updated DOUBLE PRECISION NOT NULL DEFAULT 0, removed INTEGER NOT NULL DEFAULT 0,
    updated DOUBLE PRECISION NOT NULL,
    PRIMARY KEY(tenant,source_id,kind,external_id)
);

CREATE TABLE v7_private.sync_changesets (
    id TEXT PRIMARY KEY,
    tenant TEXT NOT NULL REFERENCES v7_private.tenants(tenant) ON DELETE CASCADE,
    source_id TEXT NOT NULL, origin TEXT NOT NULL CHECK (origin IN ('import','sync')),
    state TEXT NOT NULL CHECK (state IN ('pending','applied','rejected','rolled_back','superseded')),
    summary TEXT NOT NULL, changes TEXT NOT NULL,
    before_docs TEXT NOT NULL DEFAULT '', after_revisions TEXT NOT NULL DEFAULT '',
    actor TEXT NOT NULL DEFAULT '',
    created DOUBLE PRECISION NOT NULL, updated DOUBLE PRECISION NOT NULL,
    version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX sync_changesets_tenant ON v7_private.sync_changesets(tenant,created);

DO $$
DECLARE name TEXT;
BEGIN
    FOREACH name IN ARRAY ARRAY['sync_sources','sync_jobs','sync_items','sync_changesets'] LOOP
        EXECUTE format('ALTER TABLE v7_private.%I ENABLE ROW LEVEL SECURITY', name);
        EXECUTE format('ALTER TABLE v7_private.%I FORCE ROW LEVEL SECURITY', name);
        EXECUTE format('CREATE POLICY backend_access ON v7_private.%I TO v7_backend '
                       'USING (tenant=current_setting(''v7.tenant'',true)) '
                       'WITH CHECK (tenant=current_setting(''v7.tenant'',true))', name);
        EXECUTE format('REVOKE ALL ON v7_private.%I FROM PUBLIC,anon,authenticated,service_role', name);
        EXECUTE format('GRANT SELECT,INSERT,UPDATE,DELETE ON v7_private.%I TO v7_backend', name);
    END LOOP;
END $$;

-- Worker discovery only: which businesses have ever connected a source.
-- Holds no business data; follows v7_private.ai_budget_work_tenants.
CREATE TABLE v7_private.sync_work_tenants (
    tenant TEXT PRIMARY KEY REFERENCES v7_private.tenants(tenant) ON DELETE CASCADE
);
ALTER TABLE v7_private.sync_work_tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE v7_private.sync_work_tenants FORCE ROW LEVEL SECURITY;
REVOKE ALL ON v7_private.sync_work_tenants FROM PUBLIC,anon,authenticated,service_role;
CREATE POLICY worker_ownership_read ON v7_private.sync_work_tenants
    FOR SELECT TO v7_backend USING (true);
CREATE POLICY tenant_enqueue ON v7_private.sync_work_tenants
    FOR INSERT TO v7_backend WITH CHECK (tenant=current_setting('v7.tenant',true));
GRANT SELECT,INSERT ON v7_private.sync_work_tenants TO v7_backend;
COMMIT;
