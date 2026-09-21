"""Tool contracts and thin adapters over V7 management and analytics services."""
from __future__ import annotations

import json
import math
import os
import re
from decimal import Decimal

from jsonschema import Draft202012Validator, FormatChecker

from service import analytics_db
from service.audit import AuditService
from service.business_management import BusinessError, BusinessManagement
from service.security import _registry_users


def obj(properties=None, required=()):
    return {"type": "object", "properties": properties or {}, "required": list(required), "additionalProperties": False}


TEXT = {"type": "string", "minLength": 1, "maxLength": 200, "pattern": r"\S"}
REVISION = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
PAGE = {"offset": {"type": "integer", "minimum": 0, "maximum": 100000}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}
WINDOW = {"minutes": {"type": "integer", "minimum": 1, "maximum": 43200}}
ITEM = obj({"name": TEXT, "price": {"type": "number", "minimum": 0, "maximum": 100000000},
            "price_str": {"type": "string", "minLength": 1, "maxLength": 200,
                          "pattern": r"^[^\d\-\n\r]{0,12}\d+(?:[.,]\d{1,2})?(?:[^\d\n\r].*)?$"},
            "in_stock": {"type": "boolean"}})
ITEM["minProperties"] = 1
OFFER = obj({"title": TEXT, "description": {"type": "string", "maxLength": 2000},
             "starts_at": {"type": "string", "format": "date-time", "maxLength": 40},
             "ends_at": {"type": "string", "format": "date-time", "maxLength": 40},
             "enabled": {"type": "boolean"}})
OFFER["minProperties"] = 1
from pathlib import Path
_offer_schema = json.loads((Path(__file__).resolve().parents[1] / 'schemas/offers.schema.json').read_text())['items']
OFFER['properties'].update({key:value for key,value in _offer_schema['properties'].items() if key != 'id'})

SPECS = {}


def spec(name, description, schema=None, write=False):
    SPECS[name] = {"name": name, "description": description, "inputSchema": schema or obj(),
                   "annotations": {"readOnlyHint": not write, "destructiveHint": write,
                                   "idempotentHint": not write, "openWorldHint": False},
                   "securitySchemes": [{"type": "oauth2", "scopes": ["business:read", "business:write"] if write else ["business:read"]}]}


for name, description in {
    "get_business_overview": "Get catalogue totals and recorded business activity. No revenue or sales conversion claims.",
    "get_statistics": "Get message, session and lead statistics plus daily activity for the last minutes (up to 30 days).",
    "get_conversation_stats": "Get conversation totals and channel split without private transcripts.",
    "get_popular_queries": "Get common query intent categories and fallback categories; raw customer messages are withheld.",
    "get_agent_health": "Get tenant data availability and recent recorded channel activity. External provider health is unknown.",
    "get_error_summary": "Get recorded error counts. Raw messages, stack traces and credentials are never returned.",
    "get_recent_errors": "Get recent tenant error timestamps and channels, without raw error text.",
    "get_service_status": "Get observed API/data availability. WhatsApp activity does not prove provider health.",
    "get_usage": "Get recorded message usage, not token spend or billing estimates.",
}.items():
    spec(name, description, obj(WINDOW))
SPECS["get_statistics"]["description"] += " For comparisons, call separately with explicit start_at/end_at time zones; each window is at most 30 days and end_at is exclusive."
SPECS["get_statistics"]["inputSchema"] = {
    **obj({**WINDOW, "start_at": {"type": "string", "format": "date-time", "maxLength": 40},
           "end_at": {"type": "string", "format": "date-time", "maxLength": 40}}),
    "oneOf": [{"not": {"anyOf": [{"required": ["start_at"]}, {"required": ["end_at"]}]}},
              {"required": ["start_at", "end_at"], "not": {"required": ["minutes"]}}],
}
spec("get_catalog", "Read catalogue items with exact category/name selectors and revision for safe edits.", obj(PAGE))
spec("search_catalog", "Search catalogue item names; results include the current revision.", obj({**PAGE, "query": TEXT}, ["query"]))
spec("get_catalog_stats", "Get counts of catalogue items and unavailable items.")
spec("get_offers", "Read offers and their effective active status. Offers are informational; they do not change checkout prices.", obj(PAGE))
spec("get_users", "Read tenant-assigned management accounts only, without credentials or global administrators.", obj(PAGE))
spec("get_roles", "Read the existing management role definitions and the caller's MCP permissions.")
spec("get_user_role", "Read the role of an account assigned to this business.", obj({"email": {"type": "string", "maxLength": 254}}, ["email"]))
selector = {"category": TEXT, "name": TEXT, "expected_revision": REVISION}
spec("update_catalog_item", "Update one exact catalogue item. Read the catalogue first and use its revision; price_str preserves legacy currency/unit text.",
     obj({**selector, "changes": ITEM}, [*selector, "changes"]), True)
spec("disable_catalog_item", "Mark one exact catalogue item out of stock; retain its record.", obj(selector, selector), True)
spec("add_catalog_item", "Add a catalogue item to an existing category. Use price for numeric catalogues or price_str for legacy catalogues.",
     obj({"category": TEXT, "expected_revision": REVISION, "item": {**ITEM, "required": ["name"],
         "oneOf": [{"required": ["price"]}, {"required": ["price_str"]}]}}, ["category", "expected_revision", "item"]), True)
spec("create_offer", "Create a dated informational offer; does not apply automatic discounts. Read offers first for its revision.",
     obj({"expected_revision": REVISION, "offer": {**OFFER, "required": ["title", "description"]}}, ["expected_revision", "offer"]), True)
offer_selector = {"offer_id": TEXT, "expected_revision": REVISION}
spec("update_offer", "Update one offer using its ID and current offers revision.", obj({**offer_selector, "changes": OFFER}, [*offer_selector, "changes"]), True)
spec("disable_offer", "Disable one offer while retaining its record.", obj(offer_selector, offer_selector), True)
# Generic vocabulary is additive; existing retail contracts remain unchanged.
from service.business_core import OFFERING
import copy
GENERIC_OFFERING = copy.deepcopy(OFFERING)
GENERIC_OFFERING['properties'].pop('id')
GENERIC_OFFERING['required'].remove('id')
GENERIC_CHANGES = obj(GENERIC_OFFERING['properties'])
GENERIC_CHANGES['minProperties'] = 1
for tool in ('get_offerings','get_locations','get_service_areas','get_business_rules',
             'get_jobs','get_bookings','get_orders','get_projects','get_viewings','get_appointments','get_tickets'):
    spec(tool, 'Read tenant-scoped business records. Work records do not imply live scheduling or payment.', obj(PAGE))
spec('get_offering','Read an offering by ID, with its source document revision.',obj({'offering_id':TEXT},['offering_id']))
spec('create_offering','Create a generic offering using the business-core revision from get_offerings.',obj({'expected_revision':REVISION,'offering':GENERIC_OFFERING},['expected_revision','offering']),True)
spec('update_offering','Update an offering using its ID and source revision. Retail records retain their original catalog format.',obj({'expected_revision':REVISION,'offering_id':TEXT,'changes':GENERIC_CHANGES},['expected_revision','offering_id','changes']),True)
spec('get_business_health','Read tenant data availability and channel observations.',obj(WINDOW))
WRITES = {name for name, tool in SPECS.items() if not tool["annotations"]["readOnlyHint"]}


def validate(name, args):
    if name not in SPECS:
        raise BusinessError("unknown_tool", "Unknown tool.")
    # jsonschema considers NaN a number. JSON must contain finite values only.
    def finite(value):
        if isinstance(value, float) and not math.isfinite(value):
            return False
        if isinstance(value, dict):
            return all(finite(v) for v in value.values())
        if isinstance(value, list):
            return all(finite(v) for v in value)
        return True
    validator = Draft202012Validator(SPECS[name]["inputSchema"], format_checker=FormatChecker())
    if not finite(args) or not validator.is_valid(args):
        raise BusinessError("invalid_arguments", "Arguments do not match this tool's schema. Check required fields, types and allowed ranges.")
    for key in ("item", "changes"):
        changes = args.get(key, {})
        if name not in {"create_offering", "update_offering"} and "price" in changes and Decimal(str(changes["price"])) % Decimal("0.01"):
            raise BusinessError("invalid_arguments", "Price must have at most two decimal places.")
    if name == "get_statistics" and "start_at" in args:
        try:
            analytics_db._statistics_window(1, args["start_at"], args["end_at"])
        except ValueError:
            raise BusinessError("invalid_arguments", "Statistics windows must be positive and at most 30 days.") from None


def sanitize(payload, container):
    """Defense in depth: allowlisted responses plus known secret-value redaction."""
    secrets = []
    for key, value in os.environ.items():
        if re.search(r"SECRET|TOKEN|PASSWORD|API_KEY|DATABASE_URL|DSN", key, re.I) and value:
            secrets.append(value)
    for record in _registry_users(container):
        for key in ("password_hash", "totp_secret"):
            if record.get(key):
                secrets.append(record[key])
    def clean(value):
        if isinstance(value, str):
            for secret in secrets:
                if len(secret) >= 4:
                    value = re.sub(re.escape(secret), "[redacted]", value, flags=re.I)
            value = re.sub(r"(?i)(?:bearer\s+|sk-(?:proj-)?)[A-Za-z0-9_.-]+", "[redacted]", value)
            value = re.sub(r"(?i)(?:password|api[_ -]?key|token|secret)\s*[:=]\s*\S+", "[redacted]", value)
            return value
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value
    return clean(payload)


def execute(container, identity, scopes, name, args, *, source='ChatGPT MCP'):
    try:
        validate(name, args)
        required = "business:write" if name in WRITES else "business:read"
        if required not in scopes:
            raise BusinessError("forbidden", "This connection does not have the required scope.")
    except BusinessError:
        if name in WRITES:
            AuditService().record(user=identity["id"], role=identity["roles"][0], ip="", action=name,
                                  target=identity["tenant"], extra={"tenant": identity["tenant"], "source": source, "result": "rejected"})
        raise
    business = BusinessManagement(container.storage, identity["tenant"], identity, source)
    if name == 'get_business_health':
        from service.business_core import BusinessCore
        core = BusinessCore(container.storage, identity['tenant'])
        return sanitize({'api':'responding','offerings':len(core.offerings()),'locations':len(core.locations()),
                         'provider_health':'unknown','coverage':'Saved tenant records; not a provider probe'}, container)
    if name == 'update_offering' and args['offering_id'].startswith('retail:'):
        from service.business_core import BusinessCore
        item = BusinessCore(container.storage, identity['tenant']).get('get_offering', {'offering_id':args['offering_id']})
        if set(args['changes']) - {'name','price'}:
            raise BusinessError('invalid_arguments','Retail aliases support name and price edits. Use existing catalog tools for stock and legacy display prices.')
        args = {'category':item['category'],'name':item['name'],'expected_revision':args['expected_revision'],'changes':args['changes']}
        name = 'update_catalog_item'
    if name in WRITES:
        result = business.mutate(name, args)
        container.invalidate_tenant(identity['tenant'])
        return sanitize(result, container)
    tenant = identity["tenant"]
    window = {"tenant": tenant, "minutes": args.get("minutes", 10080)}
    if name == "get_statistics" and "start_at" in args:
        window.update(start_at=args["start_at"], end_at=args["end_at"])
    if name in {'get_offerings','get_offering','get_locations','get_service_areas','get_business_rules',
                'get_jobs','get_bookings','get_orders','get_projects','get_viewings','get_appointments','get_tickets'}:
        from service.business_core import BusinessCore
        result = BusinessCore(container.storage, tenant).get(name,args)
    elif name in {"get_catalog", "search_catalog"}:
        result = business.catalog(**args)
    elif name == "get_offers":
        result = business.offers(**args)
    elif name == "get_catalog_stats":
        doc = business.document("catalog.json")
        items = [i for c in doc.get("product_catalog", doc.get("categories", [])) for i in c["items"]]
        result = {"total": len(items), "unavailable": sum(i.get("in_stock") is False or any(w in str(i.get("stock", "")).lower() for w in ("out", "sold", "no")) for i in items)}
    elif name in {"get_users", "get_user_role"}:
        users = [{"email": r.get("email"), "role": r.get("role"), "disabled": bool(r.get("disabled"))}
                 for r in _registry_users(container) if r.get("tenant") == tenant]
        from service.account_service import AccountService
        known = {str(row['email']).casefold() for row in users}
        users.extend({'email':row['email'],'role':row['roles'][0] if row['roles'] else '', 'disabled':not row['active']}
                     for row in AccountService(container.storage).list_accounts(tenant) if row['email'].casefold() not in known)
        if name == "get_user_role":
            users = [r for r in users if r["email"].casefold() == args["email"].casefold()]
            if not users:
                raise BusinessError("not_found", "Account is not assigned to this business.")
        offset, limit = args.get("offset", 0), args.get("limit", 50)
        result = {"users": users[offset:offset + limit], "total": len(users),
                  "next_offset": offset + limit if offset + limit < len(users) else None,
                  "coverage": "tenant-assigned management accounts; global administrators excluded"}
    elif name == "get_roles":
        result = {"roles": [{"name": "business_owner", "scope": "assigned business"},
                            {"name": "business_staff", "scope": "assigned business"},
                            {"name": "admin", "scope": "platform"}, {"name": "platform_admin", "scope": "platform"}],
                  "mcp_role": "business_owner", "connection_scopes": sorted(scopes),
                  "users_and_roles_writable": False, "staff_login_supported": True, 'staff_mcp_access':False}
    elif name == "get_popular_queries":
        result = {"intents": analytics_db.get_top_intents(**window), "fallbacks": analytics_db.get_fallbacks(**window),
                  "coverage": "aggregated intent categories; raw messages excluded"}
    elif name in {"get_error_summary", "get_recent_errors"}:
        result = {"count": analytics_db.get_kpis(**window)["errors"], "window_minutes": window["minutes"]}
        if name == "get_recent_errors":
            result["errors"] = analytics_db.get_safe_recent_errors(**window)
        result["coverage"] = "tenant analytics error events only; raw server logs excluded"
    elif name in {"get_agent_health", "get_service_status"}:
        result = {"api": "responding", "catalogue": "readable" if business.catalog(limit=1) else "unknown",
                  "channels": analytics_db.get_channels_split(**window), "provider_health": "unknown",
                  "coverage": "observed activity, no external provider probe", "window_minutes": window["minutes"]}
    else:
        result = {"kpis": analytics_db.get_kpis(**window), "window_minutes": window["minutes"]}
        if name == "get_business_overview":
            result["catalogue_items"] = business.catalog(limit=1)["total"]
            result["offers"] = business.offers(limit=1)["total"]
        if name == "get_statistics":
            result["daily"] = analytics_db.get_overview_daily(**window)
            result["window_minutes"] = result["kpis"]["minutes"]
            if "start_at" in args:
                result.update(start_at=args["start_at"], end_at=args["end_at"])
        if name == "get_conversation_stats":
            result["channels"] = analytics_db.get_channels_split(**window)
            result["sessions_by_channel"] = analytics_db.get_sessions_by_channel(**window)
        if name == "get_usage":
            result["billing_and_token_usage"] = "not exposed by this tool"
    return sanitize(result, container)
