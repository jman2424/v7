"""Catalogue-backed interest, owner-recorded sales and inventory history."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re

from service import analytics_db, session_store


def catalogue_items(catalog: dict) -> list[dict]:
    return [item for category in catalog.get('categories', []) for item in category.get('items', [])]


def matched_products(result: dict) -> list[str] | None:
    # Count products returned for a product enquiry, not unsolicited suggestions.
    if result.get('intent') not in {'search_product', 'price_check', 'compare_products', 'browse_category'}:
        return None
    items = result.get('items')
    if not isinstance(items, list):
        return []
    return list(dict.fromkeys(str(item['sku']) for item in items
                             if isinstance(item, dict) and item.get('sku')))[:100]


def init_tables(db) -> None:
    db.execute('''CREATE TABLE IF NOT EXISTS recorded_sales (
        tenant TEXT NOT NULL, id TEXT NOT NULL, sku TEXT NOT NULL, name TEXT NOT NULL,
        quantity REAL NOT NULL CHECK(quantity>0), amount_pence INTEGER NOT NULL CHECK(amount_pence>=0),
        occurred_utc TEXT NOT NULL, channel TEXT NOT NULL, created_utc TEXT NOT NULL,
        voided_utc TEXT, PRIMARY KEY(tenant,id))''')
    db.execute('CREATE INDEX IF NOT EXISTS idx_recorded_sales_tenant_time ON recorded_sales(tenant,occurred_utc)')
    db.execute('''CREATE TABLE IF NOT EXISTS inventory_history (
        id INTEGER PRIMARY KEY, tenant TEXT NOT NULL, sku TEXT NOT NULL, ts_utc TEXT NOT NULL,
        quantity REAL, threshold REAL NOT NULL, in_stock INTEGER NOT NULL)''')
    db.execute('CREATE INDEX IF NOT EXISTS idx_inventory_history_tenant_sku_time ON inventory_history(tenant,sku,ts_utc)')


def record_inventory(tenant: str, before: dict, after: dict) -> None:
    """Snapshot changed quantities only; never fabricate earlier inventory levels."""
    analytics_db._ensure_ready()
    previous = {item['sku']: item for item in catalogue_items(before)}
    if session_store._using_postgres():
        tenant_key = analytics_db._norm_tenant(tenant)
        with session_store.postgres_connection(tenant_key) as db:
            for item in catalogue_items(after):
                old = previous.get(item['sku'], {})
                fields = ('stock_quantity', 'low_stock_threshold', 'in_stock')
                recorded = db.execute(
                    'SELECT 1 FROM v7_private.inventory_history WHERE tenant=%s AND sku=%s LIMIT 1',
                    (tenant_key, item['sku']),
                ).fetchone()
                if recorded and all(old.get(key) == item.get(key) for key in fields):
                    continue
                db.execute(
                    'INSERT INTO v7_private.inventory_history '
                    '(tenant,sku,ts_utc,quantity,threshold,in_stock) VALUES (%s,%s,%s,%s,%s,%s)',
                    (tenant_key, item['sku'], analytics_db._utc_now(),
                     item.get('stock_quantity'), item.get('low_stock_threshold', 5),
                     int(item.get('in_stock', True))),
                )
        return
    with analytics_db._conn() as db:
        init_tables(db)
        for item in catalogue_items(after):
            old = previous.get(item['sku'], {})
            fields = ('stock_quantity', 'low_stock_threshold', 'in_stock')
            recorded = db.execute('SELECT 1 FROM inventory_history WHERE tenant=? AND sku=? LIMIT 1',
                                  (tenant.upper(), item['sku'])).fetchone()
            if recorded and all(old.get(key) == item.get(key) for key in fields):
                continue
            db.execute('INSERT INTO inventory_history(tenant,sku,ts_utc,quantity,threshold,in_stock) VALUES(?,?,?,?,?,?)',
                       (tenant.upper(), item['sku'], analytics_db._utc_now(), item.get('stock_quantity'),
                        item.get('low_stock_threshold', 5), int(item.get('in_stock', True))))


def record_sale(tenant: str, data: dict, catalog: dict) -> dict:
    sale_id = data.get('id', '')
    if not isinstance(sale_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{16,80}', sale_id):
        raise ValueError('Invalid sale reference. Reload and try again.')
    item = next((item for item in catalogue_items(catalog) if item['sku'] == data.get('sku')), None)
    if item is None:
        raise ValueError('Choose a product from this company’s catalogue.')
    try:
        quantity = Decimal(str(data.get('quantity')))
        amount = Decimal(str(data.get('amount_gbp')))
        if not quantity.is_finite() or not amount.is_finite() or not 0 < quantity <= 1000000 or not 0 <= amount <= 10000000:
            raise ValueError
        if quantity.as_tuple().exponent < -3 or amount.as_tuple().exponent < -2:
            raise ValueError
        occurred = datetime.fromisoformat(str(data.get('occurred_utc')).replace('Z', '+00:00'))
        if occurred.tzinfo is None or occurred > datetime.now(timezone.utc) or occurred.year < 2000:
            raise ValueError
    except (ValueError, InvalidOperation, TypeError):
        raise ValueError('Enter a past sale date, positive quantity (up to 3 decimals) and GBP total (up to 2 decimals).') from None
    channel = data.get('channel')
    if channel not in {'web', 'whatsapp', 'offline'}:
        raise ValueError('Choose web, WhatsApp or offline sales.')
    row = (analytics_db._norm_tenant(tenant), sale_id, item['sku'], item['name'], float(quantity), int(amount * 100),
           occurred.astimezone(timezone.utc).isoformat(), channel)
    analytics_db._ensure_ready()
    if session_store._using_postgres():
        from psycopg.rows import dict_row
        with session_store.postgres_connection(row[0]) as db:
            inserted = db.execute(
                'INSERT INTO v7_private.recorded_sales '
                '(tenant,id,sku,name,quantity,amount_pence,occurred_utc,channel,created_utc) '
                'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) '
                'ON CONFLICT (tenant,id) DO NOTHING RETURNING id',
                (*row, analytics_db._utc_now()),
            ).fetchone()
            if inserted:
                return {'id': sale_id, 'duplicate': False}
            with db.cursor(row_factory=dict_row) as cursor:
                previous = cursor.execute(
                    'SELECT * FROM v7_private.recorded_sales WHERE tenant=%s AND id=%s',
                    row[:2],
                ).fetchone()
            fields = ('tenant','id','sku','name','quantity','amount_pence','occurred_utc','channel')
            if previous is None or tuple(previous[key] for key in fields) != row or previous['voided_utc']:
                raise ValueError('This sale reference was already used. Refresh before recording another sale.')
            return {'id': sale_id, 'duplicate': True}
    with analytics_db._conn() as db:
        init_tables(db)
        db.execute('BEGIN IMMEDIATE')
        previous = db.execute('SELECT * FROM recorded_sales WHERE tenant=? AND id=?', row[:2]).fetchone()
        if previous:
            fields = ('tenant','id','sku','name','quantity','amount_pence','occurred_utc','channel')
            if tuple(previous[key] for key in fields) != row or previous['voided_utc']:
                raise ValueError('This sale reference was already used. Refresh before recording another sale.')
            return {'id': sale_id, 'duplicate': True}
        db.execute('INSERT INTO recorded_sales(tenant,id,sku,name,quantity,amount_pence,occurred_utc,channel,created_utc) VALUES(?,?,?,?,?,?,?,?,?)',
                   (*row, analytics_db._utc_now()))
    return {'id': sale_id, 'duplicate': False}


def void_sale(tenant: str, sale_id: str) -> bool:
    analytics_db._ensure_ready()
    if session_store._using_postgres():
        with session_store.postgres_connection(tenant) as db:
            return db.execute(
                'UPDATE v7_private.recorded_sales SET voided_utc=COALESCE(voided_utc,%s) '
                'WHERE tenant=%s AND id=%s',
                (analytics_db._utc_now(), tenant, sale_id),
            ).rowcount == 1
    with analytics_db._conn() as db:
        init_tables(db)
        return db.execute('UPDATE recorded_sales SET voided_utc=COALESCE(voided_utc,?) WHERE tenant=? AND id=?',
                          (analytics_db._utc_now(), tenant.upper(), sale_id)).rowcount == 1


def product_report(db, tenant: str, start: str, end: str, channel: str, catalog: dict, *, postgres=False) -> dict:
    items = {item['sku']: item for item in catalogue_items(catalog)}
    products = {sku: {'sku':sku, 'name':item['name'], 'unit':item.get('unit','each'),
                     'interest':0, 'units':0, 'amount_pence':0, 'quantity':item.get('stock_quantity'),
                     'threshold':item.get('low_stock_threshold',5), 'available':item.get('in_stock',True), 'archived':False}
                for sku,item in items.items()}
    tenant_key = tenant if postgres else tenant.upper()
    values = (tenant_key, start, end)
    placeholder = '%s' if postgres else '?'
    events = 'v7_private.events' if postgres else 'events'
    recorded_sales = 'v7_private.recorded_sales' if postgres else 'recorded_sales'
    inventory_history = 'v7_private.inventory_history' if postgres else 'inventory_history'
    event_filter = f"e.tenant={placeholder} AND e.ts_utc>={placeholder} AND e.ts_utc<{placeholder} AND e.event_type='msg_out'"
    sales_filter = f'tenant={placeholder} AND occurred_utc>={placeholder} AND occurred_utc<{placeholder} AND voided_utc IS NULL'
    if channel != 'all':
        event_filter += f' AND e.channel={placeholder}'
        sales_filter += f' AND channel={placeholder}'
        values += (channel,)
    def rows(query, parameters=values):
        if postgres:
            return analytics_db._pg_rows(db, query, parameters)
        return [dict(row) for row in db.execute(query, parameters)]
    if postgres:
        meta = "(CASE WHEN pg_input_is_valid(e.meta_json, 'jsonb') THEN e.meta_json::jsonb ELSE '{}'::jsonb END)"
        products_json = f"CASE WHEN jsonb_typeof({meta}->'products')='array' THEN {meta}->'products' ELSE '[]'::jsonb END"
        product_source = f"{events} e CROSS JOIN LATERAL jsonb_array_elements({products_json}) p(value)"
        sku_expression = "p.value #>> '{}'"
        product_type = "jsonb_typeof(p.value)='string'"
    else:
        product_source = f"{events} e, json_each(CASE WHEN json_valid(e.meta_json) THEN e.meta_json ELSE '{{}}' END, '$.products') p"
        sku_expression = 'p.value'
        product_type = "p.type='text'"
    interest = rows(f'''SELECT substr(e.ts_utc,1,10) AS day, {sku_expression} AS sku, COUNT(*) AS count
        FROM {product_source} WHERE {event_filter} AND {product_type} GROUP BY day,sku''')
    sales = rows(f'''SELECT substr(occurred_utc,1,10) AS day,sku,MAX(name) AS name,
        SUM(quantity) AS units,SUM(amount_pence) AS amount_pence,COUNT(*) AS entries
        FROM {recorded_sales} WHERE {sales_filter} GROUP BY day,sku''')
    if postgres:
        for row in sales:
            row['amount_pence'] = int(row['amount_pence'])
    for row in interest + sales:
        sku = row['sku']
        if sku not in products:
            products[sku] = {'sku':sku,'name':row.get('name',sku)+' (removed)', 'unit':'recorded units',
                             'interest':0,'units':0,'amount_pence':0,'quantity':None,'threshold':5,'available':False,'archived':True}
        products[sku]['interest'] += row.get('count',0)
        products[sku]['units'] += row.get('units',0)
        products[sku]['amount_pence'] += row.get('amount_pence',0)
    # Include the last known level before the window, without assuming it existed earlier.
    inventory = rows(f'''SELECT sku,ts_utc,quantity,threshold,in_stock FROM {inventory_history} h
        WHERE tenant={placeholder} AND ts_utc<{placeholder} AND (ts_utc>={placeholder} OR id=(SELECT h2.id FROM {inventory_history} h2
        WHERE h2.tenant=h.tenant AND h2.sku=h.sku AND h2.ts_utc<{placeholder} ORDER BY h2.ts_utc DESC,h2.id DESC LIMIT 1))
        ORDER BY ts_utc,id''', (tenant_key,end,start,start))
    recent = rows(f'''SELECT id,sku,name,quantity,amount_pence,occurred_utc,channel
        FROM {recorded_sales} WHERE {sales_filter} ORDER BY occurred_utc DESC,id LIMIT 30''')
    tracking_filter = (f"jsonb_typeof({meta}->'products')='array'" if postgres else
                       "json_type(CASE WHEN json_valid(e.meta_json) THEN e.meta_json ELSE '{}' END,'$.products')='array'")
    first = rows(f"SELECT MIN(ts_utc) AS first FROM {events} e WHERE tenant={placeholder} AND {tracking_filter}", (tenant_key,))[0]['first']
    return {'products':list(products.values()),'interest_daily':interest,'sales_daily':sales,
            'inventory':inventory,'recent_sales':recent,'interest_tracking_since':first}
