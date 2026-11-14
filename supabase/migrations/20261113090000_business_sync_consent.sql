-- Business Sync: a business's own website as a source, and a permanent record of
-- every permission a business gives or withdraws. The application can add a
-- permission record and mark it ended; it cannot delete one.
BEGIN;
ALTER TABLE v7_private.sync_sources DROP CONSTRAINT sync_sources_kind_check;
ALTER TABLE v7_private.sync_sources ADD CONSTRAINT sync_sources_kind_check
    CHECK (kind IN ('woocommerce','shopify','custom_feed','upload','website'));

CREATE TABLE v7_private.sync_consents (
    id TEXT PRIMARY KEY,
    tenant TEXT NOT NULL REFERENCES v7_private.tenants(tenant) ON DELETE CASCADE,
    source_id TEXT NOT NULL, kind TEXT NOT NULL,
    domain TEXT NOT NULL DEFAULT '', statement TEXT NOT NULL, terms_version TEXT NOT NULL,
    account TEXT NOT NULL, role TEXT NOT NULL DEFAULT '', details TEXT NOT NULL,
    granted DOUBLE PRECISION NOT NULL, ended DOUBLE PRECISION NOT NULL DEFAULT 0,
    end_reason TEXT NOT NULL DEFAULT '' CHECK (end_reason IN ('','withdrawn','renewed')),
    ended_by TEXT NOT NULL DEFAULT ''
);
CREATE INDEX sync_consents_tenant ON v7_private.sync_consents(tenant,granted);
ALTER TABLE v7_private.sync_consents ENABLE ROW LEVEL SECURITY;
ALTER TABLE v7_private.sync_consents FORCE ROW LEVEL SECURITY;
CREATE POLICY backend_access ON v7_private.sync_consents TO v7_backend
    USING (tenant=current_setting('v7.tenant',true))
    WITH CHECK (tenant=current_setting('v7.tenant',true));
REVOKE ALL ON v7_private.sync_consents FROM PUBLIC,anon,authenticated,service_role;
GRANT SELECT,INSERT,UPDATE ON v7_private.sync_consents TO v7_backend;
COMMIT;
