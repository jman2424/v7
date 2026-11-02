"""Private AI Budget control records; usage_wallet remains the only money ledger."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import secrets
import time

from service import session_store, subscriptions

TENANT_TABLES = {
    'ai_budget_settings': '''CREATE TABLE IF NOT EXISTS ai_budget_settings (
        tenant TEXT PRIMARY KEY, revision BIGINT NOT NULL DEFAULT 1,
        recharge_enabled INTEGER NOT NULL DEFAULT 0 CHECK(recharge_enabled IN(0,1)),
        recharge_cap_pence BIGINT NOT NULL DEFAULT 2500 CHECK(recharge_cap_pence IN(2500,5000,10000)),
        authorisation TEXT NOT NULL DEFAULT '', blocked_reason TEXT NOT NULL DEFAULT '',
        alerts_enabled INTEGER NOT NULL DEFAULT 1 CHECK(alerts_enabled IN(0,1)),
        email_alerts INTEGER NOT NULL DEFAULT 0 CHECK(email_alerts IN(0,1)),
        alert_threshold_pence BIGINT NOT NULL DEFAULT 200 CHECK(alert_threshold_pence IN(200,500,1000)),
        low_state INTEGER NOT NULL DEFAULT 0 CHECK(low_state IN(0,1)), alert_epoch BIGINT NOT NULL DEFAULT 0,
        observed_balance_nano BIGINT, initial_pack TEXT NOT NULL DEFAULT '', fees_check_after DOUBLE PRECISION NOT NULL DEFAULT 0,
        updated DOUBLE PRECISION NOT NULL)''',
    'ai_budget_authorisations': '''CREATE TABLE IF NOT EXISTS ai_budget_authorisations (
        id TEXT PRIMARY KEY, tenant TEXT NOT NULL, revision BIGINT NOT NULL, request_id TEXT NOT NULL,
        actor TEXT NOT NULL, actor_revision TEXT NOT NULL, consent_terms TEXT NOT NULL, cap_pence BIGINT NOT NULL,
        customer TEXT NOT NULL DEFAULT '', checkout TEXT UNIQUE, checkout_url TEXT NOT NULL DEFAULT '',
        setup_intent TEXT UNIQUE, payment_method TEXT NOT NULL DEFAULT '',
        livemode INTEGER NOT NULL CHECK(livemode IN(0,1)),
        status TEXT NOT NULL CHECK(status IN('pending','active','revoked','failed')),
        created DOUBLE PRECISION NOT NULL, updated DOUBLE PRECISION NOT NULL,
        UNIQUE(tenant,revision), UNIQUE(tenant,id), UNIQUE(tenant,request_id))''',
    'ai_budget_recharges': '''CREATE TABLE IF NOT EXISTS ai_budget_recharges (
        reference TEXT PRIMARY KEY, tenant TEXT NOT NULL, authorisation TEXT NOT NULL,
        month TEXT NOT NULL, amount_pence BIGINT NOT NULL CHECK(amount_pence=500),
        credit_pence BIGINT NOT NULL CHECK(credit_pence=500),
        subtotal_pence BIGINT NOT NULL, tax_pence BIGINT NOT NULL, vat_percent INTEGER NOT NULL,
        customer TEXT NOT NULL, payment_method TEXT NOT NULL, livemode INTEGER NOT NULL CHECK(livemode IN(0,1)),
        payment_id TEXT UNIQUE, charge_id TEXT UNIQUE,
        status TEXT NOT NULL CHECK(status IN('reserved','dispatching','processing','succeeded','failed','requires_action','cancelled','unknown')),
        failure_code TEXT NOT NULL DEFAULT '', attempts INTEGER NOT NULL DEFAULT 0,
        lease_until DOUBLE PRECISION NOT NULL DEFAULT 0, created DOUBLE PRECISION NOT NULL,
        updated DOUBLE PRECISION NOT NULL, CHECK(subtotal_pence+tax_pence=amount_pence),
        FOREIGN KEY(tenant,authorisation) REFERENCES ai_budget_authorisations(tenant,id))''',
    'ai_budget_notifications': '''CREATE TABLE IF NOT EXISTS ai_budget_notifications (
        id TEXT PRIMARY KEY, tenant TEXT NOT NULL, kind TEXT NOT NULL, event_key TEXT NOT NULL,
        payload TEXT NOT NULL, email_enabled INTEGER NOT NULL CHECK(email_enabled IN(0,1)),
        state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN('pending','sending','sent','dashboard_only','needs_review')),
        seen INTEGER NOT NULL DEFAULT 0 CHECK(seen IN(0,1)), attempts INTEGER NOT NULL DEFAULT 0,
        available DOUBLE PRECISION NOT NULL, created DOUBLE PRECISION NOT NULL,
        UNIQUE(tenant,event_key))''',
    'ai_budget_events': '''CREATE TABLE IF NOT EXISTS ai_budget_events (
        id TEXT PRIMARY KEY, tenant TEXT NOT NULL, kind TEXT NOT NULL, actor TEXT NOT NULL,
        details TEXT NOT NULL, created DOUBLE PRECISION NOT NULL)''',
    'ai_budget_payment_costs': '''CREATE TABLE IF NOT EXISTS ai_budget_payment_costs (
        tenant TEXT NOT NULL, payment_id TEXT NOT NULL, balance_transaction TEXT NOT NULL,
        currency TEXT NOT NULL, gross_pence BIGINT NOT NULL, fee_pence BIGINT NOT NULL,
        net_pence BIGINT NOT NULL, fee_details TEXT NOT NULL, observed DOUBLE PRECISION NOT NULL,
        PRIMARY KEY(tenant,payment_id), CHECK(gross_pence-fee_pence=net_pence))''',
}
PLATFORM_TABLES = {
    # Private worker discovery metadata only. Financial rows remain tenant-scoped.
    'ai_budget_work_tenants': '''CREATE TABLE IF NOT EXISTS ai_budget_work_tenants (
        tenant TEXT PRIMARY KEY)''',
    'ai_provider_limit_snapshots': '''CREATE TABLE IF NOT EXISTS ai_provider_limit_snapshots (
        scope TEXT PRIMARY KEY, value TEXT NOT NULL, observed DOUBLE PRECISION NOT NULL)''',
    'ai_provider_funding_settings': '''CREATE TABLE IF NOT EXISTS ai_provider_funding_settings (
        id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL, updated DOUBLE PRECISION NOT NULL)''',
    'ai_provider_health': '''CREATE TABLE IF NOT EXISTS ai_provider_health (
        id INTEGER PRIMARY KEY CHECK(id=1), status TEXT NOT NULL, error_code TEXT NOT NULL DEFAULT '',
        observed DOUBLE PRECISION NOT NULL, retry_after DOUBLE PRECISION NOT NULL DEFAULT 0)''',
    'ai_provider_cost_snapshots': '''CREATE TABLE IF NOT EXISTS ai_provider_cost_snapshots (
        id TEXT PRIMARY KEY, start_utc BIGINT NOT NULL, end_utc BIGINT NOT NULL,
        source TEXT NOT NULL, currency TEXT NOT NULL, amount_decimal TEXT NOT NULL,
        project_id TEXT NOT NULL DEFAULT '', observed DOUBLE PRECISION NOT NULL,
        UNIQUE(start_utc,end_utc,source,currency,project_id))''',
}
INDEXES = (
    'CREATE INDEX IF NOT EXISTS ai_budget_auth_tenant ON ai_budget_authorisations(tenant,status,created)',
    'CREATE INDEX IF NOT EXISTS ai_budget_recharge_month ON ai_budget_recharges(tenant,month,status)',
    "CREATE UNIQUE INDEX IF NOT EXISTS ai_budget_one_open_recharge ON ai_budget_recharges(tenant) WHERE status IN('reserved','dispatching','processing','requires_action','unknown')",
    'CREATE INDEX IF NOT EXISTS ai_budget_recharge_work ON ai_budget_recharges(tenant,status,lease_until)',
    'CREATE INDEX IF NOT EXISTS ai_budget_notice_queue ON ai_budget_notifications(tenant,state,available)',
    'CREATE INDEX IF NOT EXISTS ai_budget_events_tenant ON ai_budget_events(tenant,created)',
)


def schema(db):
    if session_store._using_postgres():
        return
    for statement in (*TENANT_TABLES.values(), *PLATFORM_TABLES.values(), *INDEXES):
        db.execute(statement)
    for operation in ('UPDATE', 'DELETE'):
        db.execute(f"CREATE TRIGGER IF NOT EXISTS ai_budget_events_no_{operation.lower()} BEFORE {operation} ON ai_budget_events BEGIN SELECT RAISE(ABORT,'immutable_budget_audit'); END")


@contextmanager
def connection(tenant, *, write=False, operator=False):
    with subscriptions.connection(tenant) as db:
        if write:
            if session_store._using_postgres():
                key = int.from_bytes(hashlib.sha256(('ai_budget:'+tenant).encode()).digest()[:8], 'big', signed=True)
                db.execute('SELECT pg_advisory_xact_lock(?)', (key,))
            else:
                db.execute('BEGIN IMMEDIATE')
        schema(db)
        if operator and session_store._using_postgres():
            from flask import session
            db.execute("SELECT set_config('v7.application_session',?,true)", (session_store._digest(session.get('management_token', '')),))
        yield db


def ensure_settings(db, tenant):
    suffix=' FOR UPDATE' if session_store._using_postgres() else ''
    row=db.execute('SELECT * FROM ai_budget_settings WHERE tenant=?'+suffix,(tenant,)).fetchone()
    if row:
        return dict(row)
    db.execute('INSERT INTO ai_budget_settings(tenant,updated) VALUES (?,?) ON CONFLICT(tenant) DO NOTHING', (tenant,time.time()))
    db.execute('INSERT INTO ai_budget_work_tenants(tenant) VALUES (?) ON CONFLICT(tenant) DO NOTHING',(tenant,))
    return dict(db.execute('SELECT * FROM ai_budget_settings WHERE tenant=?'+suffix, (tenant,)).fetchone())


def settings(tenant, db=None):
    if db is None:
        with connection(tenant) as handle:
            return settings(tenant, handle)
    row = db.execute('SELECT * FROM ai_budget_settings WHERE tenant=?', (tenant,)).fetchone()
    return dict(row) if row else {'tenant':tenant, 'revision':0, 'recharge_enabled':0,
        'recharge_cap_pence':2500, 'authorisation':'', 'blocked_reason':'', 'alerts_enabled':1,
        'email_alerts':0, 'alert_threshold_pence':200, 'low_state':0, 'alert_epoch':0,
        'observed_balance_nano':None, 'initial_pack':''}


def audit(db, tenant, kind, actor, details):
    db.execute('INSERT INTO ai_budget_events VALUES (?,?,?,?,?,?)',
        (secrets.token_hex(16), tenant, kind, actor, json.dumps(details,sort_keys=True,allow_nan=False),time.time()))


def notify(db, tenant, kind, event_key, payload, *, email=False):
    db.execute('INSERT INTO ai_budget_notifications(id,tenant,kind,event_key,payload,email_enabled,available,created) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(tenant,event_key) DO NOTHING',
        (secrets.token_hex(16),tenant,kind,event_key,json.dumps(payload,sort_keys=True,allow_nan=False),int(email),time.time(),time.time()))


def month_key(now=None):
    return datetime.fromtimestamp(time.time() if now is None else now,timezone.utc).strftime('%Y-%m')


def monthly_reserved(db, tenant, month=None):
    return int(db.execute("SELECT COALESCE(SUM(amount_pence),0) AS total FROM ai_budget_recharges WHERE tenant=? AND month=? AND status NOT IN('failed','cancelled')",
        (tenant, month or month_key())).fetchone()['total'])
