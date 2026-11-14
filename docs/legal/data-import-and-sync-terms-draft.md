# Data Import and Synchronisation Terms — proposed schedule to the service agreement

**Status: DRAFT for UK legal review. Not legal advice and not yet in force.**
Version identifier recorded in the product: `data-import-sync-terms-2026-11-draft-2`
(`service/business_sync.py`). Change that identifier whenever this wording changes, so
each customer's recorded permission points at the text they actually accepted.

Changes since draft 1: new section 6 (reading your website), a fuller description of
the permission record in 2.1 and 2.5, withdrawal in 2.4 and 11.1, and later sections
renumbered.

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

## 2. Your permission

2.1 We only read a Source after you (or a person you have authorised, acting through
your account) confirm in the product that we may, by ticking a statement shown at that
moment. Nothing is read before that. For each permission we keep a record of: the exact
statement that was ticked; the account that ticked it and its role; the date and time;
the kind of Source and its website domain; the categories of information covered; and
the version of these terms that applied.

2.2 You may authorise these kinds of Source: (a) files and documents you give us;
(b) exports from your other systems; (c) your online store or business system through
its official interface (for example WooCommerce or Shopify); (d) a data feed your
developer provides; (e) the public pages of a website you control, as described in
section 6.

2.3 For each connected Source the product shows whether automatic updates are on, how
often we check, and what is being read. You can change these settings at any time.

2.4 **Withdrawing permission.** You can withdraw permission for any Source at any time
in the product, without giving a reason, and it is as easy as giving it. Your
permission otherwise continues until the agreement ends. Section 11.1 says what happens
when you withdraw.

2.5 **The permission record.** Permission records are added to and marked as ended;
they are not edited or deleted while your workspace exists, including after you
withdraw, so that both of us can show what was authorised and when. You can see your
records in the product. If you change the terms a permission was given under, or
connect the same Source again, a new record is made and the earlier one is kept.

2.6 A permission covers only the Source and website domain named in it. If your
website moves to a different address we stop reading until you give permission for the
new address.

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

## 6. Reading your website

6.1 **What you are asked to confirm.** Before we read your website the product shows
this statement, and we read nothing unless the owner of the business account ticks it:

> "I confirm that this business controls the website named here and has the right to
> reuse what is published on it, and I give Vertex Seven permission to read its public
> pages, when I ask and on the schedule shown, to keep this business's AI assistant up
> to date. I understand that only public pages are read, that the website's robots
> rules are followed, that nothing is changed on the website, and that I can withdraw
> this permission at any time by disconnecting."

6.2 **What we read.** Only the website address saved in your business profile, and only
pages on that same address. We read the text of ordinary public web pages: at most 20
pages on each occasion, each limited in size. We do not read pages on any other
website, and we do not follow links that lead away from yours.

6.3 **How we read it.** Our reader (a) identifies itself by name
(`V7-Business-Knowledge-Importer`) rather than pretending to be a person's browser;
(b) first reads your website's `robots.txt` file and does not open any page that file
asks automated readers to avoid; (c) never signs in, submits a form, accepts a prompt,
solves a challenge or otherwise gets around a restriction; (d) does not change, order
or submit anything; and (e) stops if your website cannot be reached, in which case
your assistant keeps what was read before.

6.4 **When we read it.** When you give permission, whenever you ask in the product,
and, if you leave the daily option on, once a day. We do not read your website more
often than that on a schedule.

6.5 **How the text is used.** The text is stored in your workspace only, and is used
only so that your assistant can answer your customers. Information you have entered or
approved in the product (products, prices, answers, policies) takes priority over
website text. Text that appears to be an instruction to an AI system rather than
business information is left out.

6.6 **You must control the website.** You confirm that the website is yours or that
its owner has authorised you to give this permission. We rely on that confirmation; we
may ask you for evidence of control, and we may refuse or stop reading a website where
we reasonably doubt it. *[For legal review: whether a technical proof of control (for
example a code placed on the website) should be required before reading. The product
does not require one today.]*

6.7 **Other people's material and personal information on your website.** Clause 4.2
applies to your website. If your public pages show personal information (for example
named staff and their work contact details) you confirm that you are entitled to
publish it and to let your assistant repeat it. *[For legal review: lawful basis and
transparency for personal data that appears on a customer's public pages; whether this
makes us a processor for that data and requires Article 28 terms now.]*

6.8 **Withdrawal.** When you withdraw this permission we stop reading your website at
once, we delete the copy of its pages held for your assistant, and your assistant no
longer answers from it. Copies in dated back-ups expire under clause 11.2.

## 7. How we process imported information

7.1 Imported information is checked before it is used: required details must be
present, prices must be valid, and text that appears to be an instruction to an AI
system rather than business information is set aside for a person to review.

7.2 Changes that are unusual (a large price change, many products disappearing, or a
change that conflicts with something you edited in Vertex Seven) are held for your
approval rather than applied automatically. An empty or failed response from a Source
never deletes your information.

7.3 We keep a history of what was imported, from which Source and when, and you can
undo a recent import from the product while the affected information is unchanged.

7.4 **Tools we use.** Our staff may use AI software tools, which may include Anthropic's
Claude and OpenAI's Codex, to help convert your material into the format the product
needs. Material is given to such a tool only for that purpose; the output is checked by
the product's validation and by a person before it is applied; and those tools are not
given your account credentials or standing access to your workspace.

7.5 *[For legal review: list the sub-processors actually used at signing (expected: the
hosting provider, the database provider, the AI model provider or providers and the
implementation tools in 7.4) with locations and transfer safeguards, and confirm how
customers are told about changes.]*

## 8. Security and confidentiality

8.1 Access keys and tokens you give us for a Source are encrypted in storage, are never
shown again in the product after you enter them, and are used only to read that Source.

8.2 Your Business Information, Source credentials and permission records are kept
separate from every other customer's. We treat non-public information from your
Sources as confidential.

8.3 If we become aware of unauthorised access to your Source credentials we will tell
you without undue delay so that you can revoke them.

## 9. Intellectual property

9.1 You keep all rights in your Business Information. You grant us a non-exclusive
licence to copy, store, adapt and use it solely to provide the service to you.

9.2 We do not use your Business Information to provide services to anyone else.
*[For legal review: add the agreed position on use for improving AI models.]*

## 10. Accuracy and timing

10.1 Synchronisation is periodic, not instantaneous. The product shows when each Source
last updated and warns when it has not updated recently. Between updates your assistant
may give information that has since changed in your Source.

10.2 We do not promise automatic synchronisation for a Source that has no reliable
connection method; for those, section 1.3 applies.

## 11. Retention, withdrawal and termination

11.1 When you disconnect a Source, which withdraws your permission for it, we stop
reading it immediately and delete the stored access details. Products, prices and
answers already imported stay in your workspace until you remove them, because you may
have edited them since. The stored copy of website pages is different: it is deleted
on withdrawal (clause 6.8).

11.2 Import history, including the copy kept so that a change can be undone, is kept
for *[period to be agreed. Product behaviour today: undo copies for the ten most recent
changes; history entries and dated back-ups of workspace documents until the workspace
is closed]*.

11.3 Permission records are kept for as long as your workspace exists and then for
*[period to be agreed, long enough to answer a later dispute about what was
authorised]*.

11.4 When the agreement ends we delete or return your Business Information in line
with the main agreement and privacy notice. *[For legal review: align with the
retention schedule in the privacy policy.]*

## 12. Liability

*[For legal review: confirm that the limits and exclusions in the main service
agreement apply to this schedule, and the allocation of responsibility where a customer
authorises a Source or website they were not entitled to share (clauses 4 and 6.6),
including an indemnity for third-party claims arising from that.]*
