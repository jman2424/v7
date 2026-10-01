"""Run the pinned offline scanner without putting secret values into CI logs."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import uuid

IMAGE = ('ghcr.io/trufflesecurity/trufflehog:3.97.6@sha256:'
         'cc1a591e83fec7bf56f64c15beaaa5d8e3d179a4165a03a087d07165296ef7df')
_MAX_LINE = 1024 * 1024
_MAX_REPORT = 64 * 1024 * 1024
_METADATA_LIMIT = 50


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_key')
        result[key] = value
    return result


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('invalid_number')
    return number


def _sensitive_strings(value):
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, dict):
        return [text for child in value.values() for text in _sensitive_strings(child)]
    if isinstance(value, list):
        return [text for child in value for text in _sensitive_strings(child)]
    return []


def _metadata(finding):
    sensitive = [text for key in ('Raw', 'RawV2', 'Redacted', 'ExtraData', 'VerificationError')
                 for text in _sensitive_strings(finding.get(key))]
    def safe(text):
        return not any(secret in text for secret in sensitive)
    detector = finding.get('DetectorName')
    if (not isinstance(detector, str) or not re.fullmatch(r'[A-Za-z0-9 _().-]{1,80}', detector)
            or not safe(detector)):
        detector_type = finding.get('DetectorType')
        detector = f'type-{detector_type}' if type(detector_type) is int and 0 <= detector_type <= 100000 else 'unknown'
    result = {'detector': detector}
    source = finding.get('SourceMetadata')
    data = source.get('Data') if isinstance(source, dict) else None
    filesystem = data.get('Filesystem') if isinstance(data, dict) else None
    if isinstance(filesystem, dict):
        file = filesystem.get('file')
        if isinstance(file, str) and file.startswith('/scan/') and len(file) <= 512 and safe(file):
            path = PurePosixPath(file[len('/scan/'):])
            if (not path.is_absolute() and '..' not in path.parts and path.parts
                    and all(re.fullmatch(r'[A-Za-z0-9 _().-]{1,120}', part) for part in path.parts)):
                result['file'] = path.as_posix()
        line = filesystem.get('line')
        if type(line) is int and 1 <= line <= 1000000000:
            result['line'] = line
    return result


def _findings(report):
    count, metadata, size = 0, [], 0
    report.seek(0)
    while True:
        line = report.readline(_MAX_LINE + 1)
        if not line:
            break
        size += len(line)
        if len(line) > _MAX_LINE or size > _MAX_REPORT:
            raise ValueError('report_too_large')
        if not line.strip():
            continue
        finding = json.loads(line, object_pairs_hook=_unique_object, parse_float=_finite_float,
                             parse_constant=lambda value: _finite_float(value))
        if not isinstance(finding, dict) or 'DetectorName' not in finding or 'Raw' not in finding:
            raise ValueError('invalid_finding')
        count += 1
        if len(metadata) < _METADATA_LIMIT:
            metadata.append(_metadata(finding))
    return count, metadata


def run_scan(workspace, *, runner=subprocess.run, output=print, timeout=900):
    """The injected runner makes unit checks independent of Docker and providers."""
    try:
        workspace = Path(workspace).resolve(strict=True)
        if not workspace.is_dir():
            raise ValueError('invalid_workspace')
    except (OSError, ValueError, TypeError):
        output('Secret scan failed: workspace is unavailable.')
        return 1
    name = 'v7-secret-scan-' + uuid.uuid4().hex
    command = ['docker', 'run', '--rm', '--name', name, '--network=none',
               '--mount', f'type=bind,source={workspace},target=/scan,readonly', IMAGE,
               'filesystem', '/scan', '--json', '--no-verification', '--results=unverified', '--fail']
    # TemporaryFile creates private files and removes them on every normal/error exit.
    with tempfile.TemporaryFile(mode='w+b') as stdout, tempfile.TemporaryFile(mode='w+b') as stderr:
        try:
            result = runner(command, stdout=stdout, stderr=stderr, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            try:
                runner(['docker', 'rm', '--force', name], stdout=stdout, stderr=stderr, timeout=10, check=False)
            except (OSError, subprocess.TimeoutExpired):
                pass
            output('Secret scan failed: scanner timed out.')
            return 1
        except OSError:
            output('Secret scan failed: scanner could not start.')
            return 1
        try:
            count, metadata = _findings(stdout)
        except (ValueError, UnicodeError, RecursionError):
            output('Secret scan failed: invalid scanner report.')
            return 1
        output(f'Secret scan: {count} unverified finding(s).')
        for location in metadata:
            output('Finding location: ' + json.dumps(location, ensure_ascii=True, sort_keys=True))
        if count > len(metadata):
            output(f'Additional finding locations omitted: {count-len(metadata)}.')
        if result.returncode not in {0, 183} or (result.returncode == 183 and not count):
            status = result.returncode if type(result.returncode) is int else 'unknown'
            output(f'Secret scan failed: scanner exit status {status}.')
            return 1
        return 183 if count else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', default=os.getenv('GITHUB_WORKSPACE') or str(Path.cwd()))
    return run_scan(parser.parse_args().workspace)


if __name__ == '__main__':
    raise SystemExit(main())
