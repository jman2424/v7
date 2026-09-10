"""Revocable management sessions and login throttling shared by local workers."""
import hashlib
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def connection():
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
    with connection() as db:
        db.execute("DELETE FROM management_sessions WHERE expires < ?", (time.time(),))
        db.execute("INSERT INTO management_sessions VALUES (?, ?, ?, ?)",
                   (_digest(token), json.dumps(identity), revision, time.time() + 8 * 3600))
    return token


def read(token):
    if not isinstance(token, str) or len(token) > 128:
        return None
    with connection() as db:
        row = db.execute("SELECT identity, revision FROM management_sessions WHERE token_hash=? AND expires>?",
                         (_digest(token), time.time())).fetchone()
    return (json.loads(row[0]), row[1]) if row else None


def revoke(token):
    if isinstance(token, str):
        with connection() as db:
            db.execute("DELETE FROM management_sessions WHERE token_hash=?", (_digest(token),))


def allow_login(ip):
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
