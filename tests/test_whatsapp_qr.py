from __future__ import annotations

import base64
from xml.etree import ElementTree
from urllib.parse import parse_qs, urlsplit

import pytest

from service.whatsapp_qr import create_whatsapp_qr
from tests.conftest import set_test_identity


def _owner(client):
    with client.session_transaction() as state:
        set_test_identity(client, state, {"id": "owner", "roles": ["business_owner"], "tenant": "EXAMPLE"})


def test_qr_uses_whatsapp_international_number_and_encodes_message():
    message = 'Hi! Tea & coffee? £5 ☕'
    result = create_whatsapp_qr('+44 (7700) 900-123', message)
    url = urlsplit(result['link'])
    assert url.scheme == 'https' and url.netloc == 'wa.me' and url.path == '/447700900123'
    assert parse_qs(url.query) == {'text': [message]}
    svg = ElementTree.fromstring(base64.b64decode(result['image'].split(',', 1)[1]))
    assert svg.tag == '{http://www.w3.org/2000/svg}svg'
    assert svg.find('{http://www.w3.org/2000/svg}path') is not None
    assert svg.find('{http://www.w3.org/2000/svg}rect').get('fill') == 'white'
    assert all(element.tag in {'{http://www.w3.org/2000/svg}'+tag for tag in ('svg', 'path', 'rect')} for element in svg.iter())


@pytest.mark.parametrize('phone', ['', '07700900123', '+4407700900123x', 'https://evil.test', '+44+7700900123', '1'*16, 447700900123, None])
def test_qr_rejects_invalid_number(phone):
    with pytest.raises(ValueError):
        create_whatsapp_qr(phone)


@pytest.mark.parametrize('message', ['x'*201, 'hello\x00world', {'text':'hello'}])
def test_qr_rejects_invalid_message(message):
    with pytest.raises(ValueError):
        create_whatsapp_qr('447700900123', message)


def test_qr_requires_authentication_tenant_access_and_csrf(client):
    payload = {'phone': '+44 7700 900123'}
    assert client.post('/admin/api/whatsapp-qr', json=payload).status_code == 401
    _owner(client)
    assert client.post('/admin/api/whatsapp-qr?tenant=OTHER', json=payload).status_code == 403
    assert client.post('/admin/api/whatsapp-qr', json=payload, headers={'X-CSRF-Token':'invalid'}).status_code == 403
    response = client.post('/admin/api/whatsapp-qr?tenant=EXAMPLE', json=payload)
    assert response.status_code == 200
    assert response.json['tenant'] == 'EXAMPLE'
    assert response.json['link'] == 'https://wa.me/447700900123'
    assert response.headers['Cache-Control'] == 'no-store'
    assert client.get('/admin/api/whatsapp-qr').status_code == 405


def test_qr_reports_bad_payload_without_altering_settings(client, app):
    _owner(client)
    before = app.container.storage.read_json('EXAMPLE', 'branding.json')
    assert client.post('/admin/api/whatsapp-qr', json=[]).status_code == 400
    assert client.post('/admin/api/whatsapp-qr', json={'phone':'07700900123'}).status_code == 400
    assert app.container.storage.read_json('EXAMPLE', 'branding.json') == before
