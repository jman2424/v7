Tenant Onboarding Guide
Overview

This document explains how to create and activate a new tenant within the AI Sales Assistant platform.
Each tenant is fully modular and isolated, making it easy to onboard new businesses without changing any shared code.

1️⃣ Create Tenant Folder

Duplicate the example tenant directory:

cp -r business/EXAMPLE business/NEW_TENANT

This will create a new tenant folder with all required JSON files pre-filled.

2️⃣ Edit Core Files
File	Description
catalog.json	Add your full product listings (categories, SKUs, prices).
delivery.json	Define delivery zones, fees, and minimum order values.
branches.json	List all branch locations with coordinates and hours.
store_info.json	Set the business name, about text, certifications, and contact.
branding.json	Add logo URLs, theme colors, and UI assets for dashboards/widgets.
3️⃣ Link Google Sheets (Optional)

If using analytics or data sync:

Share the target Google Sheet with your service account email.

Add the sheet ID in .env as SHEETS_ID.

Enable sync with SHEETS_SYNC=true.

4️⃣ Validate Setup

Run validation to catch schema or SKU issues:

python scripts/validate_catalog.py

This ensures your JSON files follow all required formats and contain valid data.

5️⃣ Deploy Tenant

Commit and push the new tenant folder:

git add business/NEW_TENANT
git commit -m "Add new tenant NEW_TENANT"
git push

Render or your deployment environment will automatically include the new tenant data.

6️⃣ Test Tenant

After deployment, test your bot via /chat_ui or WhatsApp:

Confirm product queries return correct results.

Check delivery fees match postcode rules.

Verify store info responses.

7️⃣ Backups and Snapshots

Nightly snapshots run automatically via scripts/snapshot_backup.py.
You can also trigger manual backups:

python scripts/snapshot_backup.py --tenant NEW_TENANT

To test restore behavior safely:

python scripts/restore_snapshot.py --dry-run

Summary

Every tenant has its own data folder, schema validation, and analytics link.
Once configured, it becomes immediately available to the AI for real-time responses — no code edits required.
