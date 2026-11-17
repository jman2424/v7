-- Each business's daily limit on messages one customer can send by website chat
-- or WhatsApp, and the daily counts used to enforce it. No row for a channel
-- means the default (40); a NULL limit means unlimited. Counts store only keyed
-- digests of a conversation, connection or phone number, never the raw value,
-- and are deleted after two days. Writes are scoped in application code.
BEGIN;
CREATE TABLE v7_private.customer_message_limits (
  tenant TEXT NOT NULL CHECK (tenant ~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$'),
  channel TEXT NOT NULL CHECK (channel IN ('web', 'whatsapp')),
  message_limit INTEGER CHECK (message_limit IS NULL OR message_limit BETWEEN 5 AND 200),
  actor TEXT NOT NULL CHECK (length(actor) BETWEEN 1 AND 200),
  updated BIGINT NOT NULL CHECK (updated > 0),
  PRIMARY KEY (tenant, channel)
);
CREATE TABLE v7_private.customer_message_counts (
  tenant TEXT NOT NULL CHECK (tenant ~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$'),
  channel TEXT NOT NULL CHECK (channel IN ('web', 'whatsapp')),
  subject TEXT NOT NULL CHECK (subject ~ '^(session|ip|whatsapp):[0-9a-f]{64}$'),
  day TEXT NOT NULL CHECK (day ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'),
  count INTEGER NOT NULL CHECK (count >= 0),
  PRIMARY KEY (tenant, channel, subject, day)
);
ALTER TABLE v7_private.customer_message_limits ENABLE ROW LEVEL SECURITY;
ALTER TABLE v7_private.customer_message_limits FORCE ROW LEVEL SECURITY;
ALTER TABLE v7_private.customer_message_counts ENABLE ROW LEVEL SECURITY;
ALTER TABLE v7_private.customer_message_counts FORCE ROW LEVEL SECURITY;
CREATE POLICY backend_access ON v7_private.customer_message_limits TO v7_backend USING (true) WITH CHECK (true);
CREATE POLICY backend_access ON v7_private.customer_message_counts TO v7_backend USING (true) WITH CHECK (true);
REVOKE ALL ON v7_private.customer_message_limits FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON v7_private.customer_message_counts FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON v7_private.customer_message_limits TO v7_backend;
GRANT SELECT, INSERT, UPDATE, DELETE ON v7_private.customer_message_counts TO v7_backend;
COMMIT;
