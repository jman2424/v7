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

from flask import abort, current_app

from service import session_store
from service.security import _revision, _verify_password

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
        return config
    except (ValueError, TypeError):
        abort(503, description="invalid_oauth_configuration")


@contextmanager
def database():
    with session_store.connection() as db:
        db.execute("CREATE TABLE IF NOT EXISTS mcp_grants (digest TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL, expires REAL NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS mcp_rate (identity TEXT PRIMARY KEY, window INTEGER NOT NULL, count INTEGER NOT NULL)")
        yield db


def _put(db, kind, payload, ttl):
    token = secrets.token_urlsafe(32)
    db.execute("INSERT INTO mcp_grants VALUES (?, ?, ?, ?)",
               (session_store._digest(token), kind, json.dumps(payload), time.time() + ttl))
    return token


def _get(db, token, kind):
    if not isinstance(token, str) or not 20 <= len(token) <= 128:
        return None
    row = db.execute("SELECT payload FROM mcp_grants WHERE digest=? AND kind=? AND expires>?",
                     (session_store._digest(token), kind, time.time())).fetchone()
    return json.loads(row[0]) if row else None


def live_identity(payload):
    identity = payload["identity"]
    revision = _revision(identity)
    if (identity.get("roles") != ["business_owner"] or not revision
            or not hmac.compare_digest(revision, payload["revision"])
            or payload["resource"] != resource()):
        abort(401, description="invalid_token")
    directory = current_app.container.storage.tenant_dir(identity["tenant"])
    if not directory.is_dir():
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
    payload = {**data, "identity": identity, "revision": _revision(identity)}
    live_identity(payload)
    with database() as db:
        db.execute("DELETE FROM mcp_grants WHERE expires<?", (time.time(),))
        return _put(db, "code", payload, 120)


def exchange(form):
    if any(len(form.getlist(k)) != 1 for k in form):
        abort(400)
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
        db.execute("BEGIN IMMEDIATE")
        payload = _get(db, token, kind)
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
        db.execute("DELETE FROM mcp_grants WHERE digest=?", (session_store._digest(token),))
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
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        window = int(time.time() // 60)
        key = session_store._digest(identity["id"] + ":" + identity["tenant"])
        db.execute("DELETE FROM mcp_rate WHERE window<?", (window,))
        row = db.execute("SELECT count FROM mcp_rate WHERE identity=? AND window=?", (key, window)).fetchone()
        if row and row[0] >= 60:
            abort(429)
        db.execute("INSERT INTO mcp_rate VALUES (?, ?, 1) ON CONFLICT(identity) DO UPDATE SET count=count+1", (key, window))
    return identity, set(payload["scope"].split())


def revoke_owner(identity):
    with database() as db:
        # Payload is trusted server-created JSON; scope revocation to this owner.
        db.execute("DELETE FROM mcp_grants WHERE json_extract(payload, '$.identity.id')=? AND json_extract(payload, '$.identity.tenant')=?",
                   (identity["id"], identity.get("tenant")))


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
            rows = db.execute("SELECT payload FROM mcp_grants WHERE kind IN ('access','refresh') AND expires>? AND json_extract(payload, '$.identity.id')=? AND json_extract(payload, '$.identity.tenant')=?",
                              (time.time(), identity['id'], identity.get('tenant'))).fetchall()
        connected = sorted({json.loads(row[0])['client_id'] for row in rows} & set(clients))
    return dict(configured=configured, owner_access=owner, clients=clients,
                connected_clients=connected, mcp_url=base+'/mcp' if base else '',
                api_url=base+'/api/v1' if base else '',
                authorization_url=base+'/oauth/authorize' if base else '',
                token_url=base+'/oauth/token' if base else '')
