-- Platform-assigned phone numbers, email addresses and WhatsApp senders live in
-- each business's own channel_routes.json document. Inbound provider webhooks run
-- before any business is known, so they need one narrow cross-business read:
-- this function returns only those routing documents, never other business data.
BEGIN;
CREATE FUNCTION v7_private.channel_route_documents()
RETURNS TABLE(tenant TEXT, payload JSONB)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog
AS $routes$
  SELECT documents.tenant, documents.payload
  FROM v7_private.business_documents AS documents
  WHERE documents.filename = 'channel_routes.json'
  ORDER BY documents.tenant
  LIMIT 5000;
$routes$;
REVOKE ALL ON FUNCTION v7_private.channel_route_documents() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION v7_private.channel_route_documents() TO v7_backend;
COMMIT;
