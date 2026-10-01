"""OAuth discovery and browser consent, using the existing management login."""
from urllib.parse import parse_qsl, urlencode
import re

from flask import Blueprint, abort, jsonify, redirect, render_template, request, session, url_for
from werkzeug.exceptions import HTTPException
from werkzeug.datastructures import MultiDict

from service import mcp_auth
from service.security import management_user, require_permission

bp = Blueprint("mcp_oauth", __name__)


@bp.after_request
def private(response):
    if response.status_code == 429:
        response.headers["Retry-After"] = "60"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "default-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
    return response


@bp.errorhandler(HTTPException)
def oauth_error(error):
    allowed = {"invalid_client", "invalid_grant", "invalid_scope", "unsupported_grant_type", "invalid_request", "invalid_redirect_uri", "pkce_required"}
    return jsonify(error=error.description if error.description in allowed else "access_denied"), error.code


@bp.get("/.well-known/oauth-protected-resource")
@bp.get("/.well-known/oauth-protected-resource/mcp")
def protected_resource():
    return jsonify(resource=mcp_auth.resource(), authorization_servers=[mcp_auth.issuer()],
                   scopes_supported=sorted(mcp_auth.SCOPES), bearer_methods_supported=["header"])


@bp.get("/.well-known/oauth-authorization-server")
def metadata():
    base = mcp_auth.issuer()
    return jsonify(issuer=base, authorization_endpoint=base + "/oauth/authorize",
                   token_endpoint=base + "/oauth/token", response_types_supported=["code"],
                   grant_types_supported=["authorization_code", "refresh_token"],
                   code_challenge_methods_supported=["S256"], scopes_supported=sorted(mcp_auth.SCOPES),
                   token_endpoint_auth_methods_supported=["none", "client_secret_post"])


@bp.route("/oauth/authorize", methods=["GET", "POST"])
def authorize():
    data = mcp_auth.authorization_request(request.args)
    error = None
    if request.method == 'POST' and request.form.get('decision') not in {'allow','deny'}:
        abort(400)
    identity = management_user() if session.get("management_token") else None
    if identity and identity.get("roles") != ["business_owner"]:
        abort(403)
    if request.method == "POST" and request.form.get("decision") in {"allow", "deny"}:
        identity = management_user()
        result = {"state": data["state"]}
        if request.form["decision"] == "allow":
            result["code"] = mcp_auth.authorize(data, identity)
        else:
            result["error"] = "access_denied"
        separator = "&" if "?" in data["redirect_uri"] else "?"
        return redirect(data["redirect_uri"] + separator + urlencode(result), 303)
    return render_template("mcp_consent.html", identity=identity, data=data, error=error)


@bp.post("/oauth/token")
def token():
    mcp_auth.rate_limit("oauth-token:" + (request.remote_addr or "unknown"), 30)
    if request.args:
        abort(400)
    if request.mimetype != "application/x-www-form-urlencoded":
        abort(415)
    if request.content_length is not None and request.content_length > 8192:
        abort(413)
    raw = request.stream.read(8193)
    if len(raw) > 8192:
        abort(413)
    try:
        values = MultiDict(parse_qsl(raw.decode("utf-8"), keep_blank_values=True,
                                    encoding="utf-8", errors="strict", max_num_fields=20))
    except (UnicodeError, ValueError):
        abort(400)
    return jsonify(mcp_auth.exchange(values))


@bp.post("/auth/mcp/revoke")
def revoke():
    identity = require_permission("integrations.read")
    if request.args:
        abort(400)
    if not request.is_json and any(len(request.form.getlist(key)) != 1 for key in request.form):
        abort(400)
    data = request.get_json(silent=True) if request.is_json else request.form.to_dict()
    if not isinstance(data, dict) or set(data) - {"connection_id", "csrf_token"}:
        abort(400)
    if "connection_id" in data and not isinstance(data["connection_id"], str):
        abort(400)
    mcp_auth.revoke_owner(identity, data.get("connection_id"))
    if not request.is_json:
        return redirect(url_for('owner_console.owner_console_asset', asset_path='integrations'), 303)
    return jsonify(ok=True)


@bp.get('/auth/mcp/connections')
def connections():
    """Public connection settings and this owner's grants, never tokens or secrets."""
    identity = require_permission("integrations.read")
    if set(request.args) - {"offset", "limit"}:
        abort(400)
    page = {}
    for key, default, minimum, maximum in (("offset", "0", 0, 100000), ("limit", "50", 1, 100)):
        raw = request.args.get(key, default)
        if not re.fullmatch(r"[0-9]{1,6}", raw) or not minimum <= int(raw) <= maximum:
            abort(400)
        page[key] = int(raw)
    settings = mcp_auth.connection_settings(identity)
    rows = mcp_auth.owner_connections(identity, **page) if identity.get("roles") == ["business_owner"] else []
    return jsonify(**settings, connections=rows,
                   next_offset=page["offset"] + len(rows) if len(rows) == page["limit"] else None)
