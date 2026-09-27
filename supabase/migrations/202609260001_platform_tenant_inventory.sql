-- A bounded inventory for an authenticated platform operator. Tenant table RLS
-- remains unchanged; owners continue reading only their authorized workspaces.
BEGIN;
CREATE FUNCTION v7_private.list_platform_tenant_keys(
  management_token_hash TEXT, page_size INTEGER DEFAULT 500, page_offset INTEGER DEFAULT 0
) RETURNS TABLE(tenant TEXT)
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog
AS $inventory$
BEGIN
  IF management_token_hash IS NULL OR management_token_hash !~ '^[0-9a-f]{64}$'
     OR page_size IS NULL OR page_size < 1 OR page_size > 500
     OR page_offset IS NULL OR page_offset < 0 THEN
    RAISE EXCEPTION 'Invalid platform inventory request' USING ERRCODE = '22023';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM v7_private.management_sessions AS management
    WHERE management.token_hash = management_token_hash
      AND management.expires > EXTRACT(EPOCH FROM clock_timestamp())
      AND jsonb_typeof(management.identity::jsonb -> 'roles') = 'array'
      AND (management.identity::jsonb -> 'roles') ?| ARRAY['platform_admin', 'admin']
  ) THEN
    RAISE EXCEPTION 'Platform administrator session required' USING ERRCODE = '42501';
  END IF;
  RETURN QUERY
    SELECT businesses.tenant FROM v7_private.tenants AS businesses
    ORDER BY lower(businesses.tenant), businesses.tenant
    LIMIT page_size OFFSET page_offset;
END;
$inventory$;
REVOKE ALL ON FUNCTION v7_private.list_platform_tenant_keys(TEXT, INTEGER, INTEGER) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION v7_private.list_platform_tenant_keys(TEXT, INTEGER, INTEGER) TO v7_backend;
INSERT INTO v7_private.schema_version VALUES (4) ON CONFLICT DO NOTHING;
COMMIT;
