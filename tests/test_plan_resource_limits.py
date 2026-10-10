"""Commercial resource caps preserve tenant scope and permit cleanup."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from retrieval.storage import Storage
from service import subscriptions
from service.account_service import AccountService
from service.business_core import empty_core
from service.plan_catalog import get_plan
from tests.conftest import set_test_identity


def staff_payload(index, roles=None):
    return {'email': f'staff-{index}@example.test', 'password': 'Resource-limit-test-password',
            'roles': roles or ['business_staff']}


def branch(index):
    return {'id': f'branch-{index}', 'name': f'Branch {index}', 'lat': None, 'lon': None,
            'postcode': 'SW1A 1AA'}


def remote_location(index):
    return {'id': f'area-{index}', 'name': f'Service area {index}', 'type': 'remote_only',
            'service_area': 'United Kingdom', 'active': True}


@pytest.fixture
def starter_resources(app, monkeypatch):
    storage = app.container.storage
    storage.write_json('EXAMPLE', 'branches.json', [])
    storage.write_json('EXAMPLE', 'business_core.json', empty_core())
    monkeypatch.setattr(subscriptions, 'configured_plan',
                        lambda tenant: get_plan('starter') if tenant == 'EXAMPLE' else None,
                        raising=False)
    return storage


@pytest.mark.parametrize('plan_id', ['starter', 'business', 'scale'])
def test_active_staff_seats_follow_selected_plan(app, monkeypatch, plan_id):
    plan = get_plan(plan_id)
    monkeypatch.setattr(subscriptions, 'configured_plan', lambda tenant: plan, raising=False)
    service = AccountService(app.container.storage)
    service.create_account('EXAMPLE', staff_payload('owner', ['business_owner']))
    for index in range(plan['staff']):
        service.create_account('EXAMPLE', staff_payload(index))
    with pytest.raises(ValueError, match='^staff_account_limit_reached$'):
        service.create_account('EXAMPLE', staff_payload('extra'))
    assert len(service.list_accounts('EXAMPLE')) == plan['staff'] + 1


def test_disabled_staff_can_release_seat_but_not_reactivate_at_cap(starter_resources):
    service = AccountService(starter_resources)
    first = service.create_account('EXAMPLE', staff_payload(1))
    service.create_account('EXAMPLE', staff_payload(2))
    service.update_account('EXAMPLE', first['id'], {'active': False})
    service.create_account('EXAMPLE', staff_payload(3))
    with pytest.raises(ValueError, match='^staff_account_limit_reached$'):
        service.update_account('EXAMPLE', first['id'], {'active': True})
    assert service.get_account('EXAMPLE', first['id'])['active'] is False


def test_staff_downgrade_keeps_password_permissions_and_deactivation_available(app, monkeypatch):
    service = AccountService(app.container.storage)
    accounts = [service.create_account('EXAMPLE', staff_payload(index)) for index in range(3)]
    monkeypatch.setattr(subscriptions, 'configured_plan', lambda tenant: get_plan('starter'), raising=False)
    service.update_account('EXAMPLE', accounts[0]['id'], {'permissions': ['view_costs'], 'active': True})
    service.update_account('EXAMPLE', accounts[1]['id'], {'password': 'New-resource-test-password'})
    service.update_account('EXAMPLE', accounts[2]['id'], {'active': False})
    with pytest.raises(ValueError, match='^staff_account_limit_reached$'):
        service.update_account('EXAMPLE', accounts[2]['id'], {'active': True})


def test_concurrent_staff_creation_cannot_claim_same_last_seat(starter_resources):
    service = AccountService(starter_resources)
    service.create_account('EXAMPLE', staff_payload('existing'))
    start = Barrier(2)

    def create(index):
        start.wait(timeout=5)
        try:
            return service.create_account('EXAMPLE', staff_payload(index))['id']
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = list(workers.map(create, [1, 2]))
    assert outcomes.count('staff_account_limit_reached') == 1
    assert len(service.list_accounts('EXAMPLE')) == 2


@pytest.mark.parametrize('first_document', ['branches.json', 'business_core.json'])
@pytest.mark.parametrize('active', [True, False])
def test_location_cap_combines_branches_and_service_areas(starter_resources, first_document, active):
    core = empty_core()
    core['locations'] = [dict(remote_location(1), active=active)]
    if first_document == 'branches.json':
        starter_resources.write_json('EXAMPLE', 'branches.json', [branch(1)])
        with pytest.raises(ValueError, match='^location_limit_reached$'):
            starter_resources.write_json('EXAMPLE', 'business_core.json', core)
        assert starter_resources.read_json('EXAMPLE', 'business_core.json')['locations'] == []
    else:
        starter_resources.write_json('EXAMPLE', 'business_core.json', core)
        with pytest.raises(ValueError, match='^location_limit_reached$'):
            starter_resources.write_json('EXAMPLE', 'branches.json', [branch(1)])
        assert starter_resources.read_json('EXAMPLE', 'branches.json') == []


@pytest.mark.parametrize('plan_id', ['starter', 'business', 'scale'])
def test_location_count_uses_each_plans_combined_allowance(app, monkeypatch, plan_id):
    storage = app.container.storage
    storage.write_json('EXAMPLE', 'branches.json', [])
    storage.write_json('EXAMPLE', 'business_core.json', empty_core())
    plan = get_plan(plan_id)
    monkeypatch.setattr(subscriptions, 'configured_plan', lambda tenant: plan, raising=False)
    branches = [branch(index) for index in range(plan['locations'])]
    storage.write_json('EXAMPLE', 'branches.json', branches)
    core = empty_core()
    core['locations'] = [remote_location(1)]
    with pytest.raises(ValueError, match='^location_limit_reached$'):
        storage.write_json('EXAMPLE', 'business_core.json', core)
    storage.write_json('EXAMPLE', 'branches.json', branches[:-1])
    storage.write_json('EXAMPLE', 'business_core.json', core)


def test_location_downgrade_permits_unchanged_edits_and_cleanup(app, monkeypatch):
    storage = app.container.storage
    original = storage.read_json('EXAMPLE', 'branches.json')
    assert len(original) > 1
    monkeypatch.setattr(subscriptions, 'configured_plan', lambda tenant: get_plan('starter'), raising=False)
    edited = [dict(row, name=row['name'] + ' updated') for row in original]
    storage.write_json('EXAMPLE', 'branches.json', edited)
    storage.write_json('EXAMPLE', 'branches.json', edited[:2])
    with pytest.raises(ValueError, match='^location_limit_reached$'):
        storage.write_json('EXAMPLE', 'branches.json', [*edited[:2], branch('extra')])
    core = empty_core()
    core['offerings'] = [{'id': 'service', 'name': 'Consultation', 'type': 'service',
                         'price_type': 'quote', 'active': True}]
    storage.write_json('EXAMPLE', 'business_core.json', core)
    storage.write_json('EXAMPLE', 'branches.json', edited[:1])


def test_concurrent_branch_and_core_imports_share_location_cap(starter_resources):
    start = Barrier(2)
    core = empty_core()
    core['locations'] = [remote_location(1)]

    def write(item):
        start.wait(timeout=5)
        try:
            starter_resources.write_json('EXAMPLE', *item)
            return 'saved'
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(write, [('branches.json', [branch(1)]), ('business_core.json', core)]))
    assert sorted(results) == ['location_limit_reached', 'saved']
    assert (len(starter_resources.read_json('EXAMPLE', 'branches.json')) +
            len(starter_resources.read_json('EXAMPLE', 'business_core.json')['locations'])) == 1


def test_raw_imports_and_dashboard_cannot_bypass_location_cap(client, starter_resources):
    with client.session_transaction() as state:
        set_test_identity(client, state, {'id': 'resource-owner', 'roles': ['business_owner'], 'tenant': 'EXAMPLE'})
    assert client.put('/admin/api/branches', json=[branch(1)]).status_code == 200
    core = empty_core()
    core['locations'] = [remote_location(1)]
    response = client.put('/files/raw/business_core.json', json=core)
    assert response.status_code == 409
    assert response.json['error'] == 'location_limit_reached'
    response = client.put('/files/raw/branches.json', json=[branch(1), branch(2)])
    assert response.status_code == 409
    response = client.put('/admin/api/branches', json=[branch(1), branch(2)])
    assert response.status_code == 409
    assert response.json['error'] == 'location_limit_reached'
    assert len(starter_resources.read_json('EXAMPLE', 'branches.json')) == 1


def test_resource_caps_are_tenant_scoped_and_legacy_tenants_unchanged(starter_resources):
    other = starter_resources.business_root / 'OTHER'
    other.mkdir()
    storage = Storage('OTHER', business_root=starter_resources.business_root)
    storage.write_json('OTHER', 'branches.json', [branch(1), branch(2), branch(3)])
    service = AccountService(storage)
    for index in range(3):
        service.create_account('OTHER', staff_payload(index))
    assert len(service.list_accounts('OTHER')) == 3
    assert starter_resources.read_json('EXAMPLE', 'branches.json') == []
    assert AccountService(starter_resources).list_accounts('EXAMPLE') == []


def test_persisted_plan_selection_enforces_resources_without_test_override(app):
    storage = app.container.storage
    storage.write_json('EXAMPLE', 'branches.json', [])
    subscriptions.select_plan('EXAMPLE', 'starter')
    storage.write_json('EXAMPLE', 'branches.json', [branch(1)])
    core = empty_core()
    core['locations'] = [remote_location(1)]
    with pytest.raises(ValueError, match='^location_limit_reached$'):
        storage.write_json('EXAMPLE', 'business_core.json', core)
    service = AccountService(storage)
    service.create_account('EXAMPLE', staff_payload(1))
    service.create_account('EXAMPLE', staff_payload(2))
    with pytest.raises(ValueError, match='^staff_account_limit_reached$'):
        service.create_account('EXAMPLE', staff_payload(3))
