"""New privacy management endpoints enforce narrowed account permissions."""
import json

from tests import test_platform_security
from tests import test_privacy_settings

platform = test_platform_security.platform
privacy_app = test_privacy_settings.privacy_app


def test_read_only_owner_cannot_change_privacy_policy(privacy_app, platform):
    records = json.loads(platform[1].read_text())
    records['users'][1]['permissions'] = ['business_settings.read']
    platform[1].write_text(json.dumps(records))
    client = privacy_app.test_client()
    csrf = test_platform_security.login(client)
    before = client.get('/admin/api/privacy').json
    assert before['write_allowed'] is False
    response = client.put('/admin/api/privacy', json={
        'settings': test_privacy_settings.valid_settings(), 'revision': before['revision']},
        headers={'X-CSRF-Token': csrf})
    assert response.status_code == 403
    assert client.get('/admin/api/privacy').json == before


def test_owner_without_settings_read_cannot_view_management_policy(privacy_app, platform):
    records = json.loads(platform[1].read_text())
    records['users'][1]['permissions'] = ['offerings.read']
    platform[1].write_text(json.dumps(records))
    client = privacy_app.test_client()
    test_platform_security.login(client)
    assert client.get('/admin/api/privacy').status_code == 403
