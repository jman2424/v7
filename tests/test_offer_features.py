from datetime import datetime, timedelta, timezone
import json

import pytest

from service import analytics_db
from service.offer_metrics import shown_offers
from service.statistics import get_statistics
from tests.test_admin_api import as_admin
from tests.conftest import set_test_identity


def offer(**values):
    return {'id': 'deal', 'title': 'Two for one', 'description': 'Available while stocks last.',
            'active': True, 'deal_type': 'buy_one_get_one', 'product_skus': ['CHICK_WINGS_1KG'], **values}


def test_offer_types_and_history_survive_reload_and_do_not_promote_archives(client, app):
    as_admin(client)
    items = [offer(), offer(id='spend', title='Basket saving', deal_type='minimum_spend',
                           minimum_spend=50, discount_type='fixed', discount_value=5, product_skus=[]),
             offer(id='old', title='Old promotion', archived=True)]
    assert client.put('/admin/api/offers', json=items).status_code == 200
    assert client.get('/admin/api/offers').json == items
    response = app.container.handler.handle('Any offers?', tenant='EXAMPLE', channel='web', session_id='offers-test')
    assert 'Buy 1 eligible item and get 1 of the same item free' in response['reply']
    assert 'Spend at least GBP 50.00' in response['reply']
    assert 'GBP 5.00 off' in response['reply']
    assert 'Old promotion' not in response['reply']
    assert shown_offers(response) == ['deal', 'spend']


@pytest.mark.parametrize('values', [
    {'product_skus': []}, {'deal_type': []}, {'product_skus': 42},
    {'deal_type': 'minimum_spend', 'minimum_spend': -1, 'discount_type': 'fixed', 'discount_value': 5},
    {'deal_type': 'minimum_spend', 'minimum_spend': 50, 'discount_type': 'percentage', 'discount_value': 101},
    {'deal_type': 'minimum_spend', 'minimum_spend': 50, 'discount_type': 'fixed', 'discount_value': 51},
    {'deal_type': 'minimum_spend', 'minimum_spend': 50.001, 'discount_type': 'fixed', 'discount_value': 5},
    {'deal_type': 'minimum_spend', 'minimum_spend': 50, 'discount_type': [], 'discount_value': 5},
])
def test_invalid_deals_are_rejected_without_changing_saved_offers(client, values):
    as_admin(client)
    original = client.get('/admin/api/offers').json
    response = client.put('/admin/api/offers', json=[offer(**values)])
    assert response.status_code == 400
    assert client.get('/admin/api/offers').json == original


def test_offer_api_requires_authorized_company(client):
    assert client.get('/admin/api/offers').status_code == 401
    with client.session_transaction() as state:
        set_test_identity(client, state, {'id': 'owner', 'roles': ['business_owner'], 'tenant': 'EXAMPLE'})
    assert client.put('/admin/api/offers?tenant=OTHER', json=[offer()]).status_code == 403
    assert client.get('/admin/api/offers?tenant=OTHER').status_code == 403


def test_offer_statistics_scope_dates_channels_and_deduplicate(app):
    now = datetime.now(timezone.utc)
    analytics_db.log_message(tenant='EXAMPLE', channel='web', direction='outbound', session_id='s',
                             intent='offers', offers=['deal', 'deal'], message_id='offer-reply')
    analytics_db.log_message(tenant='EXAMPLE', channel='web', direction='outbound', session_id='s',
                             intent='offers', offers=['deal'], message_id='offer-reply')
    analytics_db.log_message(tenant='OTHER', channel='web', direction='outbound', session_id='s',
                             intent='offers', offers=['private-offer'])
    with analytics_db._conn() as db:
        db.execute("INSERT INTO events(ts_utc,tenant,channel,session_id,event_type,intent,meta_json) VALUES(?,?,?,?,?,?,?)",
                   ((now-timedelta(days=9)).isoformat(), 'EXAMPLE', 'web', 's', 'msg_out', 'offers', json.dumps({'offers': ['deal']})))
    result = get_statistics(tenant='EXAMPLE', days=7, offers=[offer()])['offers']
    assert result['offer_replies'] == 1 and result['conversations'] == 1
    assert result['items'][0]['replies'] == 1
    assert 'private-offer' not in json.dumps(result)
    assert get_statistics(tenant='EXAMPLE', days=7, channel='whatsapp', offers=[offer()])['offers']['items'][0]['replies'] == 0


def test_only_displayed_offers_are_attributed():
    assert shown_offers({'intent': 'offers', 'reply': 'Shown', 'facts': {'offers': {'items': [
        offer(id='one', title='Shown'), offer(id='two', title='Omitted')]}}}) == ['one']


def test_web_offer_replies_are_attributed_at_transport_boundary(client):
    as_admin(client)
    assert client.put('/admin/api/offers', json=[offer()]).status_code == 200
    response = client.post('/chat_api', json={'tenant': 'EXAMPLE', 'message': 'Buy one get one free?', 'session_id': 'bogo-test'})
    assert response.status_code == 200
    stats = client.get('/admin/api/statistics?days=1').json['offers']
    assert stats['items'][0]['replies'] == 1
    assert stats['items'][0]['conversations'] == 1


def signup_offer(**values):
    return offer(id='signup', title='Welcome saving', deal_type='signup_discount',
                 discount_type='percentage', discount_value=10, product_skus=[], code='WELCOME10',
                 description='Create an account on our website. New customers only; redeem at checkout after verification.',
                 **values)


@pytest.mark.parametrize('kind,value,expected', [('percentage', 10, '10%'), ('fixed', 5.5, 'GBP 5.50')])
def test_signup_discount_roundtrips_and_preserves_conditions(client, app, kind, value, expected):
    as_admin(client)
    promotion = signup_offer()
    promotion.update(discount_type=kind, discount_value=value)
    assert client.put('/admin/api/offers', json=[promotion]).status_code == 200
    assert client.get('/admin/api/offers').json == [promotion]
    result = app.container.handler.handle('Any signup discounts?', tenant='EXAMPLE', channel='web', session_id='signup-offer')
    assert expected in result['reply'] and 'after signing up' in result['reply']
    assert 'New customers only' in result['reply'] and 'verification' in result['reply']
    assert 'WELCOME10' in result['reply']
    assert shown_offers(result) == ['signup']


@pytest.mark.parametrize('values', [
    {'discount_value': 0}, {'discount_value': -1}, {'discount_value': 101},
    {'discount_value': 10.001}, {'discount_value': True}, {'discount_value': '10'},
    {'discount_type': 'other'}, {'discount_type': []}, {'discount_value': None},
    {'discount_type': 'fixed', 'discount_value': 1000000.01},
])
def test_invalid_signup_discounts_do_not_change_saved_data(client, values):
    as_admin(client)
    original = client.get('/admin/api/offers').json
    promotion = signup_offer()
    promotion.update(values)
    assert client.put('/admin/api/offers', json=[promotion]).status_code == 400
    assert client.get('/admin/api/offers').json == original


@pytest.mark.parametrize('field', ['discount_type', 'discount_value'])
def test_signup_discount_requires_structured_reward(client, field):
    as_admin(client)
    promotion = signup_offer()
    promotion.pop(field)
    assert client.put('/admin/api/offers', json=[promotion]).status_code == 400


@pytest.mark.parametrize('status', ['disabled', 'archived', 'expired', 'scheduled'])
def test_signup_discount_is_optional_and_respects_dates(client, app, status):
    as_admin(client)
    today = datetime.now(timezone.utc).date()
    promotion = signup_offer()
    promotion.update({'disabled': {'active': False}, 'archived': {'archived': True},
                      'expired': {'ends_on': (today-timedelta(days=1)).isoformat()},
                      'scheduled': {'starts_on': (today+timedelta(days=1)).isoformat()}}[status])
    assert client.put('/admin/api/offers', json=[offer(), promotion]).status_code == 200
    result = app.container.handler.handle('Any signup discounts?', tenant='EXAMPLE', channel='web', session_id='signup-off')
    assert 'no' in result['reply'].lower() and 'signup discount' in result['reply']
    assert 'Welcome saving' not in result['reply'] and '10%' not in result['reply']
    assert 'Two for one' not in result['reply']


def test_signup_question_finds_its_offer_after_unrelated_promotions(client, app):
    as_admin(client)
    items = [offer(id=f'bogo_{index}', title=f'Other saving {index}') for index in range(4)] + [signup_offer()]
    assert client.put('/admin/api/offers', json=items).status_code == 200
    result = app.container.handler.handle('Can I get 10% off for signing up?', tenant='EXAMPLE', channel='web', session_id='signup-find')
    assert result['intent'] == 'offers'
    assert 'Welcome saving' in result['reply'] and 'Other saving' not in result['reply']


def test_legacy_custom_signup_offer_still_answers_signup_questions(client, app):
    as_admin(client)
    assert client.put('/admin/api/offers', json=[offer(deal_type='custom', title='Newsletter welcome',
        description='Get a welcome code after joining our newsletter.')]).status_code == 200
    result = app.container.handler.handle('Any newsletter discounts?', tenant='EXAMPLE', channel='web', session_id='signup-legacy')
    assert 'Newsletter welcome' in result['reply']


def test_signup_offer_cannot_be_written_or_read_through_another_tenant(client):
    with client.session_transaction() as state:
        set_test_identity(client, state, {'id': 'owner', 'roles': ['business_owner'], 'tenant': 'EXAMPLE'})
    assert client.put('/admin/api/offers?tenant=OTHER', json=[signup_offer()]).status_code == 403
    assert client.get('/admin/api/offers?tenant=OTHER').status_code == 403
