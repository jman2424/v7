"""Start an isolated localhost preview with temporary management accounts.

Run from the repository root: python scripts/run_local.py
Access details are saved under logs/local-preview-access.txt (git-ignored).
"""
import json
import os
import secrets
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
deps = ROOT / ".codex-test-deps"
if deps.is_dir():
    sys.path.insert(0, str(deps))

def main():
    from werkzeug.security import generate_password_hash

    from app import create_app
    preview = ROOT / "logs" / "local-preview"
    preview.mkdir(parents=True, exist_ok=True)
    company = preview / "business" / "TARIQ"
    if not company.exists():
        shutil.copytree(ROOT / "business" / "TARIQ", company)
    password = secrets.token_urlsafe(18)
    accounts = preview / "accounts.json"
    accounts.write_text(json.dumps({"users": [
        {"email": "admin@example.test", "password_hash": generate_password_hash(password), "role": "platform_admin"},
        {"email": "owner@example.test", "password_hash": generate_password_hash(password), "role": "business_owner", "tenant": "TARIQ"},
    ]}), encoding="utf-8")
    (ROOT / "logs" / "local-preview-access.txt").write_text(
        "Local preview only. Accounts are regenerated on restart.\n"
        "Login: http://127.0.0.1:10000/admin/login\n"
        "Platform admin: admin@example.test\nBusiness owner: owner@example.test\n"
        f"Password for both preview accounts: {password}\n"
        "Preview edits are stored under logs/local-preview/business.\n"
        "AI provider and WhatsApp are disabled in this local preview.\n", encoding="utf-8")
    os.chdir(preview)
    os.environ["ADMIN_USERS_FILE"] = str(accounts)
    os.environ["ANALYTICS_DB_PATH"] = str(preview / "analytics.db")
    os.environ["SECURITY_DB_PATH"] = str(preview / "security.db")
    os.environ["V7_DATA_DIR"] = str(preview)
    os.environ["CRM_SNAPSHOT_PATH"] = str(preview / "crm_snapshot.json")
    for key in ["OPENAI_API_KEY", "ADMIN_PASSWORD", "ADMIN_USERNAME", "ADMIN_PASSWORD_HASH",
                "TWILIO_AUTH_TOKEN", "TWILIO_WHATSAPP_NUMBER"]:
        os.environ.pop(key, None)
    from service import analytics_db
    analytics_db.DB_PATH = str(preview / "analytics.db")
    app = create_app({"SECRET_KEY": secrets.token_urlsafe(48), "MODE": "V7", "BUSINESS_KEY": "TARIQ",
                      "BASE_URL": "http://127.0.0.1:10000", "WHATSAPP_TOKEN": "", "WHATSAPP_PHONE_ID": "",
                      "WHATSAPP_APP_SECRET": "", "WHATSAPP_VERIFY_TOKEN": "",
                      "WHATSAPP_TENANT_MAP_JSON": "", "TWILIO_AUTH_TOKEN": "",
                      "ENVIRONMENT": "development", "SESSION_COOKIE_SECURE": False,
                      "TRUST_PROXY_COUNT": 0})
    app.run(host="127.0.0.1", port=10000, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
