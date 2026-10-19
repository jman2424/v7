"""Receipt-authorized management of V7-native appointments; no external claims."""
from contextlib import contextmanager
from datetime import datetime, timezone
import re
import sqlite3

from service import session_store
from service.conversion_actions import ActionError, _database, _start_time, load_actions


@contextmanager
def _transaction(tenant):
    if session_store._using_postgres():
        with session_store.postgres_connection(tenant) as db:
            db.execute('SELECT tenant FROM v7_private.tenants WHERE tenant=%s FOR UPDATE', (tenant,))
            yield db, 'v7_private.sales_action_requests', '%s'
    else:
        db = _database()
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db, 'sales_action_requests', '?'
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


def receipt_claims(tenant, reference):
    with _transaction(tenant) as (db, table, p):
        created = db.execute(f'SELECT created_at FROM {table} WHERE tenant={p} AND reference={p}',
                             (tenant, reference)).fetchone()
        if created is None:
            raise ActionError('booking_not_found', 404)
        return {'tenant': tenant, 'reference': reference,
                'expires': int(_start_time(created[0]).timestamp()) + 30 * 86400}


def manage_booking(storage, tenant, reference, operation, *, slot_id=None, expected_slot_id=None):
    if not isinstance(reference, str) or not re.fullmatch(r'[A-Za-z0-9_-]{12,64}', reference):
        raise ActionError('booking_not_found', 404)
    if not isinstance(operation, str) or operation not in {'view', 'cancel', 'reschedule'}:
        raise ActionError('invalid_operation')
    try:
        with _transaction(tenant) as (db, table, p):
            row = db.execute(f'SELECT reference,status,slot_id,slot_start_at,slot_label FROM {table} '
                             f'WHERE tenant={p} AND reference={p} AND action={p}',
                             (tenant, reference, 'consultation')).fetchone()
            if row is None:
                raise ActionError('booking_not_found', 404)
            result = dict(zip(('reference', 'status', 'slot_id', 'start_at', 'label'), tuple(row)))
            if operation == 'view' or (operation == 'cancel' and result['status'] == 'cancelled'):
                return result
            if result['status'] != 'confirmed' or not result['slot_id']:
                raise ActionError('booking_not_changeable', 409)
            if _start_time(result['start_at']) <= datetime.now(timezone.utc):
                raise ActionError('booking_started', 409)
            if operation == 'reschedule' and slot_id == result['slot_id']:
                return result  # Safe retry after a successful change.
            if expected_slot_id != result['slot_id']:
                raise ActionError('booking_changed', 409)
            config = load_actions(storage, tenant)['consultation']
            if not config.get('manage_bookings', False):
                raise ActionError('management_unavailable', 409)
            if operation == 'cancel':
                db.execute(f'UPDATE {table} SET status={p},slot_id=NULL WHERE tenant={p} AND reference={p}',
                           ('cancelled', tenant, reference))
                return {**result, 'status': 'cancelled', 'slot_id': None}
            if not config['enabled']:
                raise ActionError('action_unavailable', 409)
            slot = next((item for item in config['slots'] if item['id'] == slot_id), None)
            if slot is None or _start_time(slot['start_at']) <= datetime.now(timezone.utc):
                raise ActionError('slot_unavailable', 409)
            occupied = db.execute(f'SELECT 1 FROM {table} WHERE tenant={p} AND slot_id={p} AND action={p}',
                                  (tenant, slot_id, 'consultation')).fetchone()
            if occupied:
                raise ActionError('slot_unavailable', 409)
            db.execute(f'UPDATE {table} SET slot_id={p},slot_start_at={p},slot_label={p} '
                       f'WHERE tenant={p} AND reference={p}',
                       (slot_id, slot['start_at'], slot['label'], tenant, reference))
            return {**result, 'slot_id': slot_id, 'start_at': slot['start_at'], 'label': slot['label']}
    except sqlite3.IntegrityError:
        raise ActionError('slot_unavailable', 409) from None
