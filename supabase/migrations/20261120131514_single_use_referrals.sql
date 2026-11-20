BEGIN;
-- Lock the current code until the claim and both rewards commit. A waiter
-- rechecks the predicate against the replacement code after the lock releases.
CREATE OR REPLACE FUNCTION v7_private.lookup_referral_code(requested_code text)
RETURNS TABLE(tenant text, owner_hash text)
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = pg_catalog AS $$
  SELECT c.tenant, c.owner_hash FROM v7_private.referral_codes c
  WHERE c.code = requested_code FOR UPDATE
$$;

CREATE FUNCTION v7_private.replace_claimed_referral() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
  UPDATE v7_private.referral_codes
  SET code = 'V7-' || upper(replace(gen_random_uuid()::text, '-', ''))
  WHERE tenant = NEW.sponsor;
  RETURN NEW;
END
$$;
REVOKE ALL ON FUNCTION v7_private.replace_claimed_referral() FROM PUBLIC;
CREATE TRIGGER replace_claimed_referral AFTER INSERT ON v7_private.referral_claims
FOR EACH ROW EXECUTE FUNCTION v7_private.replace_claimed_referral();

UPDATE v7_private.referral_codes c
SET code = 'V7-' || upper(replace(gen_random_uuid()::text, '-', ''))
WHERE EXISTS (SELECT FROM v7_private.referral_claims r WHERE r.sponsor = c.tenant);

-- Only a boolean is needed after the signup mailbox has been verified.
CREATE FUNCTION v7_private.signup_owner_exists(mailbox text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
  SELECT EXISTS (
    SELECT FROM v7_private.business_documents d
    CROSS JOIN LATERAL jsonb_array_elements(
      CASE WHEN jsonb_typeof(d.payload) = 'array' THEN d.payload ELSE '[]'::jsonb END
    ) a
    WHERE d.filename = 'owner_accounts.json' AND a->'roles' ? 'business_owner'
      AND CASE WHEN lower(btrim(a->>'email')) ~ '@(gmail|googlemail)\.com$'
        THEN replace(split_part(split_part(lower(btrim(a->>'email')), '@', 1), '+', 1), '.', '') || '@gmail.com'
        ELSE lower(btrim(a->>'email')) END = mailbox
  )
$$;
REVOKE ALL ON FUNCTION v7_private.signup_owner_exists(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION v7_private.signup_owner_exists(text) TO v7_backend;
COMMIT;
