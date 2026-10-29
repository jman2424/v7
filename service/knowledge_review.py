"""On-demand, deterministic review of configured public business knowledge.

No provider requests, network fetches, customer history or automatic edits. This
is an actionable checklist, not a semantic audit or a readiness certification.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re

from service.faq_integrity import faq_groups
from service.sales_playbook import SalesPlaybookValidationError, validate_sales_playbook
from service.website_knowledge import current_website_knowledge

DOCUMENTS = ('store_info.json', 'overrides.json', 'catalog.json', 'faq.json',
             'business_core.json', 'website_knowledge.json')
MAX_ROWS = 1000
MAX_ISSUES = 30


def review_documents(documents, *, now=None):
    now = now or datetime.now(timezone.utc)
    issues, complete = [], True

    def issue(code, message, section, severity='review'):
        nonlocal complete
        if len(issues) >= MAX_ISSUES:
            complete = False
            return
        issues.append({'code': code, 'message': message, 'section': section, 'severity': severity})

    def document(name, expected):
        value = documents.get(name, expected())
        if not isinstance(value, expected):
            issue('invalid_document', f'{name} has an unsupported format. Review the saved source.',
                  'faqs' if name == 'faq.json' else 'agent', 'error')
            return expected()
        return value

    def rows(value, label, section):
        nonlocal complete
        if not isinstance(value, list):
            issue('invalid_collection', f'{label} has an unsupported format.', section, 'error')
            return []
        if len(value) > MAX_ROWS:
            complete = False
            issue('review_limit', f'Only the first {MAX_ROWS} {label} were reviewed.', section)
        if any(not isinstance(row, dict) for row in value[:MAX_ROWS]):
            issue('invalid_entries', f'{label} contains entries that cannot be reviewed.', section, 'error')
        return [row for row in value[:MAX_ROWS] if isinstance(row, dict)]

    def public(row):
        return row.get('active') is not False and row.get('public') is not False

    def text(value):
        return isinstance(value, str) and bool(value.strip())

    profile = document('store_info.json', dict)
    overrides = document('overrides.json', dict)
    raw_playbook = overrides.get('sales_playbook', {})
    try:
        playbook = validate_sales_playbook(raw_playbook)
    except SalesPlaybookValidationError:
        playbook = {}
        issue('playbook_invalid', 'Review the saved playbook; its settings cannot be validated.', 'agent', 'error')
    if not text(profile.get('name')):
        issue('identity_missing', 'Add the business name so the assistant can identify the company.', 'profile')
    if not text(profile.get('about')) and not text(playbook.get('business_focus')):
        issue('business_focus_missing', 'Describe what the business does and the needs it helps customers with.', 'profile')
    if not text(profile.get('email')) and not text(profile.get('phone')):
        issue('contact_missing', 'Add a public email address or phone number for human assistance.', 'profile')
    if not isinstance(raw_playbook, dict) or not raw_playbook.get('primary_goal'):
        issue('goal_review', 'Review the conversation goal and qualification questions for this business.', 'agent', 'suggestion')

    catalog = document('catalog.json', dict)
    products = []
    categories = rows(catalog.get('categories', []), 'catalogue categories', 'catalog')
    for category in categories:
        items = rows(category.get('items', []), 'catalogue items in a category', 'catalog')
        remaining = MAX_ROWS - len(products)
        if len(items) > remaining:
            complete = False
            issue('review_limit', f'Only the first {MAX_ROWS} catalogue items were reviewed.', 'catalog')
        products.extend(items[:remaining])
        if len(products) >= MAX_ROWS:
            if category is not categories[-1]:
                complete = False
            break
    products = [item for item in products if public(item)]
    if any(isinstance(item.get('price'), (float, int)) and not isinstance(item.get('price'), bool)
           for item in products) and not re.fullmatch(r'[A-Z]{3}', str(catalog.get('currency') or '')):
        issue('catalog_currency_missing', 'Set the catalogue currency before the assistant can safely quote these prices.',
              'catalog', 'error')
    core = document('business_core.json', dict)
    offerings = [row for row in rows(core.get('offerings', []), 'native offerings', 'catalog') if public(row)]
    if not products and not offerings:
        issue('offerings_missing', 'Add active products or services if the assistant should recommend or price them.', 'catalog', 'suggestion')

    faqs = document('faq.json', list)
    if len(faqs) > MAX_ROWS:
        complete = False
        issue('review_limit', f'Only the first {MAX_ROWS} FAQs were reviewed.', 'faqs')
    groups = faq_groups(faqs[:MAX_ROWS])
    if any(not isinstance(row, dict) or public(row) and (
            not text(row.get('q')) or not text(row.get('a'))) for row in faqs[:MAX_ROWS]):
        issue('faq_invalid_entries', 'Some FAQ entries need a nonempty question and answer. They are not usable facts.', 'faqs', 'error')
    conflicting = sum(len(group['answers']) > 1 for group in groups)
    duplicates = sum(len(group['indexes']) > 1 and len(group['answers']) == 1 for group in groups)
    for group in groups:
        if len(group['indexes']) <= 1:
            continue
        positions = ', '.join(str(index + 1) for index in group['indexes'][:8])
        topic = ' '.join(group['question'].split())[:160]
        if len(group['answers']) > 1:
            issue('faq_conflict', f'FAQ entries {positions} give different answers to “{topic}”. '
                  'These answers are withheld from automatic FAQ responses. Keep one current, approved answer.',
                  'faqs', 'error')
        else:
            issue('faq_duplicate', f'FAQ entries {positions} repeat “{topic}”. Keep one copy to simplify future edits.',
                  'faqs', 'suggestion')
    if not groups:
        issue('faqs_missing', 'Add approved answers to common questions and important customer policies.', 'faqs', 'suggestion')

    knowledge = document('website_knowledge.json', dict)
    current = current_website_knowledge(knowledge, profile.get('website'))
    page_count = len(current.get('pages', []))
    if text(profile.get('website')):
        if not page_count:
            issue('website_refresh', 'Import or refresh the configured website; no usable pages match it.', 'website')
        else:
            try:
                fetched = datetime.fromisoformat(str(current.get('fetched_at', '')).replace('Z', '+00:00'))
                if fetched.tzinfo is None or fetched > now + timedelta(minutes=5):
                    raise ValueError('invalid_timestamp')
                if now - fetched > timedelta(days=30):
                    issue('website_stale', 'The website import is over 30 days old. Review and refresh it after website changes.', 'website')
            except (ValueError, TypeError):
                issue('website_date_unknown', 'The website import date cannot be verified. Refresh it to establish freshness.', 'website')

    return {
        'generated_at': now.isoformat(), 'complete': complete,
        'scope': 'Configured public facts only. Exact FAQ conflicts are checked; semantic contradictions and live website changes are not verified.',
        'counts': {'active_catalogue_items_reviewed': len(products), 'active_native_offerings_reviewed': len(offerings),
                   'faq_topics_reviewed': len(groups), 'conflicting_faq_topics': conflicting,
                   'duplicate_faq_topics': duplicates, 'usable_imported_pages': page_count},
        'issues': issues,
    }


def review(storage, tenant):
    # The caller establishes identity, tenant and permissions. One batch reads
    # existing documents, with no new cache/authority or calls on the chat path.
    return review_documents(storage.read_json_many(tenant, DOCUMENTS))
