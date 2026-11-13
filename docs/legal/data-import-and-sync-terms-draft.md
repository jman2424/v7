# Data Import and Synchronisation Terms — proposed schedule to the service agreement

**Status: DRAFT for UK legal review. Not legal advice and not yet in force.**
Version identifier recorded in the product: `data-import-sync-terms-2026-11-draft-1`
(`service/business_sync.py`). Change that identifier whenever this wording changes, so
each customer's recorded authorisation points at the text they actually accepted.

"You" means the business customer. "We" means Vertex Seven. "Business Information"
means the information about your business that your assistant uses: products, services,
prices, categories, availability, descriptions, answers to common questions, policies,
offers, opening hours, locations and delivery rules.

---

## 1. What these terms cover

1.1 **Initial import.** To set your assistant up we may copy Business Information from
sources you authorise ("Sources") into your Vertex Seven workspace.

1.2 **Ongoing synchronisation.** Where you connect a Source that supports it and switch
automatic updates on, we will periodically read that Source and update your workspace
so that you do not have to enter the same change twice.

1.3 **Manual refresh.** For a Source that cannot be connected, you may give us an
updated file at any time.

## 2. Your authorisation

2.1 We only read a Source after you (or a person you have authorised, acting through
your account) confirm in the product that we may. We record who confirmed, when, which
Source and website domain, what categories of information, and the version of these
terms that applied.

2.2 You may authorise these kinds of Source: (a) files and documents you give us;
(b) exports from your other systems; (c) your online store or business system through
its official interface (for example WooCommerce or Shopify); (d) a data feed your
developer provides; (e) the public pages of a website you control.

2.3 For each connected Source the product shows whether automatic updates are on, how
often we check (between every 15 minutes and once a day, as you choose), and what is
being synchronised. You can change these settings or disconnect at any time.

2.4 Your authorisation continues until you disconnect the Source, withdraw it by
writing to us, or the agreement ends.

## 3. What we access and what we do not

3.1 We request the narrowest access the Source allows: read-only access to product
information wherever the Source offers it. We do not change anything in your Source.

3.2 We do not seek access to your customers' personal data, order history or payment
information through a Source, and you agree not to include such information in any
file or feed you give us for import. If we find personal data in imported material we
may delete it and will tell you.

3.3 *[For legal review: if a future feature needs customer personal data (for example
order-status answers), it will require a separate written data-processing agreement
under UK GDPR Article 28 and a documented lawful basis before it is enabled.]*

## 4. Your responsibilities

4.1 You confirm that you own the information in each Source, or are otherwise entitled
to let us copy and use it for your assistant, and that doing so does not breach a
contract or infringe anyone's rights.

4.2 **Your own material and other people's material are different.** Information you
created or commissioned is yours to share. A website or system can also contain
material owned by others (for example supplier photographs or text, or reviews written
by your customers). You must only authorise us to import material you have the right
to reuse.

4.3 You are responsible for the accuracy of the information in your Sources. You should
review what is imported; the product shows you a preview before the first import and
before unusual changes are applied.

## 5. What this agreement does not permit

5.1 Nothing in this agreement authorises us, and we will not attempt, to: (a) get
around a login, paywall, technical restriction or anti-automation measure; (b) read a
website or system you do not control; (c) act contrary to the published terms of the
service that hosts your Source; or (d) break any law.

5.2 If a Source's own terms forbid the access you have asked us to make, you must not
authorise it, and we may refuse or stop it.

## 6. How we process imported information

6.1 Imported information is checked before it is used: required details must be
present, prices must be valid, and text that appears to be an instruction to an AI
system rather than business information is set aside for a person to review.

6.2 Changes that are unusual (a large price change, many products disappearing, or a
change that conflicts with something you edited in Vertex Seven) are held for your
approval rather than applied automatically. An empty or failed response from a Source
never deletes your information.

6.3 We keep a history of what was imported, from which Source and when, and you can
undo a recent import from the product while the affected information is unchanged.

6.4 **Tools we use.** Our staff may use AI software tools, which may include Anthropic's
Claude and OpenAI's Codex, to help convert your material into the format the product
needs. Material is given to such a tool only for that purpose; the output is checked by
the product's validation and by a person before it is applied; and those tools are not
given your account credentials or standing access to your workspace.

6.5 *[For legal review: list the sub-processors actually used at signing (expected: the
hosting provider, the database provider, the AI model provider or providers and the
implementation tools in 6.4) with locations and transfer safeguards, and confirm how
customers are told about changes.]*

## 7. Security and confidentiality

7.1 Access keys and tokens you give us for a Source are encrypted in storage, are never
shown again in the product after you enter them, and are used only to read that Source.

7.2 Your Business Information and Source credentials are kept separate from every
other customer's. We treat non-public information from your Sources as confidential.

7.3 If we become aware of unauthorised access to your Source credentials we will tell
you without undue delay so that you can revoke them.

## 8. Intellectual property

8.1 You keep all rights in your Business Information. You grant us a non-exclusive
licence to copy, store, adapt and use it solely to provide the service to you.

8.2 We do not use your Business Information to provide services to anyone else.
*[For legal review: add the agreed position on use for improving AI models.]*

## 9. Accuracy and timing

9.1 Synchronisation is periodic, not instantaneous. The product shows when each Source
last updated and warns when it has not updated recently. Between updates your assistant
may give information that has since changed in your Source.

9.2 We do not promise automatic synchronisation for a Source that has no reliable
connection method; for those, section 1.3 applies.

## 10. Retention, disconnection and termination

10.1 When you disconnect a Source we stop reading it immediately and delete the stored
access details. Information already imported stays in your workspace until you remove
it.

10.2 Import history, including the copy kept so that a change can be undone, is kept
for *[period to be agreed. Product behaviour today: undo copies for the ten most recent
changes; history entries until the workspace is closed]*.

10.3 When the agreement ends we delete or return your Business Information in line
with the main agreement and privacy notice. *[For legal review: align with the
retention schedule in the privacy policy.]*

## 11. Liability

*[For legal review: confirm that the limits and exclusions in the main service
agreement apply to this schedule, and the allocation of responsibility where a customer
authorises a Source they were not entitled to share (clause 4).]*
