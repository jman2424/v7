# Password and account management

Use **Forgot password?** on `/console/` with the company key and account email.
An eligible active account receives a six-digit code through the existing
authenticated email sender. Enter the code in the same browser and choose a
12–256 character password. Codes expire after ten minutes, allow five attempts
and are consumed once. A changed credential snapshot invalidates older codes.
Request limits apply across workers and addresses; public responses do not
confirm whether an account exists. Delivery failures log only the exception type.

Signed-in users can change their own password in **Account & security → Manage
password & accounts**, using their current password. The screen links eligible
owners/operators to the existing company-scoped team account manager for adding
accounts, resetting team passwords and activating/deactivating access.

Password updates preserve roles, company scope, permissions and authenticators.
Existing sessions lose access through credential revision checks, and trusted
devices are revoked. Users sign in again with their new password and authenticator.
Resetting a password does not reset a lost authenticator.

Recovery reuses `registration_requests` in the private security database, with
separate `password_reset` kind and `reset_*` states. PostgreSQL challenge and
credential writes share the existing tenant transaction; operator rows are locked
as well. SQLite uses security and tenant write locks, with atomic document/registry
replacement and credential snapshot checks preventing duplicate consumption.
No migration or new email credentials are required.

Environment-defined and legacy accounts remain operator-configured. Username-only
accounts can change a stored password while signed in; email recovery requires an
actual account email. The system never guesses or adds a recovery email.

Relevant checks: `pytest tests/test_account_passwords.py tests/test_account_management.py
tests/test_registration.py tests/test_registration_mail.py`; native PostgreSQL
recovery scenarios are in `tests/test_postgres_auth_runtime.py` and require the
disposable database fixture. The new screens use English, Spanish, French and Arabic.
