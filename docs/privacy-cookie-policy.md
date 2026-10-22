# Public privacy and cookie policies

The platform notice at `/privacy` is separate from `/privacy?tenant=...` business notices. A complete, validated platform configuration renders `platform_privacy.html`; missing or invalid controller, contact, lawful-basis or retention details retain the existing draft notice. Platform settings never fill a customer's controller details.

Configure the public operator details through the existing `V7_PRIVACY_CONTROLLER`, `V7_PRIVACY_CONTACT_EMAIL`, `V7_PRIVACY_LAWFUL_BASIS`, and `V7_PRIVACY_RETENTION_CRITERIA` environment variables. `V7_PRIVACY_RETENTION_DAYS` is optional. These public notice fields are not a deletion scheduler. There is no new automatic deletion of customer, billing, audit or backup records.

The platform notice covers account administration, enquiries and demonstration chat, customer-business processing roles, AI and conversation context, voice, billing, configured providers, international processing, retention criteria, individual rights and the ICO complaint route. Provider names reflect configuration; this is not a verification of every provider contract, transfer safeguard or operational retention process.

The cookie notice inventories the actual cookies and the chat/checkout session-storage keys. Both policies include direct controls to reopen the existing shared cookie panel. Analytics remains opt-in and restricted to the existing public marketing allowlist. Closing the panel grants no consent, and essential-only or withdrawal preserves account security while removing optional choices. The policy pages do not load Google Analytics.

Business profiles also expose optional TikTok and Linktree fields using the existing validated social-link map. This lets account owners maintain those links alongside Instagram and Facebook without requiring an integration or adding a new credential.

Referral invitations now prefill only from the validated current referral URL. The console no longer reads or writes the optional `v7-referral` session-storage value. Default-workspace redirects retain the URL parameter, and claiming a discount still requires an explicit action through the existing server workflow. Customers can enter a referral code in the claim form if they have navigated away from the invitation URL.

## Release checks

- 91 privacy, permissions, cookie and analytics Python tests passed. A later focused run of the 39 privacy tests passed after removing referral storage.
- Frontend tests cover valid/invalid referral codes, preserving the referral URL through the workspace redirect, consent withdrawal and existing billing/authentication request boundaries.
- All 74 frontend tests passed, Svelte reported zero errors and warnings, and the production frontend build passed.
- Console sign-in, workspace loading, registration loading and owner-console regression suites also passed after keeping referral-link detection self-contained in the console.
- The public templates and preference panel were visually checked through a local preview before deployment.
- Public privacy provider links were checked; OpenAI's official privacy URL rejected automated HTTP access with 403 rather than reporting a missing page.

## Outstanding business disclosure

The operator supplied a controller identity and privacy email but no geographic business address. No address has been invented or published. An online business's geographic-address disclosure is a separate outstanding requirement; publishing a privacy policy is not certification that every business-disclosure or data-protection obligation has been completed.

References: [ICO privacy information](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/individual-rights/the-right-to-be-informed/what-privacy-information-should-we-provide/), [ICO storage/access guidance](https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/guidance-on-the-use-of-storage-and-access-technologies/), [Electronic Commerce Regulations, regulation 6](https://www.legislation.gov.uk/uksi/2002/2013/regulation/6).
