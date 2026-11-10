"""REST transport over the exact authentication and dispatcher used by Vertex MCP."""
from pathlib import Path
import re
import sqlite3

from flask import Blueprint, abort, g, jsonify, request, send_file
from jsonschema import ValidationError
from werkzeug.exceptions import HTTPException

from routes import get_container
from service import mcp_auth, mcp_tools
from service.business_management import BusinessError

bp = Blueprint('vertex_api', __name__, url_prefix='/api/v1')

_CONTRACT = Path(__file__).resolve().parents[1] / 'schemas' / 'vertex-api.openapi.json'
_CONFIGURATION_ERRORS = {
    'mcp_not_configured': (
        'mcp_not_configured', 'The operator must configure the public HTTPS integration address.',
    ),
    'mcp_invalid_public_url': (
        'mcp_invalid_public_url', 'The operator must correct the public HTTPS integration address.',
    ),
    'mcp_https_configuration_required': (
        'mcp_https_configuration_required', 'The integration address must match the site’s HTTPS address.',
    ),
    'invalid_oauth_configuration': (
        'invalid_oauth_configuration', 'The operator must check the registered OAuth client settings.',
    ),
}

# These are transport mappings, not separate business implementations.
ENDPOINTS = (
    ('GET','/offerings','get_offerings'),
    ('GET','/offerings/<offering_id>','get_offering'),
    ('POST','/offerings','create_offering'),
    ('PATCH','/offerings/<offering_id>','update_offering'),
    ('GET','/locations','get_locations'),
    ('GET','/service-areas','get_service_areas'),
    ('GET','/business-rules','get_business_rules'),
    ('GET','/business-health','get_business_health'),
    ('GET','/jobs','get_jobs'),
    ('GET','/bookings','get_bookings'),
    ('GET','/orders','get_orders'),
    ('GET','/projects','get_projects'),
    ('GET','/viewings','get_viewings'),
    ('GET','/appointments','get_appointments'),
    ('GET','/tickets','get_tickets'),
    ('GET','/business-overview','get_business_overview'),
    ('GET','/statistics','get_statistics'),
    ('GET','/conversation-stats','get_conversation_stats'),
    ('GET','/popular-queries','get_popular_queries'),
    ('GET','/catalog','get_catalog'),
    ('GET','/catalog/search','search_catalog'),
    ('GET','/catalog/stats','get_catalog_stats'),
    ('POST','/catalog/items','add_catalog_item'),
    ('PATCH','/catalog/items','update_catalog_item'),
    ('POST','/catalog/items/disable','disable_catalog_item'),
    ('GET','/offers','get_offers'),
    ('POST','/offers','create_offer'),
    ('PATCH','/offers/<offer_id>','update_offer'),
    ('POST','/offers/<offer_id>/disable','disable_offer'),
    ('GET','/roles','get_roles'),
    ('GET','/users','get_users'),
    ('GET','/users/role','get_user_role'),
    ('GET','/health','get_agent_health'),
    ('GET','/errors','get_error_summary'),
    ('GET','/errors/recent','get_recent_errors'),
    ('GET','/service-status','get_service_status'),
    ('GET','/usage','get_usage'),
)


@bp.before_request
def authenticate():
    if request.endpoint == 'vertex_api.openapi':
        return
    # Cookie sessions never authenticate this API. OAuth scopes, token revocation,
    # assigned tenant, owner-only access and per-owner quotas are shared with MCP.
    g.vertex_identity, g.vertex_scopes = mcp_auth.authenticate(request.headers.get('Authorization',''))
    mcp_auth.require_origin(request.headers.get('Origin'))
    request.max_content_length = 65536


@bp.get('/openapi.json')
def openapi():
    """Serve the public REST contract independently of account and OAuth setup."""
    return send_file(_CONTRACT, mimetype='application/json')


@bp.after_request
def private(response):
    response.headers['Cache-Control'] = 'no-store'
    if response.status_code == 429:
        response.headers['Retry-After'] = '60'
    return response


@bp.errorhandler(HTTPException)
def http_error(error):
    code = error.name.lower().replace(' ', '_')
    message = error.name
    if error.code == 503 and isinstance(error.description, str) and error.description in _CONFIGURATION_ERRORS:
        code, message = _CONFIGURATION_ERRORS[error.description]
    elif error.code == 401:
        message = 'Supply a valid Vertex OAuth access token in the Authorization header.'
    response = jsonify(error={'code': code, 'message': message})
    response.status_code = error.code
    if error.code == 401:
        try:
            issuer = mcp_auth.issuer()
        except HTTPException:
            response.headers['WWW-Authenticate'] = 'Bearer scope="business:read"'
        else:
            metadata = issuer + '/.well-known/oauth-protected-resource/mcp'
            response.headers['WWW-Authenticate'] = f'Bearer resource_metadata="{metadata}", scope="business:read"'
    return response


def endpoint(tool):
    def handle(**selectors):
        try:
            if request.method in {'GET', 'HEAD'}:
                if any(len(request.args.getlist(key)) != 1 for key in request.args):
                    abort(400)
                arguments = request.args.to_dict()
                if set(selectors).intersection(arguments):
                    abort(400)
                arguments.update(selectors)
                properties = mcp_tools.SPECS[tool]['inputSchema']['properties']
                for key, value in list(arguments.items()):
                    if properties.get(key, {}).get('type') == 'integer':
                        if not re.fullmatch(r'[0-9]{1,9}',value):
                            abort(400)
                        arguments[key] = int(value)
            else:
                if request.args:
                    abort(400)
                if not request.is_json:
                    abort(415)
                arguments = request.get_json(silent=True)
                if not isinstance(arguments,dict) or set(selectors).intersection(arguments):
                    abort(400)
                arguments.update(selectors)
            result = mcp_tools.execute(get_container(),g.vertex_identity,g.vertex_scopes,tool,arguments,source='Vertex REST API')
            return jsonify(result)
        except BusinessError as error:
            status = {'forbidden':403,'not_found':404,'conflict':409}.get(error.code,400)
            return jsonify(error={'code':error.code,'message':error.message}), status
        except ValidationError:
            return jsonify(error={'code':'invalid_arguments','message':'The update does not match the business data schema.'}),400
        except (OSError,sqlite3.Error):
            return jsonify(error={'code':'service_unavailable','message':'Storage is unavailable. Re-read data before retrying a write; its outcome may be uncertain.'}),503
        except (ValueError,TypeError,KeyError):
            return jsonify(error={'code':'invalid_data','message':'Business data could not be processed. Ask the operator to validate it.'}),400
    return handle


for method,path,tool in ENDPOINTS:
    bp.add_url_rule(path, endpoint=tool, view_func=endpoint(tool), methods=[method])
