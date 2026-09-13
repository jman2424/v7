"""Start an isolated localhost preview with temporary management accounts.

Run from the repository root: python scripts/run_local.py
Access details are saved under logs/local-preview-access-<port>.txt (git-ignored).
Set LOCAL_PREVIEW_PORT to use a separate preview (default 10000).
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
    port = int(os.getenv("LOCAL_PREVIEW_PORT", "10000"))
    if not 1024 <= port <= 65535:
        raise ValueError("Invalid local preview port")
    preview = ROOT / "logs" / f"local-preview-{port}"
    preview.mkdir(parents=True, exist_ok=True)
    company = preview / "business" / "EXAMPLE"
    if not company.exists():
        shutil.copytree(ROOT / "business" / "EXAMPLE", company)
    password = secrets.token_urlsafe(18)
    accounts = preview / "accounts.json"
    accounts.write_text(json.dumps({"users": [
        {"email": "admin@example.test", "password_hash": generate_password_hash(password), "role": "platform_admin"},
        {"email": "owner@example.test", "password_hash": generate_password_hash(password), "role": "business_owner", "tenant": "EXAMPLE"},
    ]}), encoding="utf-8")
    (ROOT / "logs" / f"local-preview-access-{port}.txt").write_text(
        "Local preview only. Accounts are regenerated on restart.\n"
        f"LOCAL ONLY: http://127.0.0.1:{port}/console/ (company EXAMPLE)\n"
        "Platform admin: admin@example.test\nBusiness owner: owner@example.test\n"
        f"Password for both preview accounts: {password}\n"
        f"Preview edits are stored under {preview.name}/business.\n"
        "Enroll an authenticator after entering the password. These accounts do not work on Render.\n"
        "AI provider, Stripe and WhatsApp are disabled in this local preview.\n", encoding="utf-8")
    os.chdir(preview)
    os.environ["ADMIN_USERS_FILE"] = str(accounts)
    os.environ["ANALYTICS_DB_PATH"] = str(preview / "analytics.db")
    os.environ["SECURITY_DB_PATH"] = str(preview / "security.db")
    os.environ["V7_DATA_DIR"] = str(preview)
    os.environ["CRM_SNAPSHOT_PATH"] = str(preview / "crm_snapshot.json")
    for key in ["OPENAI_API_KEY", "ADMIN_PASSWORD", "ADMIN_USERNAME", "ADMIN_PASSWORD_HASH",
                "TWILIO_AUTH_TOKEN", "TWILIO_WHATSAPP_NUMBER", "STRIPE_API_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_TAX_RATE_ID"]:
        os.environ.pop(key, None)
    from service import analytics_db
    analytics_db.DB_PATH = str(preview / "analytics.db")
    app = create_app({"SECRET_KEY": secrets.token_urlsafe(48), "MODE": "V7", "BUSINESS_KEY": "EXAMPLE",
                      "BASE_URL": f"http://127.0.0.1:{port}", "WHATSAPP_TOKEN": "", "WHATSAPP_PHONE_ID": "",
                      "WHATSAPP_APP_SECRET": "", "WHATSAPP_VERIFY_TOKEN": "",
                      "WHATSAPP_TENANT_MAP_JSON": "", "TWILIO_AUTH_TOKEN": "",
                      "ENVIRONMENT": "development", "SESSION_COOKIE_SECURE": False,
                      "TRUST_PROXY_COUNT": 0})
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
