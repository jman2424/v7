"""Generic tenant facts with read-through compatibility for retail documents."""
import copy
import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from service.business_management import BusinessError, revision

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / 'schemas/business-core.schema.json').read_text())
OFFERING = SCHEMA['properties']['offerings']['items']


def empty_core():
    return {'version':1, 'offerings':[], 'locations':[], 'business_rules':[], 'work':[]}


def validate_core(document):
    # Reject non-JSON floats as well as invalid schemas and duplicate identifiers.
    json.dumps(document, allow_nan=False)
    Draft202012Validator(SCHEMA, format_checker=FormatChecker()).validate(document)
    for field in ('offerings','locations','business_rules','work'):
        ids = [row['id'] for row in document[field]]
        if len(ids) != len(set(ids)) or any(value.startswith('retail:') for value in ids):
            raise ValueError('Duplicate or reserved business record ID')


class BusinessCore:
    def __init__(self, storage, tenant):
        self.storage, self.tenant = storage, tenant
        if not storage.tenant_exists(tenant):
            raise BusinessError('not_found','Business does not exist.')

    def read(self, filename, default):
        try:
            return self.storage.read_json(self.tenant, filename)
        except FileNotFoundError:
            return copy.deepcopy(default)

    def document(self):
        document = self.read('business_core.json', empty_core())
        validate_core(document)
        return document

    def offerings(self):
        core = self.document()
        rows = [{**item, 'source':'business_core', 'revision':revision(core)} for item in core['offerings']]
        catalog = self.read('catalog.json', {})
        for category in catalog.get('product_catalog', catalog.get('categories', [])):
            for item in category['items']:
                # Never parse a legacy display price into a fabricated fixed price.
                record = {'id':'retail:'+revision([category['name'],item['name']]),
                          'name':item['name'],'category':category['name'],'type':'product',
                          'price_type':'fixed' if 'price' in item else 'quote',
                          'active':True,'source':'catalog','revision':revision(catalog),
                          'in_stock':item.get('in_stock',True)}
                for key in ('price','price_str','sku','stock','unit'):
                    if key in item:
                        record[key] = item[key]
                if 'currency' in catalog:
                    record['currency'] = catalog['currency']
                rows.append(record)
        return rows

    def locations(self):
        rows = list(self.document()['locations'])
        for branch in self.read('branches.json', []):
            rows.append({'id':'retail:'+str(branch['id']),'type':'store','active':True,
                         **{k:v for k,v in branch.items() if k in {'name','address','postcode','phone','hours','lat','lon'}}})
        return rows

    def get(self, name, args):
        if name in {'get_offerings','get_offering'}:
            rows = self.offerings()
            if name == 'get_offering':
                rows = [row for row in rows if row['id'] == args['offering_id']]
                if len(rows) != 1:
                    raise BusinessError('not_found','Offering does not exist.')
                return rows[0]
        elif name in {'get_locations','get_service_areas'}:
            rows = self.locations()
            if name == 'get_service_areas':
                rows = [row for row in rows if row['type'] in {'mobile_service_area','remote_only'} or row.get('service_area')]
        elif name == 'get_business_rules':
            rows = self.document()['business_rules']
        else:
            kind = name.removeprefix('get_').removesuffix('s')
            rows = [row for row in self.document()['work'] if row['type'] == kind]
        offset, limit = args.get('offset',0), args.get('limit',50)
        return {'items':rows[offset:offset+limit], 'total':len(rows),
                'revision':revision(self.document()),
                'next_offset':offset+limit if offset+limit<len(rows) else None}

    def public_context(self):
        """Only customer-facing facts. Work, accounts and analytics are private."""
        core = self.document()
        return {'industry':core.get('industry',''), 'operation_types':core.get('operation_types',[]),
                'offerings':[row for row in core['offerings'] if row['active']][:50],
                'locations':[row for row in core['locations'] if row['active']][:30],
                'business_rules':[row for row in core['business_rules'] if row['active']][:50]}

    def answer(self, text):
        """Grounded local answers for configured generic facts; no booking execution."""
        context = self.public_context()
        words = set(re.findall(r'[a-z0-9]+', text.casefold()))
        if not words:
            return None
        offerings = context['offerings']
        browse = bool(words & {'services','offerings','packages','subscriptions'})
        matches = [row for row in offerings if browse or len(words & set(row['name'].casefold().split())) >= 1]
        lines = []
        for row in matches[:8]:
            price = 'Quote required'
            if 'price' in row and row['price_type'] != 'quote':
                price = f"{row.get('currency','')} {row['price']:g}".strip()
                if row['price_type'] == 'from': price = 'From '+price
                elif row['price_type'].startswith('per_'): price += ' '+row['price_type'].replace('_',' ')
            elif row['price_type'].startswith('per_'):
                price = 'Priced '+row['price_type'].replace('_',' ')+'; ask the team for a quote'
            line = row['name']+' — '+price
            if row.get('duration_minutes'): line += f"; {row['duration_minutes']} minutes"
            if row.get('description'): line += '; '+row['description']
            lines.append(line)
        if words & {'location','locations','where','area','areas','remote','mobile','office','workshop','hours','opening'}:
            for row in context['locations'][:8]:
                lines.append(row['name']+' — '+row['type'].replace('_',' ')+((': '+row['service_area']) if row.get('service_area') else '')+(('; '+row['address']) if row.get('address') else '')+(f"; radius {row['radius_miles']:g} miles" if 'radius_miles' in row else ''))
                if row.get('hours'):
                    lines.append('Hours: '+', '.join(day+': '+hours for day,hours in row['hours'].items()))
        for rule in context['business_rules']:
            if matches or words & set((rule['title']+' '+rule['description']).casefold().split()) - {'a','the','is','for','to','of','and','in','i','do','you'}:
                lines.append(rule['description']+(' The team must review this before confirming.' if rule.get('requires_manual_review') else ''))
        if lines:
            return '\n'.join(lines)+'\nThe team can confirm a quote or arrange the next step. No booking or payment has been made.'
        return None
