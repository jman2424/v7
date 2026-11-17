"""Public enquiries save human follow-up tasks without AI, email or payment."""
from dataclasses import replace
from service import business_operations


def test_public_enquiry_is_csrf_protected_idempotent_and_has_a_receipt(client, app):
    app.container.settings = replace(app.container.settings, PLATFORM_MARKETING_TENANT='EXAMPLE')
    page = client.get('/contact')
    assert page.status_code == 200
    with client.session_transaction() as state:
        request_id = state['enquiry_request_id']
    form = {'business_name':'Synthetic business','email':'owner@example.test','message':'Please show how to answer our product questions.','request_id':request_id}
    assert client.post('/contact',data=form,headers={'X-CSRF-Token':'invalid'}).status_code == 403
    response=client.post('/contact',data=form)
    assert response.status_code == 303
    receipt=client.get(response.location)
    assert 'Your enquiry is saved' in receipt.text
    assert receipt.headers['X-Robots-Tag'] == 'noindex, nofollow'
    assert client.post('/contact',data=form).status_code == 303
    rows=business_operations.support_requests('EXAMPLE')
    assert len(rows)==1 and rows[0]['state']=='needs_review' and rows[0]['kind']=='demo'
    assert rows[0]['contact']=='owner@example.test'
    assert business_operations.support_requests('OTHER')==[]


def test_unconfigured_form_does_not_claim_to_send_a_message(client, app):
    app.container.settings=replace(app.container.settings,PLATFORM_MARKETING_TENANT='')
    assert 'temporarily unavailable' in client.get('/contact').text
    assert client.post('/contact',data={}).status_code == 503
