BEGIN;
-- Coordinate claim snapshots without granting the backend direct UPDATE
-- access to the global programme. The guarded administrator path owns writes.
CREATE OR REPLACE FUNCTION v7_private.set_referral_program(management_token_hash TEXT,new_enabled BOOLEAN)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog
AS $$
BEGIN
  IF management_token_hash IS NULL OR management_token_hash !~ '^[0-9a-f]{64}$' OR new_enabled IS NULL
     OR NOT EXISTS(SELECT 1 FROM v7_private.management_sessions management
       WHERE management.token_hash=management_token_hash AND management.expires>EXTRACT(EPOCH FROM clock_timestamp())
       AND (management.identity::jsonb->'roles') ?| ARRAY['platform_admin','admin']) THEN
    RAISE EXCEPTION 'Platform administrator session required' USING ERRCODE='42501';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('v7-referral-program',0));
  UPDATE v7_private.referral_program SET enabled=CASE WHEN new_enabled THEN 1 ELSE 0 END WHERE id=1;
END;
$$;
REVOKE ALL ON FUNCTION v7_private.set_referral_program(TEXT,BOOLEAN) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION v7_private.set_referral_program(TEXT,BOOLEAN) TO v7_backend;
COMMIT;
