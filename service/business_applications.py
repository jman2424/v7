"""Manual commercial eligibility, distinct from account and staff-join approval.

No model or customer-controlled field can make an eligibility decision. Payment
permits make checkout creation durable before any provider side effect; unresolved
permits prevent revocation or material edits while payment remains possible.
"""
from __future__ import annotations

import json
import hashlib
import secrets
import time
from contextlib import contextmanager
from urllib.parse import urlsplit

from service import session_store
from service.account_service import valid_account_email
from service.plan_catalog import get_plan

STATES = ('PENDING_REVIEW', 'NEEDS_INFORMATION', 'APPROVED', 'REJECTED', 'EXPIRED', 'CANCELLED')
DEFAULT_POLICY = (
    'Vertex Seven reviews applications according to the business activities and the intended use of its services. '
    'Businesses primarily offering alcohol sales, gambling or pornographic services are outside the proposed service policy. '
    'Mixed activities are reviewed individually. Approval of a business does not authorise every agent action: '
    'separate permissions, consent and approval requirements still apply. '
    'Decisions must not be based on an owner’s protected personal characteristics. '
    'Applicants may correct information or request reconsideration through their signed-in application page.'
)
DEFAULT_SETTINGS = {
    'revision': 1, 'intake_enabled': False, 'research_enabled': False,
    'guidance': 'Apply once. We review your business before you can pay. No payment is taken with your application.',
    'policy': DEFAULT_POLICY, 'policy_version': 'draft-1', 'legal_review_completed': False,
    'categories': {'general': ['Retail and professional services'],
                   'closer_review': ['Mixed activities; review individually'],
                   'excluded': ['Primary alcohol sales', 'Gambling', 'Pornographic services']},
    'owner_email_enabled': True, 'owner_email': '', 'retention_days': 180,
}


class ApplicationError(ValueError):
    """Only reviewed codes and HTTP statuses cross the API boundary."""
    def __init__(self, code, status=400):
        super().__init__(code)
        self.code, self.status = code, status


def _execute(db, sql, params=()):
    return db.execute(sql.replace('?', '%s') if session_store._using_postgres() else sql, params)


def _one(cursor):
    row = cursor.fetchone()
    return dict(zip((column[0] for column in cursor.description), row)) if row is not None else None


def _rows(cursor):
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def schema(db):
    if session_store._using_postgres():
        return
    db.execute('''CREATE TABLE IF NOT EXISTS business_applications (
        tenant TEXT PRIMARY KEY, status TEXT NOT NULL CHECK(status IN
        ('PENDING_REVIEW','NEEDS_INFORMATION','APPROVED','REJECTED','EXPIRED','CANCELLED')),
        revision INTEGER NOT NULL, details TEXT NOT NULL, contact_email TEXT NOT NULL,
        policy_version TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
        public_message TEXT NOT NULL DEFAULT '', service_preserved INTEGER NOT NULL DEFAULT 0,
        research TEXT NOT NULL DEFAULT '{}')''')
    db.execute('CREATE INDEX IF NOT EXISTS business_application_queue ON business_applications(status,created)')
    db.execute('''CREATE TABLE IF NOT EXISTS business_application_events (
        id TEXT PRIMARY KEY, tenant TEXT NOT NULL, revision INTEGER NOT NULL,
        kind TEXT NOT NULL, actor TEXT NOT NULL, note TEXT NOT NULL, created REAL NOT NULL)''')
    db.execute('CREATE INDEX IF NOT EXISTS business_application_history ON business_application_events(tenant,created)')
    db.execute('''CREATE TABLE IF NOT EXISTS business_application_settings (
        id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS business_application_permits (
        reference TEXT PRIMARY KEY, tenant TEXT NOT NULL, revision INTEGER NOT NULL,
        kind TEXT NOT NULL, state TEXT NOT NULL, checkout TEXT, created REAL NOT NULL)''')
    db.execute('CREATE INDEX IF NOT EXISTS business_application_open_payments ON business_application_permits(tenant,state)')
    db.execute('''CREATE TABLE IF NOT EXISTS business_application_notifications (
        id TEXT PRIMARY KEY, tenant TEXT NOT NULL, payload TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
        available REAL NOT NULL, created REAL NOT NULL)''')
    db.execute('CREATE INDEX IF NOT EXISTS business_application_mail_queue ON business_application_notifications(state,available)')
    db.execute('CREATE INDEX IF NOT EXISTS business_application_mail_created ON business_application_notifications(created)')


@contextmanager
def database(tenant=None, *, write=False, operator=False):
    factory = session_store.postgres_connection(tenant) if session_store._using_postgres() else session_store.connection()
    with factory as db:
        schema(db)
        if session_store._using_postgres():
            if operator:
                from flask import session
                # This hash is checked against the live server-side management
                # session by RLS; a client-supplied role or GUC is not authority.
                token = session.get('management_token', '')
                db.execute("SELECT set_config('v7.application_session',%s,true)", (session_store._digest(token),))
        elif write:
            db.execute('BEGIN IMMEDIATE')
        yield db


def _lock(db, tenant):
    if session_store._using_postgres():
        # Row locks alone cannot serialize two first INSERTs for an absent
        # application. This tenant-specific lock also covers that empty state.
        key = int.from_bytes(hashlib.sha256(('business_application:' + tenant).encode()).digest()[:8], 'big', signed=True)
        db.execute('SELECT pg_advisory_xact_lock(%s)', (key,))
    return _one(_execute(db, 'SELECT * FROM business_applications WHERE tenant=?' +
                         (' FOR UPDATE' if session_store._using_postgres() else ''), (tenant,)))


def settings(*, public=False, db=None):
    if db is None:
        with database() as connection:
            return settings(public=public, db=connection)
    row = _one(_execute(db, 'SELECT value FROM business_application_settings WHERE id=1'))
    value = json.loads(row['value']) if row else json.loads(_json(DEFAULT_SETTINGS))
    if public:
        from service.plan_catalog import public_plans
        return {**{key: value[key] for key in ('intake_enabled', 'guidance', 'policy', 'policy_version',
                                             'legal_review_completed', 'retention_days')}, 'plans': public_plans()}
    return value


def _operator():
    from service.security import management_user
    # Management sessions can only be created after the existing MFA flow.
    return management_user(platform_only=True)


def _text(value, maximum, *, required=False):
    if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise ApplicationError('invalid_application_details')
    value = value.strip()
    if required and not value:
        raise ApplicationError('invalid_application_details')
    return value


def validate_details(data, *, policy=None):
    if not isinstance(data, dict):
        raise ApplicationError('invalid_application_details')
    policy = policy or settings(public=True)
    name = _text(data.get('business_name', ''), 120, required=True)
    website = _text(data.get('website', ''), 2048)
    description = _text(data.get('description', ''), 2000, required=not website)
    if website:
        from service.website_knowledge import _validate_public_https_url, WebsiteImportError
        try:
            website = _validate_public_https_url(website)
        except (WebsiteImportError, ValueError):
            raise ApplicationError('invalid_application_website') from None
        if urlsplit(website).fragment:
            raise ApplicationError('invalid_application_website')
    try:
        plan = get_plan(data.get('plan_id'))['id']
    except ValueError:
        raise ApplicationError('invalid_subscription_plan') from None
    if data.get('accepted_terms') is not True or data.get('policy_version') != policy['policy_version']:
        raise ApplicationError('application_policy_acceptance_required')
    return {'business_name': name, 'website': website, 'description': description, 'plan_id': plan,
            'accepted_terms_version': 'application-terms-20261031'}


def _event(db, tenant, revision, kind, actor, note=''):
    _execute(db, 'INSERT INTO business_application_events VALUES (?,?,?,?,?,?,?)',
             (secrets.token_urlsafe(24), tenant, revision, kind, actor, note, time.time()))


def _notify(db, row, stage):
    policy = settings(db=db)
    detail = json.loads(row['details'])
    common = {'stage': stage, 'tenant': row['tenant'], 'revision': row['revision'], 'business_name': detail['business_name'],
              'website': detail['website'], 'plan_id': detail['plan_id'], 'submitted': row['created'],
              'public_message': row['public_message']}
    recipients = [(row['contact_email'], False)]
    if stage == 'PENDING_REVIEW' and policy['owner_email_enabled'] and policy['owner_email']:
        recipients.append((policy['owner_email'], True))
    for email, owner in recipients:
        key = f"application:{row['tenant']}:{row['revision']}:{stage}:{'owner' if owner else 'applicant'}"
        # The outbox commits with the state transition. Notes/research never
        # enter the payload. Delivery happens outside the request transaction.
        _execute(db, 'INSERT INTO business_application_notifications '
                 '(id,tenant,payload,available,created) VALUES (?,?,?,?,?) ON CONFLICT(id) DO NOTHING',
                 (key, row['tenant'], _json({**common, 'email': email, 'owner': owner}), time.time(), time.time()))
    if stage == 'PENDING_REVIEW':
        from service.application_research import enqueue
        enqueue(db, row)


def public_application(row):
    if not row:
        return None
    return {**json.loads(row['details']), **{key: row[key] for key in
            ('status', 'revision', 'created', 'updated', 'public_message', 'policy_version')},
            'contact_email': row['contact_email'], 'existing_service_preserved': bool(row['service_preserved'])}


def get(tenant, *, private=False):
    if private:
        _operator()
    with database(tenant, operator=private) as db:
        row = _one(_execute(db, 'SELECT * FROM business_applications WHERE tenant=?', (tenant,)))
        result = public_application(row)
        if result and private:
            result.update(tenant=tenant, research=json.loads(row['research']),
                          history=_rows(_execute(db, 'SELECT revision,kind,actor,note,created FROM '
                                                'business_application_events WHERE tenant=? ORDER BY created,id', (tenant,))))
        return result


def _legacy_service(tenant):
    """Recognise pre-existing entitlements, never applicant-supplied flags."""
    from service import tenant_access, subscriptions
    with tenant_access._database() as db:
        tenant_access._schema(db)
        managed = tenant_access._execute(db, 'SELECT owner FROM managed_businesses WHERE tenant=?', (tenant,)).fetchone()
    if not managed:
        # Only legacy, unregistered workspaces; every new TenantService creation
        # and verified signup reserves managed_businesses server-side.
        return True
    from flask import current_app, has_app_context
    if (has_app_context() and managed[0] is None and
            tenant == getattr(getattr(current_app.container, 'settings', None), 'PLATFORM_MARKETING_TENANT', '')):
        return True
    if subscriptions.complimentary_plan(tenant):
        return True
    with subscriptions.connection(tenant) as db:
        return bool(db.execute("SELECT 1 FROM billing_invoices WHERE tenant=? AND status='paid' AND paid>0 LIMIT 1", (tenant,)).fetchone())


def require_eligible(tenant, *, activation=False):
    with database(tenant) as db:
        row = _one(_execute(db, 'SELECT status,service_preserved FROM business_applications WHERE tenant=?', (tenant,)))
    if row:
        if row['status'] == 'APPROVED' or (activation and row['service_preserved']):
            return
    elif _legacy_service(tenant):
        return
    raise ApplicationError('business_approval_required', 403)


def submit_verified(tenant, email, details, *, db=None):
    """Called only after email verification, including inside PG signup txn."""
    if db is None:
        preserved = _legacy_service(tenant)
        with database(tenant, write=True) as connection:
            return _submit(connection, tenant, email, details, preserved=preserved)
    return _submit(db, tenant, email, details, preserved=False)


def _submit(db, tenant, email, data, *, preserved=False):
    policy = settings(db=db)
    if not policy['intake_enabled'] or not policy['legal_review_completed']:
        raise ApplicationError('business_application_intake_closed', 503)
    if not valid_account_email(email) or len(email) > 254:
        raise ApplicationError('invalid_application_email')
    details = validate_details(data, policy=policy)
    if _lock(db, tenant):
        raise ApplicationError('application_already_exists', 409)
    _limit_submissions(db, email)
    now = time.time()
    _execute(db, 'INSERT INTO business_applications '
             '(tenant,status,revision,details,contact_email,policy_version,created,updated,service_preserved) '
             "VALUES (?,'PENDING_REVIEW',1,?,?,?,?,?,?)",
             (tenant, _json(details), email, policy['policy_version'], now, now, int(preserved)))
    row = _lock(db, tenant)
    _event(db, tenant, 1, 'submitted', 'verified_applicant')
    _notify(db, row, 'PENDING_REVIEW')
    return public_application(row)


def _version(row, data):
    if not row:
        raise ApplicationError('application_not_found', 404)
    if type(data.get('revision')) is not int or data['revision'] != row['revision']:
        raise ApplicationError('application_changed_refresh', 409)


def _limit_submissions(db, email):
    if session_store._using_postgres():
        key = int.from_bytes(hashlib.sha256(('business_application_email:' + email).encode()).digest()[:8], 'big', signed=True)
        db.execute('SELECT pg_advisory_xact_lock(%s)', (key,))
        match = "payload::jsonb->>'email'=? AND payload::jsonb->>'stage'='PENDING_REVIEW' AND payload::jsonb->>'owner'='false'"
    else:
        match = "json_extract(payload,'$.email')=? AND json_extract(payload,'$.stage')='PENDING_REVIEW' AND json_extract(payload,'$.owner')=0"
    count = _execute(db, 'SELECT COUNT(*) FROM business_application_notifications WHERE created>? AND ' + match,
                     (time.time() - 86400, email)).fetchone()[0]
    if count >= 5:
        raise ApplicationError('application_submission_rate_limited', 429)


def _no_open_payments(db, tenant):
    if _execute(db, "SELECT 1 FROM business_application_permits WHERE tenant=? AND state IN ('reserved','issued') LIMIT 1", (tenant,)).fetchone():
        raise ApplicationError('application_checkout_unresolved', 409)


def update(tenant, data, email, *, actor=None):
    """Correction/reconsideration. Never accepts status, notes or research."""
    if not isinstance(data, dict):
        raise ApplicationError('invalid_application_details')
    if not valid_account_email(email) or len(email) > 254:
        raise ApplicationError('invalid_application_email')
    with database(tenant, write=True) as db:
        row = _lock(db, tenant)
        _version(row, data)
        _no_open_payments(db, tenant)
        if row['updated'] > time.time() - 30:
            raise ApplicationError('application_update_rate_limited', 429)
        _limit_submissions(db, email)
        details = validate_details(data, policy=settings(db=db))
        revision = row['revision'] + 1
        _execute(db, "UPDATE business_applications SET details=?,status='PENDING_REVIEW',revision=?,"
                 "public_message='',research='{}',updated=?,policy_version=?,contact_email=? WHERE tenant=?",
                 (_json(details), revision, time.time(), settings(db=db)['policy_version'], email, tenant))
        _event(db, tenant, revision, 'resubmitted', actor or 'verified_applicant')
        row = _lock(db, tenant)
        _notify(db, row, 'PENDING_REVIEW')
        return public_application(row)


def cancel(tenant, data, email):
    with database(tenant, write=True) as db:
        row = _lock(db, tenant)
        _version(row, data)
        _no_open_payments(db, tenant)
        if row['status'] == 'CANCELLED':
            return public_application(row)
        _execute(db, "UPDATE business_applications SET status='CANCELLED',revision=revision+1,updated=? WHERE tenant=?",
                 (time.time(), tenant))
        _event(db, tenant, row['revision'] + 1, 'cancelled', email)
        return public_application(_lock(db, tenant))


def review(tenant, data):
    actor = _operator()
    if not isinstance(data, dict) or data.get('decision') not in {'approve', 'reject', 'request_information', 'expire', 'note'}:
        raise ApplicationError('invalid_application_decision')
    note = _text(data.get('note', ''), 4000)
    message = _text(data.get('message', ''), 2000, required=data['decision'] == 'request_information')
    with database(tenant, write=True, operator=True) as db:
        row = _lock(db, tenant)
        _version(row, data)
        if not row['contact_email']:
            raise ApplicationError('application_resubmission_required', 409)
        if actor['email'].casefold() == row['contact_email'].casefold() or actor.get('tenant') == tenant:
            raise ApplicationError('application_self_approval_forbidden', 403)
        decision = data['decision']
        if decision == 'note':
            if not note:
                raise ApplicationError('application_note_required')
            # Append-only notes cannot overwrite concurrent notes and do not
            # change the material details/status or payment approval revision.
            _event(db, tenant, row['revision'], 'note', actor['id'], note)
            return public_application(row)
        _no_open_payments(db, tenant)
        target = {'approve': 'APPROVED', 'reject': 'REJECTED', 'request_information': 'NEEDS_INFORMATION', 'expire': 'EXPIRED'}[decision]
        if row['status'] in {'CANCELLED', 'EXPIRED'} or row['status'] == target:
            raise ApplicationError('invalid_application_transition', 409)
        if target == 'REJECTED':
            message = 'We cannot offer services under the current activity-based eligibility policy. You may correct your details or request reconsideration here.'
        elif target == 'APPROVED':
            message = 'Your business has been approved. Continue to Subscription to complete secure checkout.'
        revision = row['revision'] + 1
        _execute(db, 'UPDATE business_applications SET status=?,revision=?,updated=?,public_message=? WHERE tenant=?',
                 (target, revision, time.time(), message, tenant))
        _event(db, tenant, revision, target, actor['id'], note)
        row = _lock(db, tenant)
        _notify(db, row, target)
        return public_application(row)


def list_applications(*, status='', search='', sort='newest', page=1):
    _operator()
    if status and status not in STATES:
        raise ApplicationError('invalid_application_filter')
    if sort not in {'newest', 'oldest'} or type(page) is not int or not 1 <= page <= 10000:
        raise ApplicationError('invalid_application_page')
    search = _text(search, 120).lower()
    clause, params = [], []
    if status:
        clause.append('status=?')
        params.append(status)
    if search:
        # Escape wildcard characters; input is a literal search, never SQL.
        term = search.replace('!', '!!').replace('%', '!%').replace('_', '!_')
        clause.append("(lower(details) LIKE ? ESCAPE '!' OR lower(contact_email) LIKE ? ESCAPE '!')")
        params.extend(['%' + term + '%'] * 2)
    where = ' WHERE ' + ' AND '.join(clause) if clause else ''
    with database(operator=True) as db:
        total = _execute(db, 'SELECT COUNT(*) FROM business_applications' + where, tuple(params)).fetchone()[0]
        cursor = _execute(db, 'SELECT * FROM business_applications' + where +
                          ' ORDER BY created ' + ('DESC' if sort == 'newest' else 'ASC') + ',tenant LIMIT 50 OFFSET ?',
                          tuple(params) + ((page - 1) * 50,))
        rows = [{**public_application(row), 'tenant': row['tenant']} for row in _rows(cursor)]
        pending = _execute(db, "SELECT COUNT(*) FROM business_applications WHERE status IN ('PENDING_REVIEW','NEEDS_INFORMATION')").fetchone()[0]
    return {'applications': rows, 'total': total, 'pending': pending, 'page': page, 'has_next': page * 50 < total}


def save_settings(data):
    actor = _operator()
    allowed = set(DEFAULT_SETTINGS)
    if not isinstance(data, dict) or set(data) != allowed:
        raise ApplicationError('invalid_application_settings')
    with database(write=True, operator=True) as db:
        # Serialize the singleton even before its first INSERT on PostgreSQL.
        if session_store._using_postgres():
            db.execute("SELECT pg_advisory_xact_lock(731098220)")
        value = settings(db=db)
        if type(data.get('revision')) is not int or data['revision'] != value['revision']:
            raise ApplicationError('application_settings_changed', 409)
        for field in ('intake_enabled', 'research_enabled', 'owner_email_enabled', 'legal_review_completed'):
            if type(data.get(field)) is not bool:
                raise ApplicationError('invalid_application_settings')
        if type(data.get('retention_days')) is not int or not 30 <= data['retention_days'] <= 730:
            raise ApplicationError('invalid_application_settings')
        updated = {key: data[key] for key in allowed}
        for field, maximum in (('guidance', 2000), ('policy', 12000), ('owner_email', 254)):
            updated[field] = _text(data.get(field, ''), maximum, required=field != 'owner_email')
        if updated['owner_email'] and not valid_account_email(updated['owner_email']):
            raise ApplicationError('invalid_application_settings')
        if updated['intake_enabled'] and (not updated['legal_review_completed'] or
                (updated['owner_email_enabled'] and not updated['owner_email'])):
            raise ApplicationError('application_policy_and_notifications_required')
        categories = data.get('categories')
        if not isinstance(categories, dict) or set(categories) != {'general', 'closer_review', 'excluded'}:
            raise ApplicationError('invalid_application_settings')
        for entries in categories.values():
            if not isinstance(entries, list) or len(entries) > 30:
                raise ApplicationError('invalid_application_settings')
            for entry in entries:
                _text(entry, 300, required=True)
        updated['revision'] = value['revision'] + 1
        updated['policy_version'] = (secrets.token_hex(8) if updated['policy'] != value['policy'] else value['policy_version'])
        _execute(db, 'INSERT INTO business_application_settings VALUES (1,?) '
                 'ON CONFLICT(id) DO UPDATE SET value=excluded.value', (_json(updated),))
        # Settings events contain no notification addresses or applicant data.
        _event(db, '__platform__', updated['revision'], 'settings_updated', actor['id'])
        return updated


def reserve_payment(tenant, reference, kind):
    require_eligible(tenant)
    with database(tenant, write=True) as db:
        row = _lock(db, tenant)
        if row and row['status'] != 'APPROVED':
            raise ApplicationError('business_approval_required', 403)
        previous = _one(_execute(db, 'SELECT * FROM business_application_permits WHERE reference=? AND tenant=?', (reference, tenant)))
        if previous:
            if previous['kind'] != kind or previous['state'] == 'expired':
                raise ApplicationError('application_checkout_binding_conflict', 409)
            return
        _execute(db, "INSERT INTO business_application_permits (reference,tenant,revision,kind,state,created) VALUES (?,?,?,?,'reserved',?)",
                 (reference, tenant, row['revision'] if row else 0, kind, time.time()))


def bind_payment(tenant, reference, checkout):
    with database(tenant, write=True) as db:
        previous = _one(_execute(db, 'SELECT * FROM business_application_permits WHERE reference=? AND tenant=?', (reference, tenant)))
        if not previous or previous['state'] == 'expired' or (previous['checkout'] and previous['checkout'] != checkout):
            raise ApplicationError('application_checkout_binding_conflict', 409)
        _execute(db, "UPDATE business_application_permits SET checkout=?,state=CASE WHEN state='settled' THEN state ELSE 'issued' END WHERE reference=? AND tenant=?",
                 (checkout, reference, tenant))


def verify_payment(tenant, reference, kind, *, db=None):
    if db is None:
        with database(tenant) as connection:
            return verify_payment(tenant, reference, kind, db=connection)
    schema(db)
    row = _one(_execute(db, 'SELECT * FROM business_applications WHERE tenant=?', (tenant,)))
    permit = _one(_execute(db, 'SELECT * FROM business_application_permits WHERE tenant=? AND reference=?', (tenant, reference)))
    if permit:
        if permit['kind'] == kind and permit['state'] in {'reserved', 'issued', 'settled'}:
            return
        raise ApplicationError('application_payment_not_authorized', 403)
    if row and not row['service_preserved']:
        raise ApplicationError('application_payment_not_authorized', 403)
    if row:
        return
    # Missing applications are not blanket approval for managed new businesses.
    # Reuse this transaction so SQLite billing writes cannot deadlock themselves.
    from service import tenant_access
    tenant_access._schema(db)
    managed = _execute(db, 'SELECT owner FROM managed_businesses WHERE tenant=?', (tenant,)).fetchone()
    if managed is None:
        return  # Pre-existing unmanaged workspaces only.
    from flask import current_app, has_app_context
    if (has_app_context() and managed[0] is None and
            tenant == getattr(getattr(current_app.container, 'settings', None), 'PLATFORM_MARKETING_TENANT', '')):
        return
    if (_execute(db, "SELECT 1 FROM billing_contracts WHERE tenant=? AND kind='complimentary_scale' AND status='active'", (tenant,)).fetchone()
            or _execute(db, "SELECT 1 FROM billing_invoices WHERE tenant=? AND status='paid' AND paid>0 LIMIT 1", (tenant,)).fetchone()):
        return
    raise ApplicationError('application_payment_not_authorized', 403)


def settle_payment(tenant, reference):
    with database(tenant, write=True) as db:
        _execute(db, "UPDATE business_application_permits SET state='settled' WHERE tenant=? AND reference=? AND state!='expired'", (tenant, reference))
        _execute(db, 'UPDATE business_applications SET service_preserved=1 WHERE tenant=?', (tenant,))


def close_payments(tenant):
    """Resolve canonical sessions before allowing revocation/material changes."""
    from service import subscriptions
    with database(tenant) as db:
        rows = _rows(_execute(db, "SELECT * FROM business_application_permits WHERE tenant=? AND state IN ('reserved','issued')", (tenant,)))
    for row in rows:
        checkout = row['checkout']
        if not checkout:
            raise ApplicationError('application_checkout_creation_unresolved', 409)
        session = subscriptions.client().stripe_request('GET', '/v1/checkout/sessions/' + checkout)
        if session.get('id') != checkout:
            raise ApplicationError('application_checkout_unresolved', 409)
        if session.get('status') == 'complete':
            raise ApplicationError('payment_processing_refresh_soon', 409)
        if session.get('status') == 'open':
            session = subscriptions.client().stripe_request('POST', '/v1/checkout/sessions/' + checkout + '/expire',
                                                           idempotency_key='v7-application-expire-' + row['reference'])
        if session.get('status') != 'expired':
            raise ApplicationError('application_checkout_unresolved', 409)
        with database(tenant, write=True) as db:
            _execute(db, "UPDATE business_application_permits SET state='expired' WHERE tenant=? AND reference=? AND state IN ('reserved','issued')",
                     (tenant, row['reference']))
    return {'ok': True}


def purge_closed(tenant):
    """Minimise closed, non-paying applications; retain minimal decision audit."""
    with database(tenant, write=True) as db:
        row = _lock(db, tenant)
        cutoff = time.time() - settings(db=db)['retention_days'] * 86400
        if (not row or row['status'] not in {'REJECTED', 'EXPIRED', 'CANCELLED'}
                or row['service_preserved'] or row['updated'] >= cutoff or not row['contact_email']):
            return False
        _no_open_payments(db, tenant)
        detail = json.loads(row['details'])
        detail.update(business_name='Archived application', website='', description='')
        _execute(db, "UPDATE business_applications SET details=?,contact_email='',research='{}',public_message='' WHERE tenant=?",
                 (_json(detail), tenant))
        # The runtime role can redact only this column, never rewrite an audit
        # decision, actor, revision or timestamp.
        _execute(db, "UPDATE business_application_events SET note='' WHERE tenant=?", (tenant,))
        _execute(db, 'DELETE FROM business_application_notifications WHERE tenant=?', (tenant,))
        _event(db, tenant, row['revision'], 'personal_data_minimised', 'retention_worker')
        return True


def material_change(tenant, filename, previous, proposed, *, db=None):
    """Reopen an enrolled business's review on identity/activity changes.

    Called by both storage backends, including raw JSON/API/MCP imports. Routine
    prices, stock, tone and action settings are not commercial eligibility.
    PostgreSQL document and eligibility changes use the same transaction.
    """
    if filename not in {'store_info.json', 'overrides.json'}:
        return
    before = previous if isinstance(previous, dict) else {}
    after = proposed if isinstance(proposed, dict) else {}
    if filename == 'store_info.json':
        fields = ('name', 'website', 'about')
    else:
        before = before.get('sales_playbook') or {}
        after = after.get('sales_playbook') or {}
        if not isinstance(before, dict) or not isinstance(after, dict):
            return
        fields = ('business_focus', 'business_model', 'primary_goal')
    changed = [key for key in fields if before.get(key) != after.get(key)
               and (key in {'name', 'website'} or before.get(key) not in (None, '', 'general', 'drive_sales'))]
    if not changed:
        return
    if db is None:
        with database(tenant, write=True) as connection:
            return _material_change(connection, tenant, filename, proposed, changed)
    _material_change(db, tenant, filename, proposed, changed)


def _material_change(db, tenant, filename, proposed, changed):
    schema(db)
    row = _lock(db, tenant)
    if not row or row['status'] != 'APPROVED':
        return
    _no_open_payments(db, tenant)
    detail = json.loads(row['details'])
    if filename == 'store_info.json':
        if 'name' in changed and str(proposed.get('name', '')).strip().casefold() == detail['business_name'].strip().casefold():
            changed.remove('name')
        if 'website' in changed:
            from service.website_knowledge import _validate_public_https_url
            try:
                if _validate_public_https_url(proposed.get('website', '')) == detail['website']:
                    changed.remove('website')
            except ValueError:
                pass
        if not changed:
            return
        detail['business_name'] = str(proposed.get('name') or detail['business_name'])[:120]
        if 'about' in changed:
            detail['description'] = str(proposed.get('about') or '')[:2000]
        if 'website' in changed:
            from service.website_knowledge import _validate_public_https_url, WebsiteImportError
            try:
                detail['website'] = _validate_public_https_url(proposed.get('website', ''))
            except ValueError:
                detail['website'] = ''
    revision = row['revision'] + 1
    _execute(db, "UPDATE business_applications SET status='PENDING_REVIEW',revision=?,details=?,updated=?,"
             "research='{}',public_message=? WHERE tenant=?", (revision, _json(detail), time.time(),
             'Your business identity or activities changed. Further purchases require review. Existing services are not automatically cancelled.', tenant))
    _event(db, tenant, revision, 'material_business_change', 'document_writer',
           'Review changed business fields: ' + ', '.join(changed) + '. Inspect the current business profile and playbook.')
    _notify(db, _lock(db, tenant), 'PENDING_REVIEW')
