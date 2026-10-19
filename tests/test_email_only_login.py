"""Email-first sign-in still binds password, MFA and data access to one account."""
import json
from pathlib import Path
import os

import pytest

from service.account_service import AccountService
from service.security import generate_totp_token
from tests.test_widget_tenancy import _add_tenant


def account(storage, tenant, email='email-login@example.test'):
    return AccountService(storage).create_account(tenant, {'email':email,
        'password':'Email-login-test-password-123', 'roles':['business_owner']})


def test_nondefault_business_is_resolved_without_accepting_a_url_tenant(app, client):
    _add_tenant(app)
    account(app.container.storage, 'ALT')
    challenge = client.post('/auth/login?tenant=EXAMPLE', json={'email':'email-login@example.test',
        'password':'Email-login-test-password-123'})
    assert challenge.status_code == 202
    assert client.get('/admin/api/catalog?tenant=ALT').status_code == 401
    signed = client.post('/auth/mfa/confirm', json={'code':generate_totp_token(challenge.json['mfa']['setup_key'])})
    assert signed.status_code == 200 and signed.json['user']['tenant'] == 'ALT'
    assert client.get('/admin/api/catalog?tenant=ALT').status_code == 200
    assert client.get('/admin/api/catalog?tenant=EXAMPLE').status_code == 403


def test_ambiguous_email_requires_account_resolution_without_disclosing_businesses(app, client):
    _add_tenant(app)
    account(app.container.storage, 'ALT')
    account(app.container.storage, 'EXAMPLE')
    result = client.post('/auth/login', json={'email':'email-login@example.test',
        'password':'Email-login-test-password-123'})
    assert result.status_code == 401 and result.json == {'ok':False, 'error':'invalid_credentials'}
    assert 'ALT' not in result.text and 'EXAMPLE' not in result.text


def test_registry_account_in_another_business_needs_no_company_key(app, client):
    from service.security import hash_password
    _add_tenant(app)
    Path(os.environ['ADMIN_USERS_FILE']).write_text(json.dumps({'users':[{
        'email':'registry-login@example.test', 'role':'business_owner', 'tenant':'ALT',
        'password_hash':hash_password('Email-login-test-password-123')}]}), encoding='utf-8')
    result = client.post('/auth/login', json={'email':'registry-login@example.test',
        'password':'Email-login-test-password-123'})
    assert result.status_code == 202


def test_disabled_account_and_wrong_password_do_not_create_challenges(app, client):
    stored = account(app.container.storage, 'EXAMPLE')
    payload = {'email':'email-login@example.test','password':'wrong'}
    assert client.post('/auth/login', json=payload).status_code == 401
    AccountService(app.container.storage).update_account('EXAMPLE', stored['id'], {'active':False})
    assert client.post('/auth/login', json={**payload,'password':'Email-login-test-password-123'}).status_code == 401
