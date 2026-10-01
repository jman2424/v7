"""Small, first-party OAuth authorization-code service for owner MCP access.

Only pre-registered clients are accepted. Tokens are opaque, hashed at rest,
audience bound, short lived and invalidated by account changes.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from contextlib import contextmanager
from urllib.parse import urlsplit

from flask import abort, current_app, g

from service import session_store
from service.audit import AuditService
from service.security import _revision, _verify_password, management_user

SCOPES = {"business:read", "business:write"}


def issuer():
    value = os.getenv("MCP_PUBLIC_URL", "").rstrip("/")
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.netloc or parsed.path
            or parsed.query or parsed.fragment or parsed.username or parsed.password):
        abort(503, description="mcp_not_configured")
    if not current_app.testing and (
            current_app.container.settings.BASE_URL.rstrip("/") != value
            or not current_app.config.get("SESSION_COOKIE_SECURE")):
        abort(503, description="mcp_https_configuration_required")
    return value


def resource():
    return issuer() + "/mcp"


def require_origin(origin):
    """The MCP and REST transports share the same explicit origin allowlist."""
    allowed = {issuer(), *filter(None, os.getenv('MCP_ALLOWED_ORIGINS', '').split(','))}
    if origin is not None and origin not in allowed:
        abort(403)


def client_config(client_id):
    try:
        clients = json.loads(os.getenv("MCP_OAUTH_CLIENTS", "{}"))
        config = clients.get(client_id) if isinstance(clients, dict) else None
        if not isinstance(config, dict):
            abort(400, description="invalid_client")
        redirects = config.get("redirect_uris", [])
        if not isinstance(redirects, list) or not redirects:
            abort(503)
        for uri in redirects:
            p = urlsplit(uri)
            if p.scheme != "https" or not p.netloc or p.fragment or p.username or p.password:
                abort(503)
        if config.get("secret_hash") and (not isinstance(config["secret_hash"], str)
                or not config["secret_hash"].startswith("scrypt:")):
            abort(503, description="invalid_oauth_configuration")
        return config
    except (ValueError, TypeError):
        abort(503, description="invalid_oauth_configuration")


@contextmanager
def database():
    source = session_store.postgres_connection() if session_store._using_postgres() else session_store.connection()
    with source as db:
        if not session_store._using_postgres():
            db.execute("CREATE TABLE IF NOT EXISTS mcp_grants (digest TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL, expires REAL NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS mcp_rate (identity TEXT PRIMARY KEY, window INTEGER NOT NULL, count INTEGER NOT NULL)")
        yield db


def _execute(db, sql, params=()):
    return db.execute(sql.replace('?', '%s') if session_store._using_postgres() else sql, params)


def _put(db, kind, payload, ttl):
    token = secrets.token_urlsafe(32)
    _execute(db, "INSERT INTO mcp_grants VALUES (?, ?, ?, ?)",
               (session_store._digest(token), kind, json.dumps(payload), time.time() + ttl))
    return token


def _get(db, token, kind, *, lock=False):
    if not isinstance(token, str) or not 20 <= len(token) <= 128:
        return None
    suffix = ' FOR UPDATE' if lock and session_store._using_postgres() else ''
    row = _execute(db, "SELECT payload FROM mcp_grants WHERE digest=? AND kind=? AND expires>?" + suffix,
                     (session_store._digest(token), kind, time.time())).fetchone()
    return json.loads(row[0]) if row else None


def live_identity(payload):
    identity = payload["identity"]
    revision = _revision(identity)
    if (identity.get("roles") != ["business_owner"] or not revision
            or not hmac.compare_digest(revision, payload["revision"])
            or payload["resource"] != resource()):
        abort(401, description="invalid_token")
    try:
        exists = current_app.container.storage.tenant_exists(identity["tenant"])
    except ValueError:
        abort(403)
    if not exists:
        abort(403)
    return identity


def authorization_request(args):
    # Reject repeated parameters, rather than allowing a parser discrepancy.
    if any(len(args.getlist(k)) != 1 for k in args):
        abort(400)
    data = {k: args.get(k, "") for k in (
        "client_id", "redirect_uri", "response_type", "scope", "state",
        "code_challenge", "code_challenge_method", "resource")}
    config = client_config(data["client_id"])
    if data["redirect_uri"] not in config["redirect_uris"]:
        abort(400, description="invalid_redirect_uri")
    if data["response_type"] != "code" or data["resource"] != resource():
        abort(400, description="invalid_request")
    if data["code_challenge_method"] != "S256" or not re.fullmatch(r"[A-Za-z0-9_-]{43}", data["code_challenge"]):
        abort(400, description="pkce_required")
    scopes = set(data["scope"].split())
    if "business:read" not in scopes or not scopes <= SCOPES or len(data["state"]) > 2048:
        abort(400, description="invalid_scope")
    data["scope"] = " ".join(sorted(scopes))
    return data


def authorize(data, identity):
    if identity.get("roles") != ["business_owner"] or not identity.get("tenant"):
        abort(403, description="business_owner_required")
    if management_user() != identity:
        abort(401, description="session_expired")
    payload = {**data, "identity": identity, "revision": g.management_revision,
               "connection_id": secrets.token_hex(16), "created_at": int(time.time())}
    live_identity(payload)
    with database() as db:
        _execute(db, "DELETE FROM mcp_grants WHERE expires<?", (time.time(),))
        return _put(db, "code", payload, 120)


def exchange(form):
    if any(len(form.getlist(k)) != 1 for k in form):
        abort(400)
    allowed = {"client_id", "client_secret", "grant_type", "resource", "scope", "code", "redirect_uri", "code_verifier", "refresh_token"}
    if set(form) - allowed:
        abort(400, description="invalid_request")
    client_id = form.get("client_id", "")
    config = client_config(client_id)
    secret_hash = config.get("secret_hash")
    if secret_hash and not _verify_password(form.get("client_secret", ""), secret_hash):
        abort(401, description="invalid_client")
    kind = {"authorization_code": "code", "refresh_token": "refresh"}.get(form.get("grant_type"))
    if not kind:
        abort(400, description="unsupported_grant_type")
    token = form.get("code" if kind == "code" else "refresh_token", "")
    with database() as db:
        if not session_store._using_postgres():
            db.execute("BEGIN IMMEDIATE")
        payload = _get(db, token, kind, lock=True)
        if (not payload or payload["client_id"] != client_id
                or form.get("resource") != payload["resource"]):
            abort(400, description="invalid_grant")
        if kind == "code":
            verifier = form.get("code_verifier", "")
            if not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier):
                abort(400, description="invalid_grant")
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            if (not hmac.compare_digest(challenge, payload["code_challenge"])
                    or form.get("redirect_uri") != payload["redirect_uri"]):
                abort(400, description="invalid_grant")
        live_identity(payload)
        if form.get("scope") and form["scope"] != payload["scope"]:
            abort(400, description="invalid_scope")
        _execute(db, "DELETE FROM mcp_grants WHERE digest=?", (session_store._digest(token),))
        return {"access_token": _put(db, "access", payload, 900),
                "refresh_token": _put(db, "refresh", payload, 30 * 86400),
                "token_type": "Bearer", "expires_in": 900, "scope": payload["scope"]}


def authenticate(header):
    issuer()  # Disabled unless explicitly configured; never fall back to cookies.
    if not header.startswith("Bearer "):
        abort(401, description="invalid_token")
    with database() as db:
        payload = _get(db, header[7:], "access")
    if not payload:
        abort(401, description="invalid_token")
    identity = live_identity(payload)
    client_config(payload["client_id"])  # Removing a registered client revokes access.
    rate_limit("owner:" + identity["id"] + ":" + identity["tenant"], 60)
    return identity, set(payload["scope"].split())


def rate_limit(identity, limit):
    with database() as db:
        key = session_store._digest(identity)
        if session_store._using_postgres():
            lock = int.from_bytes(bytes.fromhex(key)[:8], "big", signed=True)
            db.execute("SELECT pg_advisory_xact_lock(%s)", (lock,))
        else:
            db.execute("BEGIN IMMEDIATE")
        window = int(time.time() // 60)
        _execute(db, 'DELETE FROM mcp_rate WHERE "window"<?', (window,))
        row = _execute(db, 'SELECT count FROM mcp_rate WHERE identity=? AND "window"=?', (key, window)).fetchone()
        if row and row[0] >= limit:
            abort(429)
        _execute(db, 'INSERT INTO mcp_rate VALUES (?, ?, 1) ON CONFLICT(identity) DO UPDATE SET "window"=excluded."window", count=mcp_rate.count+1', (key, window))


def _owner_predicate():
    return ("payload::jsonb #>> '{identity,id}'=? AND payload::jsonb #>> '{identity,tenant}'=?"
            if session_store._using_postgres() else
            "json_extract(payload, '$.identity.id')=? AND json_extract(payload, '$.identity.tenant')=?")


def owner_connections(identity, offset=0, limit=50):
    if identity.get("roles") != ["business_owner"] or not identity.get("tenant"):
        abort(403)
    connection = ("payload::jsonb ->> 'connection_id'" if session_store._using_postgres()
                  else "json_extract(payload, '$.connection_id')")
    with database() as db:
        rows = _execute(db,
            "WITH connections AS (SELECT payload, expires, ROW_NUMBER() OVER (PARTITION BY " + connection +
            " ORDER BY expires DESC) AS rank FROM mcp_grants WHERE kind IN ('access','refresh') "
            "AND expires>? AND " + _owner_predicate() + ") SELECT payload, expires FROM connections "
            "WHERE rank=1 ORDER BY expires DESC LIMIT ? OFFSET ?",
            (time.time(), identity['id'], identity['tenant'], limit, offset)).fetchall()
    return [{"connection_id": payload.get("connection_id"), "client_id": payload["client_id"],
             "scopes": payload["scope"].split(), "created_at": payload.get("created_at"), "expires_at": expires}
            for raw, expires in rows if (payload := json.loads(raw))]


def revoke_owner(identity, connection_id=None, source="dashboard"):
    if identity.get("roles") != ["business_owner"] or not identity.get("tenant"):
        abort(403)
    if connection_id is not None and (not isinstance(connection_id, str) or not re.fullmatch(r"[a-f0-9]{32}", connection_id)):
        abort(400, description="invalid_request")
    audit = AuditService()
    common = {"user": identity["id"], "role": "business_owner", "ip": "",
              "action": "revoke_mcp_connection", "target": connection_id or "all"}
    extra = {"tenant": identity["tenant"], "source": source}
    audit.record(**common, extra={**extra, "result": "attempted"})
    with database() as db:
        query = "DELETE FROM mcp_grants WHERE " + _owner_predicate()
        values = [identity["id"], identity["tenant"]]
        if connection_id is not None:
            query += (" AND payload::jsonb ->> 'connection_id'=?" if session_store._using_postgres()
                      else " AND json_extract(payload, '$.connection_id')=?")
            values.append(connection_id)
        _execute(db, query, values)
    audit.record(**common, extra={**extra, "result": "success"})


def connection_settings(identity):
    from werkzeug.exceptions import HTTPException
    base = ''
    clients = []
    configured = False
    try:
        base = issuer()
        entries = json.loads(os.getenv('MCP_OAUTH_CLIENTS', '{}'))
        if isinstance(entries, dict):
            for client_id in entries:
                client_config(client_id)
                clients.append(client_id)
        configured = bool(clients)
    except (HTTPException, ValueError, TypeError):
        clients = []
    owner = identity.get('roles') == ['business_owner']
    connected = []
    if owner:
        with database() as db:
            predicate = ("payload::jsonb #>> '{identity,id}'=? AND payload::jsonb #>> '{identity,tenant}'=?"
                         if session_store._using_postgres() else
                         "json_extract(payload, '$.identity.id')=? AND json_extract(payload, '$.identity.tenant')=?")
            rows = _execute(db, "SELECT payload FROM mcp_grants WHERE kind IN ('access','refresh') AND expires>? AND " + predicate,
                              (time.time(), identity['id'], identity.get('tenant'))).fetchall()
        connected = sorted({json.loads(row[0])['client_id'] for row in rows} & set(clients))
    return dict(configured=configured, owner_access=owner, clients=clients,
                connected_clients=connected, mcp_url=base+'/mcp' if base else '',
                api_url=base+'/api/v1' if base else '',
                authorization_url=base+'/oauth/authorize' if base else '',
                token_url=base+'/oauth/token' if base else '')
