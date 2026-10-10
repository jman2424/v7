BEGIN;
CREATE TABLE v7_private.billing_plan_state (
  tenant TEXT PRIMARY KEY REFERENCES v7_private.tenants(tenant),
  selected_plan TEXT NOT NULL CHECK (selected_plan IN ('starter','business','scale')),
  active_plan TEXT CHECK (active_plan IN ('starter','business','scale')),
  setup_plan TEXT CHECK (setup_plan IN ('starter','business','scale')),
  whatsapp_paused INTEGER NOT NULL DEFAULT 0 CHECK (whatsapp_paused IN (0,1))
);
CREATE TABLE v7_private.billing_plan_choices (
  ref TEXT PRIMARY KEY REFERENCES v7_private.billing_references(ref),
  tenant TEXT NOT NULL REFERENCES v7_private.tenants(tenant),
  kind TEXT NOT NULL CHECK (kind IN ('platform','implementation')),
  plan_id TEXT NOT NULL CHECK (plan_id IN ('starter','business','scale'))
);
CREATE INDEX billing_plan_choices_tenant ON v7_private.billing_plan_choices(tenant);
CREATE TABLE v7_private.billing_plan_usage (
  tenant TEXT NOT NULL REFERENCES v7_private.tenants(tenant),
  month TEXT NOT NULL CHECK (month ~ '^20[0-9]{2}-(0[1-9]|1[0-2])$'),
  website_conversations INTEGER NOT NULL DEFAULT 0 CHECK (website_conversations >= 0),
  whatsapp_messages INTEGER NOT NULL DEFAULT 0 CHECK (whatsapp_messages >= 0),
  ai_used_nano_gbp BIGINT NOT NULL DEFAULT 0 CHECK (ai_used_nano_gbp >= 0),
  ai_reserved_nano_gbp BIGINT NOT NULL DEFAULT 0 CHECK (ai_reserved_nano_gbp >= 0),
  ai_unknown INTEGER NOT NULL DEFAULT 0 CHECK (ai_unknown >= 0),
  website_paused INTEGER NOT NULL DEFAULT 0 CHECK (website_paused IN (0,1)),
  whatsapp_paused INTEGER NOT NULL DEFAULT 0 CHECK (whatsapp_paused IN (0,1)),
  ai_paused INTEGER NOT NULL DEFAULT 0 CHECK (ai_paused IN (0,1)),
  PRIMARY KEY(tenant,month)
);
CREATE TABLE v7_private.billing_plan_events (
  tenant TEXT NOT NULL,
  month TEXT NOT NULL,
  resource TEXT NOT NULL CHECK (resource IN ('website_conversations','whatsapp_messages')),
  event_hash TEXT NOT NULL CHECK (event_hash ~ '^[0-9a-f]{64}$'),
  PRIMARY KEY(tenant,month,resource,event_hash),
  FOREIGN KEY(tenant,month) REFERENCES v7_private.billing_plan_usage(tenant,month)
);
CREATE TABLE v7_private.billing_plan_reservations (
  tenant TEXT NOT NULL,
  month TEXT NOT NULL,
  ref TEXT NOT NULL,
  amount_nano_gbp BIGINT NOT NULL CHECK (amount_nano_gbp >= 0),
  PRIMARY KEY(tenant,month,ref),
  FOREIGN KEY(tenant,month) REFERENCES v7_private.billing_plan_usage(tenant,month)
);
DO $secure_tables$
DECLARE table_name TEXT; api_role TEXT;
BEGIN
  FOREACH table_name IN ARRAY ARRAY['billing_plan_state','billing_plan_choices','billing_plan_usage','billing_plan_events','billing_plan_reservations'] LOOP
    EXECUTE format('ALTER TABLE v7_private.%I ENABLE ROW LEVEL SECURITY',table_name);
    EXECUTE format('ALTER TABLE v7_private.%I FORCE ROW LEVEL SECURITY',table_name);
    EXECUTE format('CREATE POLICY backend_access ON v7_private.%I TO v7_backend USING (tenant=current_setting(''v7.tenant'',true)) WITH CHECK (tenant=current_setting(''v7.tenant'',true))',table_name);
    EXECUTE format('REVOKE ALL ON v7_private.%I FROM PUBLIC',table_name);
    FOREACH api_role IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=api_role) THEN
        EXECUTE format('REVOKE ALL ON v7_private.%I FROM %I',table_name,api_role);
      END IF;
    END LOOP;
    EXECUTE format('GRANT SELECT,INSERT,UPDATE,DELETE ON v7_private.%I TO v7_backend',table_name);
  END LOOP;
END
$secure_tables$;
INSERT INTO v7_private.schema_version VALUES (10) ON CONFLICT DO NOTHING;
COMMIT;
