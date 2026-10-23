"""A signed-in session alone cannot disclose an account's TOTP enrollment."""
import json
import time

import pyotp
import pytest

from service.account_service import AccountService
from service import account_mfa


@pytest.fixture
def signed_in(client,monkeypatch,request):
    now=[int(time.time())]
    monkeypatch.setattr('service.security.time.time',lambda:now[0])
    email,password='second-phone@example.test','Additional-phone-test-password-42!'
    role=getattr(request,'param','business_owner')
    if role=='platform_admin':
        monkeypatch.setenv('ADMIN_USERNAME',email)
        monkeypatch.setenv('ADMIN_PASSWORD',password)
        monkeypatch.delenv('ADMIN_TOTP_SECRET',raising=False)
        record={}
    else:
        record=AccountService(client.application.container.storage).create_account('EXAMPLE',{
            'email':email,'password':password,'roles':[role],
            **({'permissions':['offerings.read']} if role=='business_staff' else {})})
    challenge=client.post('/auth/login',json={'email':email,'password':password,'tenant':'EXAMPLE'})
    secret=challenge.json['mfa']['setup_key']
    assert client.post('/auth/mfa/confirm',json={'code':pyotp.TOTP(secret).at(now[0])}).status_code==200
    now[0]+=30
    return {'email':email,'password':password,'secret':secret,'now':now,'record':record}


@pytest.mark.parametrize('signed_in',['business_owner','platform_admin','business_staff'],indirect=True)
def test_additional_phone_reuses_existing_enrollment_without_reset_or_cookie_secret(client,signed_in):
    row=signed_in
    payload={'current_password':row['password'],'code':pyotp.TOTP(row['secret']).at(row['now'][0])}
    response=client.post('/auth/mfa/add-device',json=payload)
    assert response.status_code==200 and response.json['setup_key']==row['secret']
    assert response.json['qr_image'].startswith('data:image/svg+xml;base64,')
    assert 'no-store' in response.headers['Cache-Control']
    with client.session_transaction() as state:
        user=state['user']
        assert row['secret'] not in json.dumps(dict(state)) and row['password'] not in json.dumps(dict(state))
    with client.application.app_context():
        assert account_mfa.enrolled_secret(user)==row['secret']
    assert client.post('/auth/mfa/add-device',json=payload).status_code==401
    assert client.get('/auth/session').json['user']['email']==row['email']
    client.post('/auth/logout')
    other=client.application.test_client()
    challenge=other.post('/auth/login',json={'email':row['email'],'password':row['password'],'tenant':'EXAMPLE'})
    assert challenge.status_code==202 and not challenge.json['mfa']['enrollment']
    assert 'setup_key' not in challenge.text
    row['now'][0]+=30
    assert other.post('/auth/mfa/confirm',json={'code':pyotp.TOTP(response.json['setup_key']).at(row['now'][0])}).status_code==200


def test_password_and_existing_code_both_required_and_account_cannot_be_selected(client,signed_in):
    row=signed_in
    payload={'current_password':row['password'],'code':pyotp.TOTP(row['secret']).at(row['now'][0])}
    for altered in ({**payload,'current_password':'Wrong-password'}, {**payload,'code':'wrong'},
                    {**payload,'email':'someone-else@example.test'}, {**payload,'tenant':'OTHER'}):
        response=client.post('/auth/mfa/add-device',json=altered)
        assert response.status_code in (400,401) and row['secret'] not in response.text
    assert client.post('/auth/mfa/add-device',json=payload).status_code==200


def test_anonymous_and_csrf_requests_cannot_disclose_enrollment(client,signed_in):
    payload={'current_password':signed_in['password'],'code':pyotp.TOTP(signed_in['secret']).at(signed_in['now'][0])}
    assert client.application.test_client().post('/auth/mfa/add-device',json=payload).status_code==401
    assert client.post('/auth/mfa/add-device',json=payload,headers={'X-CSRF-Token':'forged'}).status_code==403
    assert client.post('/auth/mfa/add-device',json=payload).status_code==200


def test_failed_step_up_is_rate_limited(client,signed_in):
    statuses=[client.post('/auth/mfa/add-device',json={'current_password':'Wrong-password','code':'123456'}).status_code
              for _ in range(10)]
    assert 429 in statuses
