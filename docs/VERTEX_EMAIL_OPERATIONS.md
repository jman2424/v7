# Vertex Seven email roles

| Address | Purpose | Delivery |
| --- | --- | --- |
| verification@vertex-seven.com | V7 account verification, password resets and account email changes | Application sending identity in Resend; replies go to support |
| info@vertex-seven.com | General business enquiries and website enquiries | Dedicated Resend inbox, reached through its IONOS forward |
| support@vertex-seven.com | Customer assistance and replies to account emails | Dedicated Resend inbox, reached through its IONOS forward |
| marketing@vertex-seven.com | Marketing correspondence and social-account registration email | Dedicated Resend inbox, reached through its IONOS forward |

## Account notifications

Production uses the existing Resend HTTPS delivery adapter and secret API key.
Set `SMTP_FROM=Vertex Seven Accounts <verification@vertex-seven.com>` and
`SMTP_REPLY_TO=Vertex Seven Support <support@vertex-seven.com>` in the service
environment. Keep `SMTP_HOST`, `SMTP_USERNAME` and `SMTP_PASSWORD` configured as
described in [REGISTRATION.md](REGISTRATION.md). Never place the API key in this
document, browser code or a committed environment file.

The sender applies to signup codes, password-reset codes and account email-change
codes. Changing this identity does not change account authentication, code expiry,
MFA or rate limits. Account notifications remain separate from marketing email.

## Inbox access and routing

Open **Resend → Inboxes** and select General enquiries, Customer support, or
Marketing and social accounts. Use the matching inbox to compose or reply so its
business address is the sender and correspondence remains in the correct thread.

The domain's existing incoming MX records remain at IONOS. Each new business
address forwards to the receiving address shown on its matching Resend inbox.
These receiving addresses are configuration data: copy the exact current value
from Resend when restoring a forward. Do not replace the root MX records with
Resend's records; existing mailboxes still receive mail at IONOS.

Three receiving inboxes fit the current Resend plan. The verification sender does
not require a fourth inbox. Its replies are directed to the support inbox.
Use marketing@vertex-seven.com as the email when setting up social profiles.

## Acceptance checks

- Confirm the sending domain is verified in Resend.
- Verify the public `/auth/registration` status advertises the verification
  sender and enabled delivery without disclosing credentials.
- With explicit approval, send clearly labelled setup tests to each public
  address and confirm they arrive in the matching Resend inbox through IONOS.
- Keep test messages free of working authentication codes and customer data.
- Run the registration-mail tests after changing sender or reply handling.
