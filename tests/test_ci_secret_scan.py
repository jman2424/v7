"""Scanner reports stay private even on scanner failure or malformed output."""
import json
from types import SimpleNamespace
import subprocess

import pytest

from scripts import ci_secret_scan


_SECRET = 'unit-secret-value-that-must-never-be-printed'


def _finding(**overrides):
    return {'DetectorName': 'OpenAI', 'DetectorType': 800, 'Raw': _SECRET,
            'Redacted': 'partial-unit-secret', 'ExtraData': {'private': _SECRET},
            'VerificationError': 'Request failed for ' + _SECRET,
            'SourceMetadata': {'Data': {'Filesystem': {'file': '/scan/service/example.py', 'line': 14}}},
            **overrides}


def _run(tmp_path, payload=b'', code=0):
    logs, calls, streams = [], [], []
    def runner(command, **kwargs):
        calls.append((command, kwargs))
        streams.extend([kwargs['stdout'], kwargs['stderr']])
        kwargs['stdout'].write(payload)
        kwargs['stderr'].write(('scanner error might contain ' + _SECRET).encode())
        return SimpleNamespace(returncode=code)
    status = ci_secret_scan.run_scan(tmp_path, runner=runner, output=logs.append)
    assert all(stream.closed for stream in streams)
    assert _SECRET not in '\n'.join(logs) and 'partial-unit-secret' not in '\n'.join(logs)
    assert 'VerificationError' not in '\n'.join(logs)
    return status, logs, calls


def test_offline_clean_scan_has_pinned_image_readonly_mount_and_no_verification(tmp_path):
    status, logs, calls = _run(tmp_path)
    assert status == 0 and logs == ['Secret scan: 0 unverified finding(s).']
    command, kwargs = calls[0]
    assert ci_secret_scan.IMAGE in command
    assert '--network=none' in command and '--no-verification' in command
    assert '--results=unverified' in command and '--json' in command and '--fail' in command
    assert next(value for value in command if value.startswith('type=bind,')) == f'type=bind,source={tmp_path.resolve()},target=/scan,readonly'
    assert kwargs['timeout'] == 900 and kwargs['check'] is False


@pytest.mark.parametrize('code', [0, 183])
def test_findings_fail_and_log_only_safe_locations(tmp_path, code):
    status, logs, _ = _run(tmp_path, (json.dumps(_finding()) + '\n').encode(), code)
    assert status == 183
    assert logs == ['Secret scan: 1 unverified finding(s).',
                    'Finding location: {"detector": "OpenAI", "file": "service/example.py", "line": 14}']


@pytest.mark.parametrize('payload', [b'not-json-with-private-unit-data', b'[]\n', b'{}\n',
    b'{"DetectorName":"OpenAI","Raw":"private","Raw":"second"}\n',
    b'{"DetectorName":"OpenAI","Raw":"private","value":NaN}\n',
    b'{"DetectorName":"OpenAI","Raw":"private","value":1e309}\n'])
def test_invalid_report_fails_without_echoing_raw_report(tmp_path, payload):
    status, logs, _ = _run(tmp_path, payload)
    assert status == 1 and logs == ['Secret scan failed: invalid scanner report.']
    assert 'private-unit-data' not in '\n'.join(logs)


def test_scanner_failure_and_missing_expected_findings_fail_closed(tmp_path):
    status, logs, _ = _run(tmp_path, code=1)
    assert status == 1 and logs[-1] == 'Secret scan failed: scanner exit status 1.'
    status, logs, _ = _run(tmp_path, code=183)
    assert status == 1 and logs[-1] == 'Secret scan failed: scanner exit status 183.'


def test_metadata_cannot_echo_sensitive_fields_or_inject_workflow_commands(tmp_path):
    finding = _finding(DetectorName=_SECRET, SourceMetadata={'Data': {'Filesystem': {
        'file': '/scan/' + _SECRET + '.txt', 'line': '::error::' + _SECRET,
    }}})
    status, logs, _ = _run(tmp_path, json.dumps(finding).encode(), 183)
    assert status == 183 and logs[-1] == 'Finding location: {"detector": "type-800"}'
    finding = _finding(DetectorName='::error::' + _SECRET,
        SourceMetadata={'Data': {'Filesystem': {'file': '/scan/../outside.txt', 'line': True}}})
    status, logs, _ = _run(tmp_path, json.dumps(finding).encode(), 183)
    assert status == 183 and 'outside.txt' not in '\n'.join(logs) and '::error::' not in '\n'.join(logs)


def test_timeout_removes_only_its_named_container_and_hides_exception_data(tmp_path):
    logs, calls = [], []
    def runner(command, **kwargs):
        calls.append(command)
        if command[1] == 'run':
            raise subprocess.TimeoutExpired(command, 900, output=_SECRET, stderr=_SECRET)
        return SimpleNamespace(returncode=0)
    assert ci_secret_scan.run_scan(tmp_path, runner=runner, output=logs.append) == 1
    assert logs == ['Secret scan failed: scanner timed out.']
    assert calls[1] == ['docker', 'rm', '--force', calls[0][calls[0].index('--name') + 1]]


def test_scanner_launch_exception_details_are_not_logged(tmp_path):
    logs = []
    def runner(*args, **kwargs):
        raise FileNotFoundError(_SECRET)
    assert ci_secret_scan.run_scan(tmp_path, runner=runner, output=logs.append) == 1
    assert logs == ['Secret scan failed: scanner could not start.']


def test_report_and_metadata_sizes_are_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(ci_secret_scan, '_MAX_LINE', 8)
    assert _run(tmp_path, b'x' * 9)[0] == 1
    monkeypatch.setattr(ci_secret_scan, '_MAX_LINE', 1024 * 1024)
    payload = '\n'.join(json.dumps(_finding()) for _ in range(52)).encode()
    status, logs, _ = _run(tmp_path, payload, 183)
    assert status == 183 and logs[0] == 'Secret scan: 52 unverified finding(s).'
    assert len(logs) == 52 and logs[-1] == 'Additional finding locations omitted: 2.'
