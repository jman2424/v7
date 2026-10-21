"""Disposable Stripe test deployment; never import into the production app."""

import os
from pathlib import Path

if os.getenv("ENVIRONMENT") != "staging":
    raise RuntimeError("Billing sandbox requires ENVIRONMENT=staging")
if not os.getenv("STRIPE_API_KEY", "").startswith(("sk_test_", "rk_test_")):
    raise RuntimeError("Billing sandbox requires a Stripe test key")
if not os.getenv("STRIPE_WEBHOOK_SECRET", "").startswith("whsec_"):
    raise RuntimeError("Billing sandbox requires its own webhook signing secret")
if os.getenv("V7_STORAGE_BACKEND", "sqlite") != "sqlite":
    raise RuntimeError("Billing sandbox must use its disposable SQLite database")
if any(os.getenv(key) for key in ("V7_POSTGRES_DSN", "OPENAI_API_KEY", "SMTP_PASSWORD")):
    raise RuntimeError("Billing sandbox must not use production data, AI or email credentials")
if not os.getenv("BUSINESS_USERS_JSON"):
    raise RuntimeError("Billing sandbox requires a separately provisioned test owner")

from app import create_app  # noqa: E402
from service import tenant_access  # noqa: E402

app = create_app()

with app.app_context():
    if app.container.settings.BUSINESS_KEY != "EXAMPLE":
        raise RuntimeError("Billing sandbox only supports the fictional EXAMPLE tenant")
    # Reserve once, including after paid activation. Never fabricate payment state.
    with tenant_access._database() as db:
        tenant_access._schema(db)
        db.execute("INSERT OR IGNORE INTO managed_businesses(tenant,owner) VALUES (?,NULL)", ("EXAMPLE",))


@app.after_request
def exclude_from_search(response):
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


# An explicit deployment marker contains no credentials or customer information.
Path(os.environ["SECURITY_DB_PATH"]).parent.mkdir(parents=True, exist_ok=True)
app.logger.info("billing_sandbox_ready tenant=EXAMPLE stripe_mode=test")
