BEGIN;

-- Existing accepted offers keep their agreed setup percentage and rewards.
ALTER TABLE v7_private.referral_claims ADD COLUMN joining_setup_percent INTEGER NOT NULL DEFAULT 40 CHECK(joining_setup_percent BETWEEN 1 AND 100);
UPDATE v7_private.referral_claims SET joining_setup_percent=percent;

-- Only newly accepted referrals receive the updated joining-business offer.
ALTER TABLE v7_private.referral_program ADD COLUMN joining_setup_percent INTEGER NOT NULL DEFAULT 100 CHECK(joining_setup_percent BETWEEN 1 AND 100);

-- Existing forced RLS policies and restricted grants continue to cover both
-- additive columns. No customer rewards or billing records are rewritten.
COMMIT;
