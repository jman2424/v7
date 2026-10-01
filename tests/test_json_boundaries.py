"""Reject ambiguous or non-JSON input before it reaches auth or storage."""
import json

import pytest

from tests.conftest import set_test_identity


@pytest.mark.parametrize('body', [
    '{"email":"first@example.test","email":"second@example.test"}',
    '{"value":NaN}',
    '{"value":Infinity}',
    '{"value":-Infinity}',
    '{"value":1e309}',
])
def test_request_json_rejects_ambiguous_and_nonfinite_values(app, body):
    with pytest.raises(ValueError):
        app.json.loads(body)


def test_deep_json_is_rejected_before_action_processing(client):
    body = '{"nested":' + '[' * 1500 + '0' + ']' * 1500 + '}'
    response = client.post('/chat/actions', data=body,
                           content_type='application/json')
    assert response.status_code == 400


def test_nonfinite_branch_cannot_modify_business_document(client, tmp_business):
    with client.session_transaction() as state:
        set_test_identity(client, state, {'id': 'owner', 'role': 'business_owner'})
    document = tmp_business / 'branches.json'
    before = document.read_bytes()
    branches = json.loads(before)
    branches[0]['lat'] = float('nan')
    response = client.put('/admin/api/branches', data=json.dumps(branches),
                          content_type='application/json')
    assert response.status_code == 400
    assert document.read_bytes() == before


def test_normal_unicode_json_still_loads(app):
    assert app.json.loads('{"name":"Café","price":2.5}') == {
        'name': 'Café', 'price': 2.5,
    }


@pytest.mark.parametrize('number', [float('nan'), float('inf'), -float('inf')])
def test_storage_rejects_nonfinite_json_before_snapshot(storage, tmp_business, number):
    document = tmp_business / 'branches.json'
    before = document.read_bytes()
    branches = json.loads(before)
    branches[0]['lat'] = number
    with pytest.raises(ValueError, match='invalid_document_json'):
        storage.write_json('EXAMPLE', 'branches.json', branches,
                           schema='branches.schema.json')
    assert document.read_bytes() == before
    assert not storage.versions_root.exists()
