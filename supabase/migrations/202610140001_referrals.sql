BEGIN;
CREATE TABLE v7_private.referral_program (
  id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL CHECK(enabled IN(0,1)),
  percent INTEGER NOT NULL CHECK(percent BETWEEN 1 AND 100)
);
INSERT INTO v7_private.referral_program VALUES(1,1,40);
ALTER TABLE v7_private.referral_program ENABLE ROW LEVEL SECURITY;
ALTER TABLE v7_private.referral_program FORCE ROW LEVEL SECURITY;
CREATE POLICY backend_read ON v7_private.referral_program FOR SELECT TO v7_backend USING(true);
GRANT SELECT ON v7_private.referral_program TO v7_backend;

CREATE TABLE v7_private.referral_codes (
  tenant TEXT PRIMARY KEY REFERENCES v7_private.tenants(tenant),
  code TEXT UNIQUE NOT NULL CHECK(code ~ '^V7-[A-F0-9]{32}$'),
  owner_hash TEXT NOT NULL CHECK(owner_hash ~ '^[0-9a-f]{64}$')
);
CREATE TABLE v7_private.referral_claims (
  tenant TEXT PRIMARY KEY REFERENCES v7_private.tenants(tenant), sponsor TEXT NOT NULL REFERENCES v7_private.tenants(tenant),
  owner_hash TEXT UNIQUE NOT NULL CHECK(owner_hash ~ '^[0-9a-f]{64}$'),
  percent INTEGER NOT NULL CHECK(percent BETWEEN 1 AND 100), created BIGINT NOT NULL,
  qualifying_invoice TEXT UNIQUE, status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN('pending','qualified','review')),
  CHECK(tenant<>sponsor)
);
CREATE TABLE v7_private.referral_rewards (
  tenant TEXT NOT NULL REFERENCES v7_private.tenants(tenant), id TEXT NOT NULL,
  source_tenant TEXT NOT NULL REFERENCES v7_private.tenants(tenant), kind TEXT NOT NULL CHECK(kind IN('platform','implementation')),
  percent INTEGER NOT NULL CHECK(percent BETWEEN 1 AND 100), created BIGINT NOT NULL,
  status TEXT NOT NULL DEFAULT 'available' CHECK(status IN('available','reserved','applied','used','review')),
  billing_ref TEXT, coupon TEXT, invoice TEXT, PRIMARY KEY(tenant,id), UNIQUE(tenant,source_tenant,kind)
);
CREATE INDEX referral_reward_status ON v7_private.referral_rewards(tenant,kind,status,created);
CREATE UNIQUE INDEX referral_one_pending ON v7_private.referral_rewards(tenant,kind) WHERE status IN('reserved','applied');
DO $tables$
DECLARE name TEXT; api_role TEXT;
BEGIN
  FOREACH name IN ARRAY ARRAY['referral_program','referral_codes','referral_claims','referral_rewards'] LOOP
    EXECUTE format('REVOKE ALL ON v7_private.%I FROM PUBLIC',name);
    FOREACH api_role IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
      IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=api_role) THEN
        EXECUTE format('REVOKE ALL ON v7_private.%I FROM %I',name,api_role);
      END IF;
    END LOOP;
    IF name<>'referral_program' THEN
      EXECUTE format('ALTER TABLE v7_private.%I ENABLE ROW LEVEL SECURITY',name);
      EXECUTE format('ALTER TABLE v7_private.%I FORCE ROW LEVEL SECURITY',name);
      EXECUTE format('CREATE POLICY backend_access ON v7_private.%I TO v7_backend USING(tenant=current_setting(''v7.tenant'',true)) WITH CHECK(tenant=current_setting(''v7.tenant'',true))',name);
      EXECUTE format('GRANT SELECT,INSERT,UPDATE ON v7_private.%I TO v7_backend',name);
    END IF;
  END LOOP;
END
$tables$;

CREATE FUNCTION v7_private.lookup_referral_code(requested_code TEXT)
RETURNS TABLE(tenant TEXT,owner_hash TEXT)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog
AS $$ SELECT code.tenant,code.owner_hash FROM v7_private.referral_codes code WHERE code.code=requested_code $$;
REVOKE ALL ON FUNCTION v7_private.lookup_referral_code(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION v7_private.lookup_referral_code(TEXT) TO v7_backend;

CREATE FUNCTION v7_private.set_referral_program(management_token_hash TEXT,new_enabled BOOLEAN)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog
AS $$
BEGIN
  IF management_token_hash IS NULL OR management_token_hash !~ '^[0-9a-f]{64}$' OR new_enabled IS NULL
     OR NOT EXISTS(SELECT 1 FROM v7_private.management_sessions management
       WHERE management.token_hash=management_token_hash AND management.expires>EXTRACT(EPOCH FROM clock_timestamp())
       AND (management.identity::jsonb->'roles') ?| ARRAY['platform_admin','admin']) THEN
    RAISE EXCEPTION 'Platform administrator session required' USING ERRCODE='42501';
  END IF;
  UPDATE v7_private.referral_program SET enabled=CASE WHEN new_enabled THEN 1 ELSE 0 END WHERE id=1;
END;
$$;
REVOKE ALL ON FUNCTION v7_private.set_referral_program(TEXT,BOOLEAN) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION v7_private.set_referral_program(TEXT,BOOLEAN) TO v7_backend;
COMMIT;
