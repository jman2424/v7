# Complete SQLite runtime backup

`scripts/export_runtime.py` creates a protected offline backup of the current V7
file-based runtime. It does not contact Render, Supabase or an AI provider. Adding
this script to Git does **not** obtain the live data.

## Current Render recovery limitation

V7's current Free Render service has no supported SSH or Dashboard shell access.
The deployed application has no complete runtime export endpoint. Existing owner
exports omit credential/MFA state and parts of analytics and business data. They
cannot replace the backup below.

Do not redeploy, restart, suspend, upgrade or change the live instance to install
this exporter before obtaining its data. Render uses an ephemeral filesystem;
redeploys, restarts and idle spin-down can discard its local changes. Changing the
compute plan also requires a deployment. An ephemeral shell runs a new image,
which does not contain the old instance's mutable files.

For the existing Free instance, use an independently preserved complete backup,
or request Render support to export the current filesystem without replacing the
instance. Support-assisted recovery is not confirmed or guaranteed.

Official references: [Free service limitations](https://render.com/docs/free),
[SSH availability](https://render.com/docs/ssh),
[compute plan changes](https://render.com/docs/compute-plans).

## Preconditions

1. Obtain access to the **actual current source files**, with the runtime's
   configuration environment available. A fresh checkout or new container does
   not contain live state.
2. Stop every application, webhook, scheduler and other writer while keeping the
   source filesystem available. This means quiescing a filesystem-accessible
   runtime, **not** stopping or suspending the current Free Render service.
3. Identify any nondefault file paths. The tool honors `V7_DATA_DIR`,
   `SECURITY_DB_PATH`, `ANALYTICS_DB_PATH`, `CRM_SNAPSHOT_PATH` and `ADMIN_USERS_FILE`.
   Explicit CLI arguments override them. Relative configured paths resolve against
   `--source-dir`, the runtime's actual working directory.
4. Choose a new destination directory under an existing trusted parent, outside
   the application checkout and public/static directories. Keep an independent
   protected copy after export. Do not commit, publish or paste this backup.

The CLI requires `--source-frozen`. This is an explicit assertion that writers
are stopped; the script cannot stop them or prove that they remain stopped.
It compares source inventories/checksums before and after exporting and verifying,
and fails if it detects a change.

## Export

On a filesystem-accessible container whose working directory is `/app`:

```sh
python scripts/export_runtime.py --source-dir /app --out /protected/v7-backup --source-frozen
```

The destination's parent must already exist. The destination must not exist and
must not overlap a source directory/file. Export requires both SQLite databases,
the business tree, the CRM snapshot and the audit file. A configured account
registry must also exist and is included automatically.

For different deployment paths, specify them explicitly:

```sh
python scripts/export_runtime.py --source-dir /app --business-dir /data/business --security-db /data/logs/security.db --analytics-db /data/logs/analytics.db --crm-snapshot /data/logs/crm_snapshot.json --audit-log /data/logs/selfrepair.log --accounts /protected/accounts.json --out /protected/v7-backup --source-frozen
```

The analytics module's default is `/app/logs/analytics.db`, even when `V7_DATA_DIR`
is set. Do not assume both databases moved with the business directory: use their
actual runtime configuration. The default security database is
`logs/security.db` relative to the runtime directory. CRM/audit defaults follow
`V7_DATA_DIR` when supplied.

If an unused runtime has **never created** its default CRM snapshot or default
audit log, use `--no-crm-snapshot` or `--no-audit-log` respectively. The tool refuses
these declarations if the corresponding default file exists or a custom path is
configured. Included/absent optional files are recorded in the protected manifest.
Never use these flags to work around a missing file that previously contained data.

Environment-managed account definitions and provider secrets are not exported.
Retain their existing protected service configuration separately. If an
`ADMIN_USERS_FILE` is used, run with that environment variable or supply `--accounts`.

## Contents and protection

The canonical layout is directly readable by `scripts/prepare_supabase.py`:

```text
v7-backup/
  business/                 all tenant documents and dated versions
  logs/security.db          full SQLite security state
  logs/analytics.db         full SQLite analytics state
  logs/crm_snapshot.json     CRM records, if present
  logs/selfrepair.log        audit records, if present
  accounts.json              ADMIN_USERS_FILE, if configured
  manifest.json              file sizes, SHA-256 checksums and migration counts
```

Tenant account password hashes, enrolled MFA secrets, stored model/action settings
and imported website contents are preserved. Both databases preserve their full
source tables, including transient sessions and challenges. The later migration
deliberately discards transient grants/sessions and expires unfinished signup
requests; the original backup retains those records.

SQLite databases and their committed WAL/rollback journals are first copied into
a protected temporary directory. SQLite's backup API then produces independent
database files with integrity checks and no dependency on a WAL sidecar. SQLite
never opens the original database, so its shared-memory files remain unchanged.
Local `.write-lock.sqlite3` coordination files are excluded from the business tree;
they contain no application records. Generated dated `_snapshot.json` provenance
files remain intact in the backup. The importer counts valid generated metadata
among `document_versions` and preserves its original name and payload. Apply all
five reviewed migrations, including the additive snapshot filename constraint
migration, before import. Other underscore filenames and unexpected metadata
fields, non-UTC timestamps or missing provenance paths stop export for review.

Legacy analytics and CRM may have uppercase tenant IDs while business directory
names preserve case. Preparation maps those references only to a unique existing
business with the same case-insensitive key. Missing or ambiguous businesses stop
preparation; it does not create tenants or merge/discard rows. The manifest records
per-table reconciliation counts. Raw backup files and their source checksums retain
the original IDs; destination verification checks the explicitly reconciled rows.
Preparation also reads each SQLite database and any WAL/SHM/journal files through
a protected temporary copy, checks that the original inventory/checksums stay
unchanged, and removes the staging files after inspection. This does not make a
live, unfrozen source consistent: every writer must still be stopped first.

Before declaring success the script verifies exact file inventory, every checksum,
SQLite integrity, and the existing migration importer's layout/table/document
validation. Unknown source tables/files or malformed JSON stop export for review.
It refuses symlinks and junctions and does not overwrite existing destinations.
An unsuccessful export removes only the new output directory it created.

On POSIX, output directories use mode `0700` and files `0600`. On Windows, an
explicit DACL restricts the output to the executing account, Administrators and
SYSTEM before any private content is written. Failure to apply protection stops
export. Preserve those permissions when transferring the backup. The manifest
contains private filenames/counts and belongs inside the same protected backup.
Checksums detect accidental change; they are not a signature against someone who
can also replace the manifest.

Console output contains counts/status only. Failure output names the exception
class, without database rows, source file paths or credentials.

## Verify and rehearse import

After transferring the protected backup, verify it again:

```sh
python scripts/export_runtime.py --out /protected/v7-backup --verify-only
python scripts/prepare_supabase.py --data-dir /protected/v7-backup
```

Preparation automatically includes the canonical `accounts.json` registry when it
is present, preserving operator passwords and MFA settings even without repeating
`--accounts`. Use `--accounts` for a separately stored registry in a raw frozen
backup. The preparation CLI verifies an existing export manifest before connecting
to PostgreSQL. A successful offline export
does not import data, configure PostgreSQL, or authorize deployment. Continue with
the restore/import verification gates in [SUPABASE_MIGRATION.md](SUPABASE_MIGRATION.md).

## Focused checks

```sh
python -m pytest tests/test_runtime_export.py tests/test_supabase_preparation.py -q
```

Tests use synthetic disposable files. They do not export the live Render runtime.
