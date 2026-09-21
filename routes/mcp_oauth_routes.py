"""OAuth discovery and browser consent, using the existing management login."""
from urllib.parse import urlencode

from flask import Blueprint, abort, jsonify, redirect, render_template, request, session, url_for
from werkzeug.exceptions import HTTPException

from service import mcp_auth
from service.security import management_user

bp = Blueprint("mcp_oauth", __name__)


@bp.after_request
def private(response):
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
    if request.mimetype != "application/x-www-form-urlencoded":
        abort(415)
    return jsonify(mcp_auth.exchange(request.form))


@bp.post("/auth/mcp/revoke")
def revoke():
    mcp_auth.revoke_owner(management_user())
    if not request.is_json:
        return redirect(url_for('owner_console.owner_console_asset', asset_path='integrations'), 303)
    return jsonify(ok=True)
