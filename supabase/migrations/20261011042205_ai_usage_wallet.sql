BEGIN;
CREATE TABLE v7_private.usage_wallets (
  tenant TEXT PRIMARY KEY REFERENCES v7_private.tenants(tenant),
  balance_nano_gbp BIGINT NOT NULL DEFAULT 0 CHECK(balance_nano_gbp>=0),
  reserved_nano_gbp BIGINT NOT NULL DEFAULT 0 CHECK(reserved_nano_gbp>=0),
  debt_nano_gbp BIGINT NOT NULL DEFAULT 0 CHECK(debt_nano_gbp>=0),
  reconciliation_hold INTEGER NOT NULL DEFAULT 0 CHECK(reconciliation_hold IN(0,1)),
  pause_reason TEXT NOT NULL DEFAULT '', updated_utc TEXT NOT NULL,
  CHECK(reserved_nano_gbp<=balance_nano_gbp)
);
CREATE TABLE v7_private.usage_wallet_payments (
  tenant TEXT NOT NULL REFERENCES v7_private.usage_wallets(tenant),
  reference TEXT PRIMARY KEY, payment_id TEXT UNIQUE NOT NULL,
  credit_nano_gbp BIGINT NOT NULL CHECK(credit_nano_gbp>0),
  paid_pence BIGINT NOT NULL CHECK(paid_pence>0),
  refunded_pence BIGINT NOT NULL DEFAULT 0 CHECK(refunded_pence>=0),
  reversed_nano_gbp BIGINT NOT NULL DEFAULT 0 CHECK(reversed_nano_gbp>=0),
  disputed INTEGER NOT NULL DEFAULT 0 CHECK(disputed IN(0,1)),
  dispute_open INTEGER NOT NULL DEFAULT 0 CHECK(dispute_open IN(0,1)),
  dispute_states_json TEXT NOT NULL DEFAULT '{}',
  invoice_id TEXT NOT NULL DEFAULT '', receipt_url TEXT NOT NULL DEFAULT '', created_utc TEXT NOT NULL,
  CHECK(reversed_nano_gbp<=credit_nano_gbp), CHECK(refunded_pence<=paid_pence)
);
CREATE INDEX usage_wallet_payments_tenant ON v7_private.usage_wallet_payments(tenant,created_utc);
CREATE TABLE v7_private.usage_wallet_reservations (
  tenant TEXT NOT NULL REFERENCES v7_private.usage_wallets(tenant), ref TEXT PRIMARY KEY,
  amount_nano_gbp BIGINT NOT NULL CHECK(amount_nano_gbp>=0),
  maximum_nano_usd BIGINT NOT NULL CHECK(maximum_nano_usd>=0),
  fx_rate TEXT NOT NULL, fx_date TEXT NOT NULL, markup_percent TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN('pending','unknown','overrun','settled')),
  cost_nano_usd BIGINT, charged_nano_gbp BIGINT, metadata_json TEXT NOT NULL, created_utc TEXT NOT NULL
);
CREATE INDEX usage_wallet_reservations_tenant ON v7_private.usage_wallet_reservations(tenant,status);
CREATE TABLE v7_private.usage_wallet_entries (
  id TEXT PRIMARY KEY, tenant TEXT NOT NULL REFERENCES v7_private.usage_wallets(tenant),
  kind TEXT NOT NULL, created_utc TEXT NOT NULL, amount_nano_gbp BIGINT NOT NULL,
  balance_delta_nano_gbp BIGINT NOT NULL, debt_delta_nano_gbp BIGINT NOT NULL,
  reserved_delta_nano_gbp BIGINT NOT NULL,
  payment_ref TEXT NOT NULL DEFAULT '', reservation_ref TEXT NOT NULL DEFAULT '',
  invoice_id TEXT NOT NULL DEFAULT '', receipt_url TEXT NOT NULL DEFAULT '',
  reason TEXT NOT NULL DEFAULT '', actor TEXT NOT NULL DEFAULT '',
  idempotency_key TEXT NOT NULL, metadata_json TEXT NOT NULL, UNIQUE(tenant,idempotency_key)
);
CREATE INDEX usage_wallet_entries_tenant ON v7_private.usage_wallet_entries(tenant,created_utc,id);
CREATE TABLE v7_private.usage_checkout_requests (
  tenant TEXT NOT NULL REFERENCES v7_private.tenants(tenant), reference TEXT PRIMARY KEY,
  request_id TEXT NOT NULL, pack_id TEXT NOT NULL,
  credit_pence BIGINT NOT NULL CHECK(credit_pence>0),
  subtotal_pence BIGINT NOT NULL CHECK(subtotal_pence>0), tax_pence BIGINT NOT NULL CHECK(tax_pence>=0),
  total_pence BIGINT NOT NULL CHECK(total_pence=subtotal_pence+tax_pence),
  vat_percent INTEGER NOT NULL CHECK(vat_percent BETWEEN 0 AND 100), tax_rate TEXT NOT NULL,
  livemode INTEGER NOT NULL CHECK(livemode IN(0,1)), checkout TEXT UNIQUE,
  payment_id TEXT UNIQUE, invoice_id TEXT UNIQUE, checkout_url TEXT, expires_at BIGINT,
  status TEXT NOT NULL DEFAULT 'preparing', created BIGINT NOT NULL, UNIQUE(tenant,request_id)
);
CREATE INDEX usage_checkout_requests_tenant ON v7_private.usage_checkout_requests(tenant,created);
DO $secure_tables$
DECLARE table_name TEXT; api_role TEXT;
BEGIN
  FOREACH table_name IN ARRAY ARRAY['usage_wallets','usage_wallet_payments','usage_wallet_reservations','usage_wallet_entries','usage_checkout_requests'] LOOP
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
REVOKE UPDATE,DELETE ON v7_private.usage_wallet_entries FROM v7_backend;
INSERT INTO v7_private.schema_version VALUES (11) ON CONFLICT DO NOTHING;
COMMIT;
