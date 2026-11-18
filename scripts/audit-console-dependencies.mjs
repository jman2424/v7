// Audit every console dependency with one expiring, build-only risk exception.
import {readFileSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import {fileURLToPath, pathToFileURL} from 'node:url';

export const advisory = 'https://github.com/advisories/GHSA-fc5q-39xc-vjpf';
export const expires = '2026-12-18T00:00:00Z';

export function reviewAudit(audit, lockfile, now = new Date()) {
  if (audit?.error || audit?.auditReportVersion !== 2 || !audit.vulnerabilities
      || typeof audit.vulnerabilities !== 'object' || Array.isArray(audit.vulnerabilities)) {
    throw new Error('npm audit returned an error or an unsupported report');
  }
  const findings = Object.entries(audit.vulnerabilities);
  if (!findings.length) return {exceptions: 0};
  if (!Number.isFinite(+now) || +now >= Date.parse(expires)) {
    throw new Error('The temporary picomatch exception expired; review the upstream fix');
  }
  for (const [name, finding] of findings) {
    if (finding.name !== name || !Array.isArray(finding.nodes) || !finding.nodes.length) {
      throw new Error('Unrecognised dependency finding');
    }
    for (const node of finding.nodes) {
      const dependency = lockfile?.packages?.[node];
      if (dependency?.dev !== true || (name === 'picomatch' && dependency.version !== '4.0.7')) {
        throw new Error('The exception does not cover runtime dependencies or another picomatch version');
      }
    }
  }
  function covered(name, ancestors = new Set()) {
    const finding = audit.vulnerabilities[name];
    if (!finding || ancestors.has(name) || !Array.isArray(finding.via) || !finding.via.length) return false;
    const next = new Set([...ancestors, name]);
    return finding.via.every(cause => typeof cause === 'string'
      ? covered(cause, next)
      : name === 'picomatch' && cause?.name === 'picomatch' && cause?.url === advisory);
  }
  if (!findings.every(([name]) => covered(name))) {
    throw new Error('An advisory outside the approved picomatch exception was found');
  }
  return {exceptions: findings.length};
}

function main() {
  const root = new URL('../', import.meta.url);
  const docker = readFileSync(new URL('Dockerfile', root), 'utf8');
  const stages = [...docker.matchAll(/^FROM\s+(\S+)/gmi)];
  const ignored = readFileSync(new URL('.dockerignore', root), 'utf8').split(/\r?\n/);
  if (!stages.at(-1)?.[1].startsWith('python:') || !/^CMD\s+\["gunicorn"/m.test(docker)
      || !ignored.includes('frontend/node_modules') || /COPY[^\n]*node_modules/.test(docker)) {
    throw new Error('The production image no longer meets the build-only exception conditions');
  }
  const result = spawnSync(process.platform === 'win32' ? 'npm.cmd' : 'npm',
    ['audit', '--json', '--package-lock-only', '--audit-level=low'],
    {cwd: fileURLToPath(new URL('frontend/', root)), encoding: 'utf8',
      shell: process.platform === 'win32', timeout: 120000, maxBuffer: 10 * 1024 * 1024});
  if (result.error || ![0, 1].includes(result.status)) throw new Error('npm audit could not complete');
  let audit;
  try { audit = JSON.parse(result.stdout); } catch { throw new Error('npm audit did not return valid JSON'); }
  const lockfile = JSON.parse(readFileSync(new URL('frontend/package-lock.json', root), 'utf8'));
  const outcome = reviewAudit(audit, lockfile);
  if (!outcome.exceptions && result.status !== 0) throw new Error('npm audit exited unsuccessfully without covered findings');
  console.log(outcome.exceptions
    ? `Accepted ${outcome.exceptions} build-only findings caused solely by ${advisory}; expires ${expires}. See docs/operations/dependency-exceptions.md. No other advisory is accepted.`
    : 'No known console dependency vulnerabilities found.');
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try { main(); } catch (error) { console.error(error.message); process.exitCode = 1; }
}
