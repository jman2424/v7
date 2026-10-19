-- Minimal pre-auth routing for tenant-local credentials. Password/MFA validation
-- stays in the application; this exposes no account fields or business documents.
BEGIN;
CREATE FUNCTION v7_private.email_login_tenants(requested_email TEXT)
RETURNS TABLE(tenant TEXT)
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog
AS $lookup$
BEGIN
  IF requested_email IS NULL OR length(requested_email) NOT BETWEEN 1 AND 254
     OR requested_email <> lower(btrim(requested_email)) THEN
    RETURN;
  END IF;
  RETURN QUERY
    SELECT documents.tenant
    FROM v7_private.business_documents AS documents
    CROSS JOIN LATERAL jsonb_array_elements(
      CASE WHEN jsonb_typeof(documents.payload) = 'array' THEN documents.payload ELSE '[]'::jsonb END
    ) AS account
    WHERE documents.filename = 'owner_accounts.json'
      AND lower(btrim(account->>'email')) = requested_email
    ORDER BY documents.tenant
    LIMIT 2;
END;
$lookup$;
REVOKE ALL ON FUNCTION v7_private.email_login_tenants(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION v7_private.email_login_tenants(TEXT) TO v7_backend;
COMMIT;
