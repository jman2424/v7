-- Additive only: no customer, subscription, price or wallet rewrites.
BEGIN;
ALTER TABLE v7_private.registration_requests ADD COLUMN application TEXT NOT NULL DEFAULT '{}';

CREATE FUNCTION v7_private.business_application_operator() RETURNS BOOLEAN
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = pg_catalog AS $operator$
  SELECT EXISTS (
    SELECT 1 FROM v7_private.management_sessions AS s
    WHERE s.token_hash = current_setting('v7.application_session', true)
      AND s.expires > EXTRACT(EPOCH FROM statement_timestamp())
      AND jsonb_typeof(s.identity::jsonb -> 'roles') = 'array'
      AND (s.identity::jsonb -> 'roles') ?| ARRAY['platform_admin','admin']
  )
$operator$;
REVOKE ALL ON FUNCTION v7_private.business_application_operator() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION v7_private.business_application_operator() TO v7_backend;

CREATE TABLE v7_private.business_applications (
    tenant TEXT PRIMARY KEY REFERENCES v7_private.tenants(tenant) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK(status IN ('PENDING_REVIEW','NEEDS_INFORMATION','APPROVED','REJECTED','EXPIRED','CANCELLED')),
    revision INTEGER NOT NULL CHECK(revision > 0), details TEXT NOT NULL,
    contact_email TEXT NOT NULL, policy_version TEXT NOT NULL,
    created DOUBLE PRECISION NOT NULL, updated DOUBLE PRECISION NOT NULL,
    public_message TEXT NOT NULL DEFAULT '', service_preserved INTEGER NOT NULL DEFAULT 0 CHECK(service_preserved IN(0,1)),
    research TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX business_application_queue ON v7_private.business_applications(status,created);
CREATE TABLE v7_private.business_application_events (
    id TEXT PRIMARY KEY, tenant TEXT NOT NULL, revision INTEGER NOT NULL,
    kind TEXT NOT NULL, actor TEXT NOT NULL, note TEXT NOT NULL, created DOUBLE PRECISION NOT NULL
);
CREATE INDEX business_application_history ON v7_private.business_application_events(tenant,created);
CREATE TABLE v7_private.business_application_settings (
    id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL
);
CREATE TABLE v7_private.business_application_permits (
    reference TEXT PRIMARY KEY, tenant TEXT NOT NULL REFERENCES v7_private.tenants(tenant) ON DELETE CASCADE,
    revision INTEGER NOT NULL, kind TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('reserved','issued','settled','expired')),
    checkout TEXT, created DOUBLE PRECISION NOT NULL
);
CREATE INDEX business_application_open_payments ON v7_private.business_application_permits(tenant,state);
CREATE TABLE v7_private.business_application_notifications (
    id TEXT PRIMARY KEY, tenant TEXT NOT NULL, payload TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
    available DOUBLE PRECISION NOT NULL, created DOUBLE PRECISION NOT NULL
);
CREATE INDEX business_application_mail_queue ON v7_private.business_application_notifications(state,available);
CREATE INDEX business_application_mail_created ON v7_private.business_application_notifications(created);

ALTER TABLE v7_private.business_applications ENABLE ROW LEVEL SECURITY;
ALTER TABLE v7_private.business_applications FORCE ROW LEVEL SECURITY;
CREATE POLICY backend_access ON v7_private.business_applications TO v7_backend
    USING (tenant=current_setting('v7.tenant',true) OR v7_private.business_application_operator())
    WITH CHECK (tenant=current_setting('v7.tenant',true) OR v7_private.business_application_operator());
ALTER TABLE v7_private.business_application_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE v7_private.business_application_events FORCE ROW LEVEL SECURITY;
CREATE POLICY backend_access ON v7_private.business_application_events TO v7_backend
    USING (tenant=current_setting('v7.tenant',true) OR v7_private.business_application_operator())
    WITH CHECK (tenant=current_setting('v7.tenant',true) OR v7_private.business_application_operator());
ALTER TABLE v7_private.business_application_permits ENABLE ROW LEVEL SECURITY;
ALTER TABLE v7_private.business_application_permits FORCE ROW LEVEL SECURITY;
CREATE POLICY backend_access ON v7_private.business_application_permits TO v7_backend
    USING (tenant=current_setting('v7.tenant',true) OR v7_private.business_application_operator())
    WITH CHECK (tenant=current_setting('v7.tenant',true) OR v7_private.business_application_operator());
ALTER TABLE v7_private.business_application_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE v7_private.business_application_settings FORCE ROW LEVEL SECURITY;
CREATE POLICY backend_read ON v7_private.business_application_settings FOR SELECT TO v7_backend USING (true);
CREATE POLICY backend_insert ON v7_private.business_application_settings FOR INSERT TO v7_backend
    WITH CHECK (v7_private.business_application_operator());
CREATE POLICY backend_update ON v7_private.business_application_settings FOR UPDATE TO v7_backend
    USING (v7_private.business_application_operator()) WITH CHECK (v7_private.business_application_operator());
-- Like the existing registration/security queue, only the restricted server
-- login can claim this control-plane outbox. It is never exposed by Data API.
ALTER TABLE v7_private.business_application_notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE v7_private.business_application_notifications FORCE ROW LEVEL SECURITY;
CREATE POLICY backend_access ON v7_private.business_application_notifications TO v7_backend USING (true) WITH CHECK (true);
REVOKE ALL ON v7_private.business_applications, v7_private.business_application_events,
    v7_private.business_application_permits, v7_private.business_application_settings,
    v7_private.business_application_notifications FROM PUBLIC,anon,authenticated,service_role;
GRANT SELECT,INSERT,UPDATE,DELETE ON v7_private.business_applications,
    v7_private.business_application_permits,v7_private.business_application_notifications TO v7_backend;
GRANT SELECT,INSERT ON v7_private.business_application_events TO v7_backend;
GRANT UPDATE(note) ON v7_private.business_application_events TO v7_backend;
GRANT SELECT,INSERT,UPDATE ON v7_private.business_application_settings TO v7_backend;
COMMIT;
