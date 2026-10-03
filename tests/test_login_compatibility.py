"""Existing identities and hashes must survive the console sign-in change."""
from dataclasses import replace
import json
import os
from pathlib import Path

import bcrypt
import pytest

from service.security import generate_totp_secret, generate_totp_token


@pytest.mark.parametrize('source', ['environment', 'registry'])
def test_existing_bcrypt_operator_can_sign_in_with_mfa_over_https(client, monkeypatch, source):
    app = client.application
    app.container.settings = replace(app.container.settings, BASE_URL='https://console.example.test')
    hashed = bcrypt.hashpw(b'Existing-test-password-123', bcrypt.gensalt()).decode()
    if source == 'environment':
        secret = generate_totp_secret()
        identifier = 'legacy-admin'
        monkeypatch.setenv('ADMIN_USERNAME', identifier)
        monkeypatch.setenv('ADMIN_PASSWORD_HASH', hashed)
        monkeypatch.setenv('ADMIN_TOTP_SECRET', secret)
    else:
        identifier = 'legacy-operator@example.test'
        Path(os.environ['ADMIN_USERS_FILE']).write_text(json.dumps({'users': [{
            'email': identifier, 'role': 'platform_admin', 'password_hash': hashed,
        }]}), encoding='utf-8')
    rejected = client.post('/auth/login', json={
        'email': identifier, 'password': 'Wrong-test-password-123', 'tenant': 'EXAMPLE',
    })
    assert rejected.status_code == 401
    assert client.get('/admin/api/platform').status_code == 401
    response = client.post('/auth/login', json={
        'email': identifier, 'password': 'Existing-test-password-123', 'tenant': 'EXAMPLE',
    })
    assert response.status_code == 202
    if source == 'registry':
        assert response.json['mfa']['enrollment'] is True
        secret = response.json['mfa']['setup_key']
    assert client.get('/admin/api/platform').status_code == 401
    verified = client.post('/auth/mfa/confirm', json={'code': generate_totp_token(secret)})
    assert verified.status_code == 200
    assert verified.json['user']['email'] == identifier
    assert verified.json['user']['roles'] == ['platform_admin']
    assert client.get('/auth/session').json['user']['email'] == identifier
    assert client.get('/admin/api/platform').status_code == 200


def test_anonymous_sign_in_uses_configured_default_company(client):
    app = client.application
    app.container.settings = replace(app.container.settings, BUSINESS_KEY='example')
    response = client.get('/auth/session')
    assert response.status_code == 200
    assert response.json['login_tenant'] == 'EXAMPLE'
    assert response.json['user'] is None
    assert response.headers['Cache-Control'] == 'no-store'


def test_production_plaintext_admin_still_requires_hash_migration(client, monkeypatch):
    app = client.application
    app.container.settings = replace(app.container.settings, BASE_URL='https://console.example.test')
    monkeypatch.setenv('ADMIN_USERNAME', 'legacy-admin')
    monkeypatch.setenv('ADMIN_PASSWORD', 'Existing-test-password-123')
    monkeypatch.delenv('ADMIN_PASSWORD_HASH', raising=False)
    response = client.post('/auth/login', json={
        'email': 'legacy-admin', 'password': 'Existing-test-password-123', 'tenant': 'EXAMPLE',
    })
    assert response.status_code == 401
    assert response.json['error'] == 'invalid_credentials'
    assert client.get('/admin/api/platform').status_code == 401
