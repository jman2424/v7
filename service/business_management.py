"""Reusable catalogue and offer operations; no MCP or HTTP business logic."""
from __future__ import annotations

import copy
import hashlib
import json
import uuid
from datetime import datetime, timezone, timedelta

from retrieval.catalog_store import _parse_price_str
from service.audit import AuditService


class BusinessError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(code)


def revision(document):
    return hashlib.sha256(json.dumps(document, sort_keys=True, allow_nan=False).encode()).hexdigest()


def project(item, fields):
    return {key: item[key] for key in fields if key in item}


CATALOG_FIELDS = ("sku", "name", "price", "price_str", "unit", "in_stock", "stock", "subcategory")
OFFER_FIELDS = ('id','title','description','active','starts_on','ends_on','archived','code',
                'product_skus','deal_type','minimum_spend','discount_type','discount_value')


class BusinessManagement:
    def __init__(self, storage, tenant, identity=None, source="dashboard"):
        self.storage = storage
        self.tenant = tenant
        self.identity = identity
        self.source = source
        if not storage.tenant_dir(tenant).is_dir():
            raise BusinessError("not_found", "Business does not exist.")

    def document(self, filename):
        try:
            return self.storage.read_json(self.tenant, filename)
        except FileNotFoundError:
            if filename == "business_core.json":
                from service.business_core import empty_core
                return empty_core()
            if filename == "offers.json":
                return []
            raise BusinessError("not_found", "Catalogue is not configured.") from None

    def catalog(self, offset=0, limit=50, query=""):
        doc = self.document("catalog.json")
        items = []
        # Address legacy rows without rewriting their format or generated SKUs.
        for category in doc.get("product_catalog", doc.get("categories", [])):
            for item in category["items"]:
                if query.casefold() not in item["name"].casefold():
                    continue
                items.append({"category": category["name"], **project(item, CATALOG_FIELDS)})
        return {"revision": revision(doc), "items": items[offset:offset + limit],
                "total": len(items), "next_offset": offset + limit if offset + limit < len(items) else None}

    def offers(self, offset=0, limit=50):
        doc = self.document("offers.json")
        from retrieval.offer_store import OfferStore
        from types import SimpleNamespace
        active_ids = {item['id'] for item in OfferStore(SimpleNamespace(tenant_key=self.tenant, read_json=self.storage.read_json)).active()}
        items = [{**project(item, OFFER_FIELDS), 'effective_active':item['id'] in active_ids} for item in doc]
        return {"revision": revision(doc), "items": items[offset:offset + limit], "total": len(items),
                "next_offset": offset + limit if offset + limit < len(items) else None}

    def mutate(self, action, args):
        from service.mcp_tools import validate
        validate(action, args)
        if not self.identity or self.identity.get("roles") != ["business_owner"] or self.identity.get("tenant") != self.tenant:
            raise BusinessError("forbidden", "Business owner permission is required.")
        from service.tenant_access import activation
        if not activation(self.tenant)['active']:
            raise BusinessError('forbidden', 'Business activation is required before editing.')
        filename = "business_core.json" if action in {"create_offering", "update_offering"} else "offers.json" if "offer" in action else "catalog.json"
        operation_id = uuid.uuid4().hex
        audit = AuditService()
        common = {"user": self.identity["id"], "role": "business_owner", "ip": "",
                  "action": action, "target": f"{self.tenant}/{filename}"}
        extra = {"source": self.source, "tenant": self.tenant, "operation_id": operation_id}
        # Record the attempt before any data mutation; no caller text in logs.
        audit.record(**common, extra={**extra, "result": "attempted"})
        try:
            with self.storage.write_lock():
                doc = self.document(filename)
                if args["expected_revision"] != revision(doc):
                    raise BusinessError("conflict", "Data changed. Read the current revision before trying again.")
                updated = copy.deepcopy(doc)
                if filename == 'business_core.json':
                    from service.business_core import validate_core
                    validate_core(updated)
                    if action == 'create_offering':
                        before = None
                        after = {'id':uuid.uuid4().hex, **args['offering']}
                        updated['offerings'].append(after)
                    else:
                        matches = [row for row in updated['offerings'] if row['id'] == args['offering_id']]
                        if len(matches) != 1:
                            raise BusinessError('not_found','Offering does not exist.')
                        after = matches[0]
                        before = copy.deepcopy(after)
                        after.update(args['changes'])
                    validate_core(updated)
                    schema = 'business-core.schema.json'
                elif filename == "catalog.json":
                    before, after, schema = self._catalog_change(updated, action, args)
                else:
                    before, after = self._offer_change(updated, action, args)
                    schema = "offers.schema.json"
                    from retrieval.offer_store import OfferStore
                    try:
                        OfferStore.validate(updated)
                    except ValueError as exc:
                        raise BusinessError('invalid_arguments', str(exc)) from None
                self.storage._validate_json(updated, self.storage._schema_path(schema))
                # Prepared record supports recovery if the process stops after replace.
                def audit_fields(item):
                    safe = project(item or {}, ("price", "in_stock", "active"))
                    if item and "price_str" in item:
                        safe["price"] = _parse_price_str(item["price_str"])
                    return safe
                safe_before = audit_fields(before)
                safe_after = audit_fields(after)
                audit.record(**common, before=safe_before, after=safe_after,
                             extra={**extra, "result": "prepared", "item_reference": revision(args.get("offer_id", {"category": args.get("category"), "name": args.get("name", after.get("name"))})),
                                    "before_revision": revision(doc), "after_revision": revision(updated)})
                self.storage._write_json(self.tenant, filename, updated, schema=schema)
                if filename == 'catalog.json':
                    from service.product_metrics import record_inventory
                    record_inventory(self.tenant, doc, updated)
                audit.record(**common, extra={**extra, "result": "success"})
                return {"ok": True, "operation_id": operation_id, "revision": revision(updated),
                        "item": after if filename == "business_core.json" else project(after, OFFER_FIELDS if filename == "offers.json" else CATALOG_FIELDS)}
        except BusinessError:
            audit.record(**common, extra={**extra, "result": "rejected"})
            raise

    def _catalog_change(self, doc, action, args):
        legacy = "product_catalog" in doc
        categories = doc["product_catalog" if legacy else "categories"]
        matches = [c for c in categories if c["name"] == args["category"]]
        if len(matches) != 1:
            raise BusinessError("not_found", "Category must identify exactly one existing category.")
        category = matches[0]
        items = category["items"]
        creating = action == "add_catalog_item"
        if creating:
            if any(i["name"] == args["item"]["name"] for i in items):
                raise BusinessError("conflict", "An item with this name already exists in the category.")
            target = {"name": args["item"]["name"]}
            if not legacy:
                target["sku"] = "mcp_" + uuid.uuid4().hex
            items.append(target)
            before = None
            changes = args["item"]
        else:
            matches = [i for i in items if i["name"] == args["name"]]
            if len(matches) != 1:
                raise BusinessError("not_found", "Item must identify exactly one item in this category.")
            target = matches[0]
            before = copy.deepcopy(target)
            changes = {"in_stock": False} if action == "disable_catalog_item" else args["changes"]
        if "name" in changes and any(i is not target and i["name"] == changes["name"] for i in items):
            raise BusinessError("conflict", "An item with this name already exists in the category.")
        if "price" in changes and legacy:
            # Legacy prices can contain unit/range text; never silently discard it.
            raise BusinessError("invalid_arguments", "This catalogue uses price_str. Supply the complete displayed price including currency and unit.")
        if "price_str" in changes and not legacy:
            raise BusinessError("invalid_arguments", "This catalogue uses numeric price, not price_str.")
        for key, value in changes.items():
            if key == "in_stock" and legacy:
                target["stock"] = "in stock" if value else "out of stock"
            else:
                target[key] = value
        if changes.get('in_stock') is False and 'stock_quantity' in target:
            target['stock_quantity'] = 0
        if creating and "in_stock" not in changes:
            target["stock" if legacy else "in_stock"] = "in stock" if legacy else True
        if "version" in doc and isinstance(doc["version"], int):
            doc["version"] += 1
        return before, target, "catalog-sheet.schema.json" if legacy else "catalog.schema.json"

    def _offer_change(self, doc, action, args):
        changes = dict(args.get('offer', args.get('changes', {})))
        # Compatibility for the earlier local MCP contract: only whole UTC days
        # can be represented faithfully by the current shared offers store.
        for old, new in [('starts_at','starts_on'),('ends_at','ends_on')]:
            if old in changes:
                instant = datetime.fromisoformat(changes.pop(old).replace('Z','+00:00'))
                if instant.tzinfo is None or instant.astimezone(timezone.utc).time().isoformat() != '00:00:00' or new in changes:
                    raise BusinessError('invalid_arguments', 'Use starts_on/ends_on dates, or whole-day UTC legacy timestamps.')
                instant = instant.astimezone(timezone.utc)
                if old == 'ends_at':
                    instant -= timedelta(days=1)
                changes[new] = instant.date().isoformat()
        if 'enabled' in changes:
            if 'active' in changes:
                raise BusinessError('invalid_arguments', 'Use active or enabled, not both.')
            changes['active'] = changes.pop('enabled')
        if action == "create_offer":
            target = {"id": uuid.uuid4().hex, "active": True, **changes}
            doc.append(target)
            before = None
        else:
            matches = [o for o in doc if o["id"] == args["offer_id"]]
            if len(matches) != 1:
                raise BusinessError("not_found", "Offer does not exist in this business.")
            target = matches[0]
            before = copy.deepcopy(target)
            target.update({"active": False} if action == "disable_offer" else changes)
        return before, target
