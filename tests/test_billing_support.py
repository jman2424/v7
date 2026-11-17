"""Manual support never sends messages or dispatches paid AI work."""
import pytest
from service import business_operations as ops
from tests.test_subscriptions import identity


def test_owner_support_is_idempotent_private_and_manually_completed(client):
    identity(client, 'business_owner')
    body = {'kind':'setup', 'message':'Please help import our product data.', 'request_id':'a'*32}
    result = client.post('/billing/support', json=body)
    assert result.status_code == 201
    reference = result.json['reference']
    assert client.post('/billing/support', json=body).json['reference'] == reference
    assert client.post('/billing/support', json={**body,'message':'Different request content.'}).status_code == 400
    assert ops.get('EXAMPLE', reference)['state'] == 'needs_review'
    assert ops.support_requests('OTHER') == []
    assert client.post('/billing/support?tenant=OTHER', json=body).status_code == 403
    assert client.post('/billing/support/'+reference, json={'decision':'complete','version':1}).status_code == 403
    assert client.post('/admin/api/business-operations/'+reference+'/decision', json={'decision':'complete','version':1,'reply':'Forged support response.'}).status_code == 403
    assert ops.listing('EXAMPLE') == []
    identity(client)
    response = client.post('/billing/support/'+reference, json={'decision':'complete','version':1,'reply':'We reviewed your setup with you.'})
    assert response.status_code == 200
    assert client.get('/billing/support').json['requests'][0]['state'] == 'completed'
    assert client.post('/billing/support/'+reference, json={'decision':'complete','version':1}).status_code == 409


def test_support_requires_owner_and_csrf_and_limits_new_requests(client):
    assert client.get('/billing/support').status_code == 401
    identity(client, 'business_staff')
    body = {'kind':'billing','message':'Please explain this invoice.','request_id':'b'*32}
    assert client.post('/billing/support',json=body).status_code == 403
    identity(client,'business_owner')
    assert client.post('/billing/support',json=body,headers={'X-CSRF-Token':'invalid'}).status_code == 403
    for number in range(5):
        assert client.post('/billing/support',json={**body,'request_id':f'{number:032x}'}).status_code == 201
    assert client.post('/billing/support',json=body).json['error'] == 'support_daily_limit'
    assert client.post('/billing/support',json={**body,'kind':'unknown'}).status_code == 400


def test_closed_support_retention_preserves_open_and_other_business_requests(client):
    import time
    closed = ops.request_support('EXAMPLE', 'owner@example.test', 'setup', 'Please help configure our assistant.', 'c'*32)
    opened = ops.request_support('EXAMPLE', 'owner@example.test', 'access', 'Please explain account access.', 'd'*32)
    other = ops.request_support('OTHER', 'other@example.test', 'setup', 'Please help with our setup.', 'e'*32)
    ops.decide('EXAMPLE', closed, 1, 'complete', reply='Setup reviewed.')
    with ops.connection('EXAMPLE', write=True) as db:
        db.execute('UPDATE business_operations SET updated=? WHERE tenant=?', (time.time()-181*86400, 'EXAMPLE'))
    assert ops.purge_closed_support('EXAMPLE') == 1
    assert ops.get('EXAMPLE', closed) is None
    assert ops.get('EXAMPLE', opened)['state'] == 'needs_review'
    assert ops.get('OTHER', other)['state'] == 'needs_review'
