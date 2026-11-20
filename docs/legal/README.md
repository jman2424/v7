# Legal drafts awaiting review

Nothing in this folder is in force or is legal advice. Each file is proposed wording
prepared from how the product actually behaves, for a UK-qualified solicitor to review.

| File | What it is | Where it takes effect once approved |
|---|---|---|
| [acceptable-use-policy-draft.md](acceptable-use-policy-draft.md) | Activity-based business eligibility policy. | Pasted into *Platform administration → Applications*; shown at `/acceptable-use`. |
| [data-import-and-sync-terms-draft.md](data-import-and-sync-terms-draft.md) | Schedule covering imports and automatic synchronisation. | Summarised at `/terms`; its version is recorded with every source a customer authorises. |
| [business-customer-data-processing-draft.md](business-customer-data-processing-draft.md) | Proposed processing instructions, safeguards and assistance for customer conversations. | Attach the completed schedule to the customer agreement after approval. |

## Details to settle before publication

- Confirm the supplier's legal identity, business address and contact details. If the supplier is a UK limited company, verify its registered name, number, office and jurisdiction against its registration before publishing. [GOV.UK company website requirements](https://www.gov.uk/running-a-limited-company/signs-stationery-and-promotional-material)
- Reconcile the signed schedule with the providers, processing locations, transfer safeguards, retention periods and backup expiry actually used by the customer. Check the public privacy notice against those same facts.
- The repository has no root software licence. The rights holder must decide whether to grant reuse rights. The bundled Bricolage Grotesque and Hanken Grotesk fonts have their own licence files in [the fonts directory](../../dashboard/static/fonts/). Retain those notices with redistributed copies.

## Questions for the reviewing solicitor

1. Is refusing service on the listed *activities* lawful and adequately distinguished
   from discrimination on a protected characteristic under the Equality Act 2010,
   including indirect discrimination? Is the mixed-activity assessment workable?
2. Does the rejection and reconsideration procedure give enough information without
   creating a duty to give detailed reasons?
3. Are the proposed additional excluded activities (lending, tobacco, weapons)
   appropriate, and is "primary activity" defined tightly enough?
4. Is the permission captured in the product (a ticked statement, kept permanently with
   its exact wording, the account and role, time, domain, what it covers, the terms
   version, and when and by whom it was withdrawn) sufficient evidence of consent to
   access a customer's systems, including under the Computer Misuse Act 1990?
5. Is the split between customer-owned material and third-party material clear enough,
   and is the warranty in clause 4 of the import terms enforceable?
6. Does the proposed customer data processing schedule cover the enabled channels, including personal data in messages, transcripts and follow-up requests? Which import-specific instructions should be added?
7. Which sub-processors must be named, and what international-transfer wording is
   needed for the AI tools mentioned in clause 7.4?
8. Reading a customer's own website (section 6 of the import terms) is now built: on
   the owner's recorded permission, public pages only, at most 20 pages and once a
   day, following `robots.txt`, never signing in. Is section 6 sufficient, having
   regard to the Computer Misuse Act 1990, copyright and database right, and the
   website's own terms?
9. Control of the website rests on the customer's declaration (clause 6.6). Should a
   technical proof of control be required before reading, and is the indemnity
   proposed in section 12 appropriate where the declaration is false?
10. Public pages can contain personal data (for example named staff). Does reading and
    repeating it need Article 28 terms and a privacy-notice change now (clause 6.7)?
11. Withdrawal deletes the stored pages, but dated back-ups keep earlier copies until
    the workspace is closed (clauses 6.8 and 11.2). Is that acceptable, or must
    back-ups be purged on withdrawal?
12. How long should permission records be kept after a workspace closes (clause 11.3)?
