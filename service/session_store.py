"""Revocable management sessions and login throttling shared by workers."""
import hashlib
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


def _using_postgres():
    backend = os.getenv("V7_STORAGE_BACKEND", "sqlite").strip().lower()
    if backend not in {"sqlite", "postgres"}:
        raise RuntimeError("Unsupported V7_STORAGE_BACKEND value")
    return backend == "postgres"


@contextmanager
def _postgres_connection():
    import psycopg

    dsn = os.getenv("V7_POSTGRES_DSN", "")
    if not dsn:
        raise RuntimeError("V7_POSTGRES_DSN is required for PostgreSQL storage")
    try:
        # Never accept a weaker TLS mode from the DSN. The login must inherit
        # only the restricted backend role and must not own the private tables.
        with psycopg.connect(
            dsn,
            sslmode="verify-full",
            sslrootcert=os.getenv("V7_SUPABASE_CA_FILE") or "system",
            connect_timeout=15,
            autocommit=False,
        ) as db:
            role = db.execute(
                "SELECT current_user=session_user, "
                "rolsuper, rolbypassrls, rolcreatedb, rolcreaterole, "
                "pg_has_role(current_user, 'v7_backend', 'USAGE'), "
                "has_schema_privilege(current_user, 'v7_private', 'CREATE'), "
                "has_database_privilege(current_user, current_database(), 'CREATE') "
                "FROM pg_roles WHERE rolname=current_user"
            ).fetchone()
            memberships = db.execute(
                "SELECT r.rolname FROM pg_auth_members m "
                "JOIN pg_roles r ON r.oid=m.roleid "
                "WHERE m.member=(SELECT oid FROM pg_roles WHERE rolname=current_user)"
            ).fetchall()
            tables = db.execute(
                "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, "
                "c.relowner=(SELECT oid FROM pg_roles WHERE rolname=current_user) "
                "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='v7_private' "
                "AND c.relname IN ('management_sessions', 'login_attempts')"
            ).fetchall()
            if (role is None or not role[0] or any(role[1:5])
                    or not role[5] or role[6] or role[7]
                    or {row[0] for row in memberships} != {"v7_backend"}
                    or len(tables) != 2
                    or any(not row[1] or not row[2] or row[3] for row in tables)):
                raise RuntimeError("PostgreSQL security role or tables are not restricted")
            yield db
    except psycopg.Error:
        # Driver errors can contain connection details or sensitive row values.
        raise RuntimeError("Security database operation failed") from None


@contextmanager
def connection():
    if _using_postgres():
        # Other callers still issue SQLite-specific SQL. A generic translation
        # here could bypass tenant context or silently split writable state.
        raise RuntimeError("Security database caller requires PostgreSQL port")
    path = Path(os.getenv("SECURITY_DB_PATH", "logs/security.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    try:
        db.execute("CREATE TABLE IF NOT EXISTS management_sessions (token_hash TEXT PRIMARY KEY, identity TEXT NOT NULL, revision TEXT NOT NULL, expires REAL NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS login_attempts (ip_hash TEXT NOT NULL, attempted REAL NOT NULL)")
        db.execute("CREATE INDEX IF NOT EXISTS login_attempts_ip ON login_attempts(ip_hash, attempted)")
        yield db
        db.commit()
    finally:
        db.close()


def _digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def create(identity, revision):
    token = secrets.token_urlsafe(32)
    if _using_postgres():
        now = time.time()
        with _postgres_connection() as db:
            db.execute("DELETE FROM v7_private.management_sessions WHERE expires < %s", (now,))
            db.execute(
                "INSERT INTO v7_private.management_sessions "
                "(token_hash, identity, revision, expires) VALUES (%s, %s, %s, %s)",
                (_digest(token), json.dumps(identity), revision, now + 8 * 3600),
            )
        return token
    with connection() as db:
        db.execute("DELETE FROM management_sessions WHERE expires < ?", (time.time(),))
        db.execute("INSERT INTO management_sessions VALUES (?, ?, ?, ?)",
                   (_digest(token), json.dumps(identity), revision, time.time() + 8 * 3600))
    return token


def read(token):
    if not isinstance(token, str) or len(token) > 128:
        return None
    if _using_postgres():
        with _postgres_connection() as db:
            row = db.execute(
                "SELECT identity, revision FROM v7_private.management_sessions "
                "WHERE token_hash=%s AND expires>%s",
                (_digest(token), time.time()),
            ).fetchone()
        return (json.loads(row[0]), row[1]) if row else None
    with connection() as db:
        row = db.execute("SELECT identity, revision FROM management_sessions WHERE token_hash=? AND expires>?",
                         (_digest(token), time.time())).fetchone()
    return (json.loads(row[0]), row[1]) if row else None


def revoke(token):
    if isinstance(token, str):
        if _using_postgres():
            with _postgres_connection() as db:
                db.execute(
                    "DELETE FROM v7_private.management_sessions WHERE token_hash=%s",
                    (_digest(token),),
                )
            return
        with connection() as db:
            db.execute("DELETE FROM management_sessions WHERE token_hash=?", (_digest(token),))


def allow_login(ip):
    if _using_postgres():
        ip_hash = _digest(ip)
        # Serialize attempts for one address across all workers. A transaction
        # advisory lock is released on commit or rollback.
        lock_key = int.from_bytes(bytes.fromhex(ip_hash)[:8], "big", signed=True)
        with _postgres_connection() as db:
            db.execute("SELECT pg_advisory_xact_lock(%s)", (lock_key,))
            now = time.time()
            db.execute("DELETE FROM v7_private.login_attempts WHERE attempted < %s", (now - 300,))
            count = db.execute(
                "SELECT COUNT(*) FROM v7_private.login_attempts "
                "WHERE ip_hash=%s AND attempted>%s",
                (ip_hash, now - 60),
            ).fetchone()[0]
            if count >= 5:
                return False
            db.execute(
                "INSERT INTO v7_private.login_attempts (ip_hash, attempted) VALUES (%s, %s)",
                (ip_hash, now),
            )
        return True
    now = time.time()
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM login_attempts WHERE attempted < ?", (now - 300,))
        count = db.execute("SELECT COUNT(*) FROM login_attempts WHERE ip_hash=? AND attempted>?",
                           (_digest(ip), now - 60)).fetchone()[0]
        if count >= 5:
            return False
        db.execute("INSERT INTO login_attempts VALUES (?, ?)", (_digest(ip), now))
    return True
