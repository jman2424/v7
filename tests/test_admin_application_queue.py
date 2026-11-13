"""The platform administrator manages business applications from their own account; nobody else can."""
import test_business_applications as helpers

intake = helpers.intake
workspace = helpers.workspace
stripe = helpers.stripe


def waiting(operator):
    response = operator.get('/business-applications/queue?page=1')
    assert response.status_code == 200
    return response.json['pending']


def test_administrator_sees_the_waiting_count_and_decides_from_their_account(workspace):
    applicant, operator, tenant = workspace
    assert waiting(operator) == 0
    helpers.apply(workspace)
    assert waiting(operator) == 1  # This drives the alert shown across the administrator's console.
    listed = operator.get('/business-applications/queue?page=1').json['applications']
    assert [row['tenant'] for row in listed] == [tenant] and listed[0]['status'] == 'PENDING_REVIEW'
    # Asking for more information needs the question, and keeps the application open.
    assert helpers.decide(workspace, 'request_information').status_code == 400
    asked = helpers.decide(workspace, 'request_information', message='Which products do you sell?')
    assert asked.status_code == 200 and asked.json['application']['status'] == 'NEEDS_INFORMATION'
    assert waiting(operator) == 1
    seen = applicant.get('/business-applications/current?tenant=' + tenant).json['application']
    assert seen['public_message'] == 'Which products do you sell?'
    approved = helpers.decide(workspace, 'approve', note='Checked the website by hand.')
    assert approved.status_code == 200 and approved.json['application']['status'] == 'APPROVED'
    assert waiting(operator) == 0
    # Private notes never reach the applicant.
    assert 'Checked the website by hand.' not in applicant.get('/business-applications/current?tenant=' + tenant).get_data(as_text=True)


def test_only_the_administrator_can_open_the_queue_or_decide(workspace):
    applicant, operator, tenant = workspace
    row = helpers.apply(workspace)
    assert applicant.get('/business-applications/queue?page=1').status_code in {401, 403}
    assert applicant.get('/business-applications/review?tenant=' + tenant).status_code in {401, 403}
    own = applicant.post('/business-applications/review?tenant=' + tenant,
                         json={'revision': row['revision'], 'decision': 'approve'})
    assert own.status_code in {401, 403}
    anonymous = applicant.application.test_client()
    assert anonymous.get('/business-applications/queue?page=1').status_code in {401, 403}
    declined = helpers.decide(workspace, 'reject')
    assert declined.status_code == 200 and declined.json['application']['status'] == 'REJECTED'
    assert waiting(operator) == 0
