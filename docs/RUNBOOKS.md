# On-Call Runbooks

## WhatsApp Outage
1. Check `monitoring/heartbeat.log` for failed probes.
2. Verify WhatsApp Cloud API status: https://metastatus.com.
3. Restart webhook worker if stalled: `systemctl restart gunicorn`.
4. Post temporary message on web widget if outage persists.

---

## Google Sheets Quota Exceeded
1. Check error logs for `RateLimitError` from `connectors/sheets.py`.
2. Disable sync temporarily in `.env` (`SHEETS_SYNC=false`).
3. Export analytics CSV manually using `scripts/export_analytics_csv.py`.

---

## 5xx Spike or Latency
1. Inspect `errors.log` for traceback.
2. Run `monitoring/probes.py` to reproduce issue.
3. If catalog validation fails → run `scripts/validate_catalog.py`.
4. Restart service only after verifying disk/log usage.

---

## Self-Repair Alerts
If `services/self_repair.py` emits warnings:
- Review suggested fixes in `/__diag/selfrepair`.
- Apply changes manually, never automatically.
- Commit verified fixes to Git.

---

## Summary
Keep this file open during on-call shifts.  
It contains direct recovery steps for common production issues.
