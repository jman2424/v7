from types import SimpleNamespace

from flask import Flask
import pytest

from app.middleware import install_request_boundaries
from tests.test_platform_security import platform, login  # noqa: F401


def test_production_accepts_only_configured_hosts_and_origins(monkeypatch):
    monkeypatch.setenv('RENDER_EXTERNAL_HOSTNAME', 'service.onrender.com')
    app = Flask(__name__)
    install_request_boundaries(app, SimpleNamespace(ENVIRONMENT='production', BASE_URL='https://console.example.test'))
    app.add_url_rule('/admin/api/example', view_func=lambda: 'ok', methods=['GET', 'POST'])
    app.add_url_rule('/billing/stripe/webhook', endpoint='webhook', view_func=lambda: 'signed elsewhere', methods=['POST'])
    client = app.test_client()
    assert client.get('/admin/api/example', base_url='https://attacker.example').status_code == 400
    assert client.get('/admin/api/example', base_url='https://attacker.example', headers={'X-Forwarded-Host': 'console.example.test'}).status_code == 400
    for origin in ['https://console.example.test', 'https://service.onrender.com']:
        assert client.post('/admin/api/example', base_url=origin, headers={'Origin': origin}).status_code == 200
    assert client.post('/admin/api/example', base_url='https://console.example.test', headers={'Origin': 'null'}).status_code == 403
    assert client.post('/billing/stripe/webhook', base_url='https://console.example.test', headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 200


@pytest.mark.parametrize('headers', [{'Origin': 'https://attacker.example'}, {'Sec-Fetch-Site': 'cross-site'}])
def test_cross_origin_management_write_rejected_even_with_csrf(platform, headers):
    client = platform[0].test_client()
    csrf = login(client)
    before = client.get('/admin/api/offers').json
    response = client.put('/admin/api/offers', json=[], headers={**headers, 'X-CSRF-Token': csrf})
    assert response.status_code == 403
    assert client.get('/admin/api/offers').json == before
    assert client.put('/admin/api/offers', json=[], headers={'Origin': 'http://localhost', 'X-CSRF-Token': csrf}).status_code == 200


def test_raw_offer_editor_cannot_bypass_discount_validation(platform):
    client = platform[0].test_client()
    csrf = login(client)
    offer = {'id': 'bad', 'title': 'Bad discount', 'description': 'Invalid', 'active': True,
             'deal_type': 'minimum_spend', 'minimum_spend': 10, 'discount_type': 'fixed', 'discount_value': 20}
    response = client.put('/files/raw/offers.json', json=[offer], headers={'X-CSRF-Token': csrf})
    assert response.status_code == 400
    assert client.get('/admin/api/offers').json == []


@pytest.mark.parametrize('field, value', [('email', 'a'*321), ('password', 'a'*1025), ('totp', '1'*33)])
def test_login_rejects_unbounded_input_before_authentication(platform, monkeypatch, field, value):
    client = platform[0].test_client()
    csrf = client.get('/auth/session').json['csrf_token']
    def must_not_authenticate(*args, **kwargs):
        raise AssertionError('Oversized credentials reached password verification')
    monkeypatch.setattr('service.security.authenticate_user', must_not_authenticate)
    response = client.post('/auth/login', json={'email': 'owner@example.test', 'password': 'test', field: value},
                           headers={'X-CSRF-Token': csrf})
    assert response.status_code == 400


def test_missing_authenticator_secret_never_verifies():
    from service.security import verify_totp
    assert verify_totp('', '123456') is False
    assert verify_totp(None, '123456') is False


def test_production_host_validation_cannot_start_unconfigured(monkeypatch):
    monkeypatch.delenv('RENDER_EXTERNAL_HOSTNAME', raising=False)
    with pytest.raises(RuntimeError, match='BASE_URL'):
        install_request_boundaries(Flask(__name__), SimpleNamespace(ENVIRONMENT='production', BASE_URL=''))
