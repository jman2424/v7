# Operations and Maintenance

## Overview
Operators must configure and monitor their backup schedule, test restoration and
verify the actual deployed service. Local tools do not obtain live provider data.

---

## SQLite backups and recovery

Before changing the existing live runtime, read [live backup requirements](LIVE_BACKUP.md).
Pushing code does not obtain its mutable data. The existing `export_runtime.py`
creates frozen, complete exports for migration; its format is documented there.
The commands below use a separate routine backup format and require access to
the actual runtime files. They do not contact Render or Supabase.

Run as the service operator with the runtime's actual environment. Configure
`ANALYTICS_DB_PATH`, `SECURITY_DB_PATH`, `ADMIN_USERS_FILE`, `CRM_SNAPSHOT_PATH`
and `AUDIT_LOG_PATH` explicitly when they differ from the local defaults. In
particular, the analytics runtime's default can be `/app/logs/analytics.db`;
do not infer its location from `V7_DATA_DIR`. The tool requires both databases.
`V7_DATA_DIR/business` is the existing persistent business default;
`BUSINESS_DATA_ROOT` overrides it. Relative configured paths resolve against
`--root`, which must name the application's working directory.

Pause all writers when a consistent recovery point across files, databases and
accounts is required. Choose a new protected directory outside business data:

```sh
python scripts/platform_backup.py create /protected/v7-backups/2026-09-30 --root /app
python scripts/platform_backup.py verify /protected/v7-backups/2026-09-30
```

Backups include business files and versions, consistent snapshots of both SQLite
databases, a configured account registry and any existing CRM/audit files. Private
state held only in environment configuration is not copied; preserve it in the
provider's protected secrets system. Review the manifest to confirm the expected
optional files are present. A missing historical CRM/audit file must be
investigated, not treated as evidence that the runtime never used it.

The checksummed manifest is written last. Duplicate manifest keys, case-colliding
names, traversal, Windows device names and symlink/junction paths fail validation.
Checksums detect corruption; they do not authenticate attacker-supplied archives.
Restore only trusted backups. Size/file limits bound verification. Files contain
customer records, password hashes and MFA secrets: use restrictive Windows ACLs
or POSIX permissions, encrypted off-host storage, multiple versions and a
monitored schedule. No schedule or off-host destination is created by these tools.

For recovery, preserve current data for investigation, stop all writers and
review the backup's accounts for compromise. Use a clean business destination
when recovering from malicious edits: additional destination files are retained.

```sh
python scripts/platform_backup.py restore /protected/v7-backups/2026-09-30 --root /app --service-stopped
```

The flag is an operator assertion, not a process detector. Restore validates
every target and both verified SQLite byte streams before writing. Sessions,
OAuth grants, trusted-device proofs, OIDC login states and unfinished MFA
challenges are cleared in the prepared security
database before replacement, so a later file failure cannot revive saved
credentials. Unverified/incomplete registrations expire with credentials cleared;
verified pending approvals remain. Existing authenticator replay high-water marks
and used MFA-code markers are retained, together with newer login failures.
Persistent OIDC account links remain. Previous SQLite WAL sidecars are removed
after database replacement.
Users must sign in and reconnect OAuth integrations afterward. Writes are atomic
per file, not one transaction across the platform. Keep the service stopped after
an interrupted restore until recovery and checks are complete.
If the existing security database is unreadable, preserving its MFA replay state
is impossible: the tool fails before changing live files. Preserve it for
investigation and configure a clean security-database destination for recovery.

For tenant-only file snapshots:

```sh
python scripts/snapshot_backup.py --tenant EXAMPLE --date 2026-09-30
python scripts/restore_snapshot.py --tenant EXAMPLE --snapshot backups/2026-09-30/EXAMPLE.tar.gz
python scripts/restore_snapshot.py --tenant EXAMPLE --snapshot backups/2026-09-30/EXAMPLE.tar.gz --apply
```

The preview lists counts/names without document contents. `--apply` removes files
absent from the snapshot; review it and take a complete backup first. Archives must
contain this tenant's regular files only; empty, duplicate, oversized and unsafe
paths are rejected before changes. Restoration accepts at most 2,000 archive
entries, 16 MiB per file, 64 MiB of file contents and an 80 MiB compressed or
decompressed archive, including data after the tar footer. Audit preparation
must succeed before a write.
These snapshots exclude databases/accounts and cannot replace a complete backup.

## PostgreSQL recovery

The file backup/restore commands explicitly refuse `V7_STORAGE_BACKEND=postgres`.
Offline verification of an existing SQLite backup remains available. PostgreSQL
stores business documents, accounts, sessions, MFA, billing, CRM, audits and
analytics in `v7_private`; local files do not represent that live state. Follow
[the PostgreSQL migration/runtime requirements](SUPABASE_MIGRATION.md) and use the
database provider's verified backup/recovery process. Rehearse restoration with
the private schema and forced RLS intact, preserve secrets separately, and revoke
restored sessions, OAuth grants and unfinished login/registration challenges
before reconnecting clients. No PostgreSQL backup or restore is performed by
these local scripts.

---

## Website knowledge imports

Imports remain on the configured HTTPS host, use a validated public unicast IP
with hostname TLS verification, and disable redirects and proxies. Each page is
limited to 512 KiB, a 5-second body read and a 10-second socket-fetch deadline;
an import visits at most six pages. DNS resolution uses the operating system's
resolver timing and is outside the socket deadline.

---

## WhatsApp setup

Use `WHATSAPP_PROVIDER_MODE=meta`, `twilio`, or `both` to select accepted
callbacks; `auto` preserves existing integrations. Optional
`WHATSAPP_META_TENANT_MAP_JSON` and `TWILIO_WHATSAPP_TENANT_MAP_JSON` assign
recipient IDs to tenants separately. Blank values fall back to the legacy
`WHATSAPP_TENANT_MAP_JSON`; an explicit `{}` allows no recipients for that
provider. A map takes priority over the default phone ID/number.

Authenticated owners can inspect `/admin/api/integrations?tenant=EXAMPLE` for
their company's recipients, provider mode, missing setting names, activation,
subscription and voice readiness. This checks local configuration only and
does not contact a provider. Credentials and other tenants' recipients are
excluded. Meta voice downloads require the official Graph API host. Voice
messages are transcribed in memory and receive text replies; provider signatures,
recipient routing and the durable deduplication inbox remain required.

---

## Privacy notices and account exports

`GET /admin/api/privacy?tenant=EXAMPLE` returns the authorized company's
`settings`, document `revision`, `draft`, `missing_details` and `policy_url`.
Reading requires `business_settings.read`; owners and platform admins with
`business_settings.write` may save with
`PUT /admin/api/privacy?tenant=EXAMPLE` and `{ "settings": {...}, "revision":
"..." }`. A stale revision returns 409. Edits remain available before tenant
activation, require the management session and CSRF protection, and audit field
names without recording policy text. The document is not available through the
raw file editor.

The public `/privacy?tenant=EXAMPLE` notice publishes only validated controller,
contact, retention and lawful-basis details. Platform `/privacy` details use the
optional `V7_PRIVACY_*` settings in `env.example`. Business details are separate.
Incomplete or invalid details are clearly marked drafts. Retention fields do not
delete records or enable a cleanup job. Processors are described from local
configuration; provider contracts, locations and transfer arrangements still
require the operator's review.

`/cookies` describes the configured session-cookie lifetime and the effective
management session limit, the optional 30-day trusted-device proof and 180-day
cookie choice/language preference. `GET /auth/privacy/export` requires the
current account session and exports only that account's identity, safe trusted
device metadata and valid preference values. It excludes business records,
customer conversations, other users and credentials; it is not a complete data
access export.

---

## Log Rotation
- Manual rotation: `python scripts/rotate_logs.py`
- Automatic rotation handled by `app/logging_setup.py` (5MB per file, 3 backups).

`LOG_DIR` overrides the existing `V7_DATA_DIR/logs` default; `AUDIT_LOG_PATH`
overrides the audit file location. Logging excludes exception messages/source
lines, including cached traceback text; configured credentials and encoded
credential-bearing query values are redacted. Gunicorn access logs omit query
strings, referers and user agents. If historical Meta verification callbacks
were logged with query strings, inspect protected old logs and rotate
`WHATSAPP_VERIFY_TOKEN` if present. Do not paste these logs or backup contents.

## Dependency and CI security

Runtime pins include patched PyJWT 2.15.0 and oauthlib 4.0.0; the development
formatter is pinned to Black 26.3.1. The canonical requirements also pin setuptools
83.0.0, replacing vulnerable preinstalled packaging tooling in CI, Docker and
native installers. Maintainer advisories document the fixes:
[PyJWT payload recursion](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-42vr-xj54-vc7v),
[OAuthlib PKCE timing](https://github.com/oauthlib/oauthlib/security/advisories/GHSA-xpv3-w29h-x7cv),
[Black cache path validation](https://github.com/psf/black/security/advisories/GHSA-3936-cmfr-pm3m),
[Black action version input](https://github.com/psf/black/security/advisories/GHSA-v53h-f6m7-xcgm).
[Setuptools release history](https://setuptools.pypa.io/en/latest/history.html#v83-0-0)
documents the source-distribution exclusion fix for PYSEC-2026-3447.
`requirement.txt` is a compatibility alias for the canonical `requirements.txt`.

Security CI audits resolved Python runtime/development dependencies and the
frontend lockfile. Third-party Actions use verified full commit IDs; TruffleHog
uses an immutable official image digest and scans checked-out files offline.
The scanner disables its container's network access and provider verification;
its wrapper logs bounded detector/file/line metadata without matched values.
Keep these pins under review as upstream versions and advisories change.
Checkout credentials are not persisted. Release tags are validated before
shell use; source artifacts include tracked files only. CI also runs both
widget SDK origin/source security tests. CodeQL and dependency review still
depend on the repository's GitHub feature availability.

---

## Monitoring
- Heartbeat pings `/health` endpoint every 60s.
- Synthetic probes in `monitoring/probes.py` simulate chat flows to catch broken routes or invalid catalog entries.

---

## Service Level Objectives
| Metric | Target |
|---------|--------|
| Availability | 99.9% |
| Median Response Time | < 1.2s |
| Max Error Rate | < 1% |
| Recovery Time Objective | 15 min |

---

## Recovery Steps
1. Stop writers, preserve current data and restore a verified trusted complete backup.
2. Restart Gunicorn worker: `systemctl restart app` or via Render console.
3. Run self-repair: `python scripts/validate_catalog.py`.

---

## Summary
Operational health depends on periodic validation, backups, and log reviews.  
Restoration changes persistent data and requires the stopped-writer procedure above.
