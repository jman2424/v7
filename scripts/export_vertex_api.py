"""Generate the REST contract from the same operation schemas used by MCP."""
import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from routes.vertex_api_routes import ENDPOINTS
from service.mcp_tools import SPECS, WRITES


def document():
    result = {
        'openapi':'3.1.0',
        'info':{'title':'Vertex Seven REST API','version':'1.0.0',
                'description':'REST transport for the existing MCP operations. Uses the same owner OAuth grant, canonical resource /mcp, S256 PKCE, scopes, tenant and quotas. Cookie authentication is not accepted.'},
        'paths':{},
        'components':{'securitySchemes':{'vertexOAuth':{'type':'oauth2','flows':{'authorizationCode':{
            'authorizationUrl':'/oauth/authorize','tokenUrl':'/oauth/token',
            'scopes':{'business:read':'Read the assigned business','business:write':'Edit its catalog and offers'}}}}}},
    }
    for method,path,name in ENDPOINTS:
        spec = SPECS[name]
        schema = copy.deepcopy(spec['inputSchema'])
        path_names = re.findall(r'<(\w+)>',path)
        parameters = [{'in':'path','name':key,'required':True,'schema':schema['properties'].pop(key)} for key in path_names]
        schema['required'] = [key for key in schema.get('required',[]) if key not in path_names]
        operation = {'operationId':name,'summary':spec['description'],
                     'security':[{'vertexOAuth':['business:read','business:write'] if name in WRITES else ['business:read']}],
                     'responses':{'200':{'description':'Same structured result as the corresponding MCP tool','content':{'application/json':{'schema':{'type':'object'}}}}}}
        for status,description in [('400','Invalid arguments'),('401','Missing, expired or revoked bearer token'),('403','Role, scope, origin or activation denied'),('404','Business item not found'),('409','Revision conflict'),('413','Request exceeds 64 KiB'),('415','JSON content type required'),('429','Shared MCP/REST quota exceeded'),('503','Integration not configured or storage unavailable')]:
            operation['responses'][status] = {'description':description}
        if method == 'GET':
            parameters += [{'in':'query','name':key,'required':key in schema.get('required',[]),'schema':value} for key,value in schema['properties'].items()]
        else:
            operation['requestBody'] = {'required':True,'content':{'application/json':{'schema':schema}}}
        if parameters:
            operation['parameters'] = parameters
        result['paths'].setdefault('/api/v1'+re.sub(r'<(\w+)>',r'{\1}',path),{})[method.lower()] = operation
    return result


if __name__ == '__main__':
    (ROOT / 'schemas/vertex-api.openapi.json').write_text(json.dumps(document(),indent=2)+'\n',encoding='utf-8')
