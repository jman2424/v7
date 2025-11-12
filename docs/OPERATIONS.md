# Operations and Maintenance

## Overview
Operational tools keep tenant data consistent and ensure uptime through health monitoring and scheduled backups.

---

## Backups
- Run `python scripts/snapshot_backup.py` to archive all tenant JSONs under `backups/DATE/`.
- Restores use `scripts/restore_snapshot.py` with dry-run diff preview.

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
