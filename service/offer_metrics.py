"""Offer terms and tenant-scoped engagement, never inferred redemptions."""
from datetime import datetime, timezone


def deal_terms(offer: dict) -> str:
    if offer.get('deal_type') == 'buy_one_get_one':
        return 'Buy 1 eligible item and get 1 of the same item free'
    if offer.get('deal_type') == 'minimum_spend':
        reward = (f"{offer['discount_value']:g}%" if offer.get('discount_type') == 'percentage'
                  else f"GBP {offer['discount_value']:.2f}")
        scope = ' on eligible items' if offer.get('product_skus') else ''
        return f"Spend at least GBP {offer['minimum_spend']:.2f}{scope} and get {reward} off those items"
    return ''


def offer_status(offer: dict, today: str) -> str:
    if offer.get('archived'):
        return 'archived'
    if offer.get('ends_on') and offer['ends_on'] < today:
        return 'expired'
    if not offer.get('active'):
        return 'paused'
    if offer.get('starts_on') and offer['starts_on'] > today:
        return 'scheduled'
    return 'active'


def shown_offers(result: dict) -> list[str] | None:
    if result.get('intent') != 'offers':
        return None
    items = (result.get('facts') or {}).get('offers', {}).get('items', [])
    reply = result.get('reply', '')
    return list(dict.fromkeys(item['id'] for item in items[:3]
                             if item.get('id') and item.get('title') and item['title'] in reply))


def offer_report(db, tenant, start, end, channel, offers, *, postgres=False):
    from service import analytics_db
    placeholder = '%s' if postgres else '?'
    events = 'v7_private.events' if postgres else 'events'
    condition = f"e.tenant={placeholder} AND e.ts_utc>={placeholder} AND e.ts_utc<{placeholder} AND e.event_type='msg_out' AND e.intent='offers'"
    values = (tenant if postgres else tenant.upper(), start.isoformat(), end.isoformat())
    if channel != 'all':
        condition += f' AND e.channel={placeholder}'
        values += (channel,)
    # Only new, explicitly tracked offer IDs are attributed. Never guess from old text.
    if postgres:
        meta = "(CASE WHEN pg_input_is_valid(e.meta_json, 'jsonb') THEN e.meta_json::jsonb ELSE '{}'::jsonb END)"
        offers_json = f"CASE WHEN jsonb_typeof({meta}->'offers')='array' THEN {meta}->'offers' ELSE '[]'::jsonb END"
        offer_source = f"{events} e CROSS JOIN LATERAL jsonb_array_elements({offers_json}) j(value)"
        offer_id = "j.value #>> '{}'"
        offer_type = "jsonb_typeof(j.value)='string'"
    else:
        offer_source = f"{events} e, json_each(CASE WHEN json_valid(e.meta_json) THEN e.meta_json ELSE '{{}}' END, '$.offers') j"
        offer_id = 'j.value'
        offer_type = "j.type='text'"
    def read_rows(sql):
        if postgres:
            return analytics_db._pg_rows(db, sql, values)
        return [dict(row) for row in db.execute(sql, values)]
    rows = read_rows(f"""SELECT {offer_id} AS id, COUNT(DISTINCT e.id) AS replies,
        COUNT(DISTINCT CASE WHEN e.session_id!='' THEN e.channel || ':' || e.session_id END) AS conversations
        FROM {offer_source}
        WHERE {condition} AND {offer_type} GROUP BY j.value ORDER BY replies DESC, j.value LIMIT 500""")
    counts = {row['id']: dict(row) for row in rows}
    today = datetime.now(timezone.utc).date().isoformat()
    items = []
    for offer in offers:
        count = counts.pop(offer['id'], {'replies': 0, 'conversations': 0})
        items.append({'id': offer['id'], 'title': offer['title'], 'status': offer_status(offer, today),
                      'deal_type': offer.get('deal_type', 'custom'), 'terms': deal_terms(offer),
                      'replies': count['replies'], 'conversations': count['conversations']})
    items.extend({**row, 'title': row['id'], 'status': 'removed', 'deal_type': 'custom', 'terms': ''}
                 for row in counts.values())
    totals = read_rows(f"SELECT COUNT(*) AS offer_replies, COUNT(DISTINCT CASE WHEN e.session_id!='' THEN e.channel || ':' || e.session_id END) AS conversations FROM {events} e WHERE {condition}")[0]
    return {'items': items, **totals}
