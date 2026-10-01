# Operations and Maintenance

## Overview
Operational tools keep tenant data consistent and ensure uptime through health monitoring and scheduled backups.

---

## Backups

- Run `python scripts/snapshot_backup.py --tenant EXAMPLE` for a single tenant's
  documents under `backups/DATE/EXAMPLE.tar.gz`. These filesystem tools honor
  `V7_DATA_DIR` and refuse PostgreSQL runtime mode.
- Inspect a restore with `python scripts/restore_snapshot.py --tenant EXAMPLE
  --snapshot backups/DATE/EXAMPLE.tar.gz`. Inspection is the default; `--apply`
  performs the reviewed changes. Output and audit records omit document contents.
- Restore accepts one nonempty tenant archive: traversal, another tenant, links,
  special files, duplicate names and conflicting file/directory paths fail before
  any tenant changes. Limits are 2,000 entries, 16 MiB per file, 64 MiB total file
  content and 80 MiB of compressed/decompressed archive data. Corrupt gzip footers
  are rejected. File replacement is atomic per file; a whole restore is not a
  database transaction and an I/O failure can leave a partially completed restore.
- Archives contain private business/account data. Backup uses protected directory
  permissions and refuses to replace an existing archive. Preserve permissions
  when transferring it. A single-tenant archive does not contain security,
  analytics or CRM databases; use [complete runtime backup](LIVE_BACKUP.md) before
  migration or live cutover. PostgreSQL needs its own verified database backup.

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
Staff may read; owners and platform admins may save with
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
1. Restore last valid snapshot.
2. Restart Gunicorn worker: `systemctl restart app` or via Render console.
3. Run self-repair: `python scripts/validate_catalog.py`.

---

## Summary
Operational health depends on periodic validation, backups, and log reviews.  
All key maintenance actions can be performed safely without touching business data.
