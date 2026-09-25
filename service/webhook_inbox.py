"""Persistent duplicate suppression for provider-assigned WhatsApp message IDs."""
import hashlib
import time

from service import session_store


def claim(tenant, provider, message_id):
    now = time.time()
    if session_store._using_postgres():
        lock_data = f'{tenant}\0{provider}\0{message_id}'.encode()
        lock_key = int.from_bytes(hashlib.sha256(lock_data).digest()[:8], 'big', signed=True)
        with session_store.postgres_connection(tenant) as db:
            db.execute('SELECT pg_advisory_xact_lock(%s)', (lock_key,))
            db.execute('DELETE FROM v7_private.webhook_inbox WHERE updated < %s', (now - 7 * 86400,))
            row = db.execute(
                'SELECT state, updated, reply FROM v7_private.webhook_inbox '
                'WHERE tenant=%s AND provider=%s AND message_id=%s',
                (tenant, provider, message_id),
            ).fetchone()
            if row and row[0] == 'done':
                return 'done', row[2]
            if row and row[0] == 'processing' and now - row[1] < 120:
                return 'busy', None
            db.execute(
                'INSERT INTO v7_private.webhook_inbox '
                '(tenant, provider, message_id, state, updated, reply) '
                "VALUES (%s, %s, %s, 'processing', %s, NULL) "
                "ON CONFLICT (tenant, provider, message_id) DO UPDATE "
                "SET state='processing', updated=EXCLUDED.updated",
                (tenant, provider, message_id, now),
            )
        return 'new', None
    with session_store.connection() as db:
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
    if session_store._using_postgres():
        with session_store.postgres_connection(tenant) as db:
            db.execute(
                'UPDATE v7_private.webhook_inbox SET state=%s, updated=%s, reply=%s '
                'WHERE tenant=%s AND provider=%s AND message_id=%s',
                ('failed' if failed else 'done', time.time(), reply, tenant, provider, message_id),
            )
        return
    with session_store.connection() as db:
        db.execute("UPDATE webhook_inbox SET state=?, updated=?, reply=? WHERE tenant=? AND provider=? AND message_id=?",
                   ("failed" if failed else "done", time.time(), reply, tenant, provider, message_id))
