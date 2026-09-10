"""Provision or disable a management account without storing plaintext passwords."""
import argparse
import base64
import getpass
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from werkzeug.security import generate_password_hash

    from retrieval.storage import Storage
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email")
    parser.add_argument("--file", default=os.getenv("ADMIN_USERS_FILE", "management-users.json"))
    parser.add_argument("--role", choices=["platform_admin", "business_owner"], default="business_owner")
    parser.add_argument("--tenant")
    parser.add_argument("--disable", action="store_true")
    args = parser.parse_args()
    path = Path(args.file).resolve()
    if any(path.is_relative_to(root) for root in [ROOT / "business", ROOT / "dashboard", Path.cwd() / "business"]):
        parser.error("Accounts must be stored outside business and dashboard directories")
    data = json.loads(path.read_text()) if path.exists() else {"users": []}
    email = args.email.strip().lower()
    if not email or len(email) > 254:
        parser.error("A valid account identifier is required")
    existing = next((user for user in data["users"] if user["email"] == email), None)
    if args.disable:
        if not existing:
            parser.error("Account does not exist")
        existing["disabled"] = True
    else:
        if args.role == "business_owner":
            if not args.tenant or not Storage(args.tenant).tenant_dir().is_dir():
                parser.error("Business owners require an existing --tenant")
        password = getpass.getpass("New password (at least 16 characters): ")
        if len(password) < 16 or len(password) > 1024 or password != getpass.getpass("Confirm password: "):
            parser.error("Passwords must match and contain 16–1024 characters")
        secret = getpass.getpass("Authenticator TOTP secret (required for a production platform admin): ").strip().upper()
        if secret:
            try:
                base64.b32decode(secret + "=" * (-len(secret) % 8))
            except ValueError:
                parser.error("Invalid Base32 authenticator secret")
        record = {"email": email, "role": args.role, "tenant": args.tenant,
                  "password_hash": generate_password_hash(password), "totp_secret": secret}
        if existing:
            existing.clear()
            existing.update(record)
        else:
            data["users"].append(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    print("Account updated. Set ADMIN_USERS_FILE to this registry before starting the app.")


if __name__ == "__main__":
    main()
