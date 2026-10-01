"""Model confirmation remains owner-accessible and enforces narrowed permissions."""
import json
from pathlib import Path

import pytest

from service import model_settings
from service.audit import AuditService
from tests import test_platform_security
from tests.test_model_settings import request

platform = test_platform_security.platform
login = test_platform_security.login


def restrict(platform, index, permissions):
    records = json.loads(platform[1].read_text())
    records['users'][index]['permissions'] = permissions
    platform[1].write_text(json.dumps(records))


def change_model(client, csrf):
    reviewed = request(client, 'POST', '/review', csrf, model='gpt-4o')
    assert reviewed.status_code == 200, reviewed.json
    confirmed = request(client, 'POST', '/confirm', csrf, token=reviewed.json['token'], acknowledge_cost_and_responses=True)
    assert confirmed.status_code == 200, confirmed.json
    return request(client, 'PUT', '', csrf, token=confirmed.json['token'], confirm_and_save=True)


@pytest.mark.parametrize('stage,method,payload', [
    ('/review', 'POST', {'model': 'gpt-4o'}),
    ('/confirm', 'POST', {'token': 'reviewed', 'acknowledge_cost_and_responses': True}),
    ('', 'PUT', {'token': 'confirmed', 'confirm_and_save': True}),
])
def test_read_only_owner_cannot_enter_any_model_change_stage(platform, stage, method, payload):
    restrict(platform, 1, ['business_settings.read'])
    client = platform[0].test_client()
    csrf = login(client)
    assert request(client, method, stage, csrf, **payload).status_code == 403
    assert model_settings.document(platform[0].container.storage, 'ALPHA') == {}


def test_owner_with_settings_write_can_change_model_without_platform_model_permission(platform):
    restrict(platform, 1, ['business_settings.write'])
    client = platform[0].test_client()
    csrf = login(client)
    assert change_model(client, csrf).status_code == 200
    assert model_settings.selected('ALPHA', platform[0].container.storage) == 'gpt-4o'
    assert model_settings.selected('BETA', platform[0].container.storage) is None


def test_restricted_platform_admin_requires_model_write(platform):
    restrict(platform, 0, ['business_settings.write'])
    client = platform[0].test_client()
    csrf = login(client, email='admin@example.test')
    assert request(client, 'POST', '/review', csrf, model='gpt-4o').status_code == 403


@pytest.mark.parametrize('stage', ['review', 'confirm', 'save'])
def test_unknown_fields_are_rejected_before_model_state_changes(platform, stage):
    client = platform[0].test_client()
    csrf = login(client)
    if stage == 'review':
        response = request(client, 'POST', '/review', csrf, model='gpt-4o', tenant='BETA')
    else:
        reviewed = request(client, 'POST', '/review', csrf, model='gpt-4o').json
        if stage == 'confirm':
            response = request(client, 'POST', '/confirm', csrf, token=reviewed['token'], acknowledge_cost_and_responses=True, model='gpt-6-astra')
        else:
            confirmed = request(client, 'POST', '/confirm', csrf, token=reviewed['token'], acknowledge_cost_and_responses=True).json
            response = request(client, 'PUT', '', csrf, token=confirmed['token'], confirm_and_save=True, role='platform_admin')
    assert response.status_code == 400
    assert model_settings.document(platform[0].container.storage, 'ALPHA') == {}
    assert model_settings.document(platform[0].container.storage, 'BETA') == {}


def test_model_change_audit_records_prepared_then_committed_revisions(platform):
    client = platform[0].test_client()
    csrf = login(client)
    assert change_model(client, csrf).status_code == 200
    entries = [json.loads(line) for line in Path('logs/selfrepair.log').read_text().splitlines()]
    events = [entry for entry in entries if entry['action'] == 'ai_model.change']
    assert [entry['extra']['result'] for entry in events] == ['prepared', 'success']
    after = model_settings.document(platform[0].container.storage, 'ALPHA')
    for entry in events:
        assert entry['user'] == 'owner@example.test'
        assert entry['extra']['tenant'] == 'ALPHA'
        assert entry['extra']['source'] == 'API'
        assert entry['before'] == {'model': None}
        assert entry['after'] == {'model': 'gpt-4o'}
        assert entry['extra']['before_revision'] == model_settings.revision({})
        assert entry['extra']['after_revision'] == model_settings.revision(after)
        assert 'generation' not in json.dumps(entry)
        assert 'token' not in json.dumps(entry)


def test_prepared_audit_failure_prevents_model_write(platform, monkeypatch):
    client = platform[0].test_client()
    csrf = login(client)

    def fail(*args, **kwargs):
        raise OSError('private-audit-path-details')

    monkeypatch.setattr(AuditService, 'record', fail)
    result = change_model(client, csrf)
    assert result.status_code == 500
    assert 'private-audit-path-details' not in result.text
    assert model_settings.document(platform[0].container.storage, 'ALPHA') == {}


def test_failed_model_write_never_records_success(platform, monkeypatch):
    client = platform[0].test_client()
    csrf = login(client)
    original = type(platform[0].container.storage)._write_json

    def fail_model(self, tenant, filename, data, **kwargs):
        if filename == model_settings.FILENAME:
            raise OSError('private-storage-details')
        return original(self, tenant, filename, data, **kwargs)

    monkeypatch.setattr(type(platform[0].container.storage), '_write_json', fail_model)
    result = change_model(client, csrf)
    assert result.status_code == 500
    assert 'private-storage-details' not in result.text
    events = [json.loads(line) for line in Path('logs/selfrepair.log').read_text().splitlines()]
    assert [entry['extra']['result'] for entry in events if entry['action'] == 'ai_model.change'] == ['prepared']
    assert model_settings.document(platform[0].container.storage, 'ALPHA') == {}
