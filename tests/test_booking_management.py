"""Native appointment changes are receipt-scoped, explicit and transactional."""
from datetime import datetime, timedelta, timezone
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from service.conversion_actions import ActionError, submit_action, public_availability
from service.booking_management import manage_booking
from tests.test_widget_tenancy import _add_tenant


def settings():
    return {'consultation': {'enabled': True, 'slots': [
        {'id': name, 'label': 'Review '+name,
         'start_at': (datetime.now(timezone.utc)+timedelta(days=day)).isoformat()}
        for day, name in enumerate(['first', 'second', 'third'], start=2)]},
        'quote': {'enabled': True}, 'callback': {'enabled': True}}


def book(storage, tenant, slot='first', key='original'):
    return submit_action(storage, tenant, {'action':'consultation', 'slot_id':slot, 'consent':True,
        'name':'Synthetic customer', 'contact':'synthetic@example.test', 'details':'Test only',
        'idempotency_key':key}, key)


def exercise(storage, tenant, other):
    storage.write_json(tenant, 'sales_actions.json', settings())
    ref = book(storage, tenant)['reference']
    with pytest.raises(ActionError, match='booking_not_found'):
        manage_booking(storage, other, ref, 'view')
    changed = manage_booking(storage, tenant, ref, 'reschedule', slot_id='second', expected_slot_id='first')
    assert changed['slot_id'] == 'second' and changed['status'] == 'confirmed'
    assert manage_booking(storage, tenant, ref, 'reschedule', slot_id='second', expected_slot_id='first') == changed
    assert 'contact' not in changed and 'name' not in changed
    assert 'first' in [slot['id'] for slot in public_availability(storage, tenant)['consultation']['slots']]
    with pytest.raises(ActionError, match='booking_changed'):
        manage_booking(storage, tenant, ref, 'cancel', expected_slot_id='first')
    book(storage, tenant, 'third', 'other-booking')
    with pytest.raises(ActionError, match='slot_unavailable'):
        manage_booking(storage, tenant, ref, 'reschedule', slot_id='third', expected_slot_id='second')
    assert manage_booking(storage, tenant, ref, 'view')['slot_id'] == 'second'
    cancelled = manage_booking(storage, tenant, ref, 'cancel', expected_slot_id='second')
    assert cancelled['status'] == 'cancelled'
    assert manage_booking(storage, tenant, ref, 'cancel', expected_slot_id='second') == cancelled
    with pytest.raises(ActionError, match='booking_not_changeable'):
        manage_booking(storage, tenant, ref, 'reschedule', slot_id='first', expected_slot_id='second')
    assert 'second' in [slot['id'] for slot in public_availability(storage, tenant)['consultation']['slots']]


def test_native_sqlite_booking_lifecycle(app):
    _add_tenant(app)
    exercise(app.container.storage, 'EXAMPLE', 'ALT')


def test_native_postgres_booking_lifecycle(pg_runtime):
    from retrieval.storage import Storage
    exercise(Storage(pg_runtime['tenant']), pg_runtime['tenant'], pg_runtime['other'])


def race(storage, tenant):
    storage.write_json(tenant, 'sales_actions.json', settings())
    refs = [book(storage, tenant, slot, 'race-'+slot)['reference'] for slot in ['first','second']]
    barrier = Barrier(2)
    def change(args):
        ref, old = args
        barrier.wait(timeout=10)
        try:
            return manage_booking(storage, tenant, ref, 'reschedule', slot_id='third', expected_slot_id=old)['status']
        except ActionError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(change, zip(refs, ['first','second'])))
    assert sorted(results) == ['confirmed','slot_unavailable']
    slots = [manage_booking(storage, tenant, ref, 'view')['slot_id'] for ref in refs]
    assert len(set(slots)) == 2 and slots.count('third') == 1


def test_competing_sqlite_reschedules_do_not_double_book(app):
    race(app.container.storage, 'EXAMPLE')


def test_competing_postgres_reschedules_do_not_double_book(pg_runtime):
    from retrieval.storage import Storage
    race(Storage(pg_runtime['tenant']), pg_runtime['tenant'])


def test_disabled_actions_still_allow_customer_to_cancel_existing_booking(app):
    storage = app.container.storage
    config = settings()
    storage.write_json('EXAMPLE', 'sales_actions.json', config)
    ref = book(storage, 'EXAMPLE')['reference']
    config['consultation']['enabled'] = False
    storage.write_json('EXAMPLE', 'sales_actions.json', config)
    with pytest.raises(ActionError, match='action_unavailable'):
        manage_booking(storage, 'EXAMPLE', ref, 'reschedule', slot_id='second', expected_slot_id='first')
    assert manage_booking(storage, 'EXAMPLE', ref, 'view')['slot_id'] == 'first'
    assert manage_booking(storage, 'EXAMPLE', ref, 'cancel', expected_slot_id='first')['status'] == 'cancelled'


def test_receipt_route_requires_authority_and_explicit_confirmation(app, client):
    _add_tenant(app)
    app.container.storage.write_json('EXAMPLE', 'sales_actions.json', settings())
    chat = client.post('/chat_api', json={'tenant':'EXAMPLE','message':'hello'}).json
    payload = {'tenant':'EXAMPLE','conversation_token':chat['conversation_token'], 'action':'consultation',
        'slot_id':'first', 'consent':True, 'name':'Synthetic', 'contact':'synthetic@example.test',
        'idempotency_key':'booking-route'}
    receipt = client.post('/chat/actions', json=payload).json
    assert client.post('/chat/actions', json=payload).json == receipt
    another_chat = client.post('/chat_api', json={'tenant':'EXAMPLE','message':'hello'}).json
    assert client.post('/chat/actions', json={**payload, 'conversation_token':another_chat['conversation_token']}).status_code == 409
    body = {'tenant':'EXAMPLE', 'receipt_token':receipt['receipt_token'], 'operation':'view'}
    view = client.post('/chat/booking', json=body)
    assert view.status_code == 200 and view.json['booking']['status'] == 'confirmed'
    assert 'synthetic' not in view.get_data(as_text=True).lower()
    assert client.post('/chat/booking', json={**body, 'tenant':'ALT'}).status_code == 403
    assert client.post('/chat/booking', json={**body, 'receipt_token':chat['conversation_token']}).status_code == 403
    assert client.post('/chat/booking', json={**body, 'receipt_token':'tampered'}).status_code == 403
    assert client.post('/chat/booking', json=body, headers={'Origin':'https://evil.example'}).status_code == 403
    assert client.post('/chat/booking', json={**body, 'operation':'cancel'}).status_code == 400
    assert client.post('/chat/booking', json={**body, 'operation':{},'confirm':True}).status_code == 400
    cancelled = client.post('/chat/booking', json={**body, 'operation':'cancel','confirm':True,'expected_slot_id':'first'})
    assert cancelled.status_code == 200 and cancelled.json['booking']['status'] == 'cancelled'
    from routes.conversion_routes import _receipt_signer
    with app.app_context():
        expired = _receipt_signer().dumps({'tenant':'EXAMPLE', 'reference':receipt['reference'], 'expires':int(time.time())-1})
    assert client.post('/chat/booking', json={**body,'receipt_token':expired}).status_code == 403


def test_real_browser_requires_csrf_even_with_a_valid_booking_receipt(app):
    from flask.testing import FlaskClient
    from routes.conversion_routes import _receipt_signer
    from service.booking_management import receipt_claims
    storage = app.container.storage
    storage.write_json('EXAMPLE', 'sales_actions.json', settings())
    reference = book(storage, 'EXAMPLE')['reference']
    with app.app_context():
        receipt = _receipt_signer().dumps(receipt_claims('EXAMPLE', reference))
    browser = FlaskClient(app)
    page = browser.get('/chat/booking?tenant=EXAMPLE')
    assert page.status_code == 200 and b'data-csrf=' in page.data
    with browser.session_transaction() as session:
        csrf = session['_csrf']
    body = {'tenant':'EXAMPLE','receipt_token':receipt,'operation':'view'}
    assert browser.post('/chat/booking', json=body).status_code == 403
    assert browser.post('/chat/booking', json=body, headers={'X-CSRF-Token':csrf}).status_code == 200
    assert browser.get('/static/js/booking.js').status_code == 200
    assert browser.get('/static/css/booking.css').status_code == 200


@pytest.mark.parametrize('operation', ['view', 'cancel', 'reschedule'])
def test_unknown_reference_never_lists_customer_records(app, operation):
    with pytest.raises(ActionError, match='booking_not_found'):
        manage_booking(app.container.storage, 'EXAMPLE', 'nonexistent-ref', operation)
