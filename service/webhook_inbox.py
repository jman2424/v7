"""Persistent duplicate suppression for provider-assigned WhatsApp message IDs."""
import time

from service.session_store import connection


def claim(tenant, provider, message_id):
    now = time.time()
    with connection() as db:
        db.execute("CREATE TABLE IF NOT EXISTS webhook_inbox (tenant TEXT, provider TEXT, message_id TEXT, state TEXT NOT NULL, updated REAL NOT NULL, reply TEXT, PRIMARY KEY (tenant, provider, message_id))")
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM webhook_inbox WHERE updated < ?", (now - 7 * 86400,))
        row = db.execute("SELECT state, updated, reply FROM webhook_inbox WHERE tenant=? AND provider=? AND message_id=?",
                         (tenant, provider, message_id)).fetchone()
        if row and row[0] == "done":
            return "done", row[2]
        if row and row[0] == "processing" and now - row[1] < 120:
            return "busy", None
        db.execute("INSERT INTO webhook_inbox VALUES (?, ?, ?, 'processing', ?, NULL) "
                   "ON CONFLICT(tenant, provider, message_id) DO UPDATE SET state='processing', updated=excluded.updated",
                   (tenant, provider, message_id, now))
    return "new", None


def finish(tenant, provider, message_id, reply, failed=False):
    with connection() as db:
        db.execute("UPDATE webhook_inbox SET state=?, updated=?, reply=? WHERE tenant=? AND provider=? AND message_id=?",
                   ("failed" if failed else "done", time.time(), reply, tenant, provider, message_id))
