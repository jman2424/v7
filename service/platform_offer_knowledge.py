"""Live public V7 terms for the configured internal marketing agent only.

Other tenants use their own saved offers. No account, referral code or payment
record is supplied to a public conversation.
"""
from decimal import Decimal, ROUND_HALF_UP
import re
from flask import current_app

from service import referrals, subscriptions
from service.plan_catalog import public_plans, vat_percent
from service.website_destinations import validate


def public_knowledge(tenant):
    if not tenant or not subscriptions.internal_business(tenant):
        return None
    offer = referrals.public_offer(tenant)
    plans = []
    for plan in public_plans():
        regular = plan['monthly_pence']
        first = int((Decimal(regular) * (100-offer['percent']) / 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        setup = int((Decimal(plan['setup_pence']) * (100-offer['joining_setup_percent']) / 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        plans.append({'name':plan['name'], 'standard_monthly':f'£{regular/100:.2f}',
                      'referred_first_month':f'£{first/100:.2f}', 'referred_setup':f'£{setup/100:.2f}'})
    return {**offer, 'authority':'Current platform billing rules; override older imported referral descriptions.',
            'scope':'V7 platform referral programme, not a discount on other businesses products.',
            'eligibility':'New business accepts a valid referral code before its first checkout.',
            'joining_business':'First subscription month discounted; the accepted joining setup percentage applies only to unpaid setup.',
            'referrer':'Reward earned only after verified first subscription payment. Applies to its next subscription month and any unpaid setup.',
            'pause_rule':'Disabling stops new claims. Previously accepted offers and earned rewards retain their saved terms.',
            'payment_action':'Sign in and explicitly accept the referral in Account & security or Subscription before checkout. Chat cannot grant discounts or take payment.',
            'prices':plans}


def public_destinations(tenant, configured):
    if not tenant or not subscriptions.internal_business(tenant):
        return []
    origin = current_app.container.settings.BASE_URL.rstrip('/')
    candidates = [
        {'id':'platform_referrals','label':'Referral settings','url':origin+'/console/account#business-referrals',
         'purpose':'Sign in to share or accept a referral before checkout; this does not apply a discount by itself.'},
        {'id':'platform_plans','label':'Compare subscription plans','url':origin+'/#pricing',
         'purpose':'Compare current platform subscription plans, setup fees and public referral terms.'},
    ]
    for plan in public_plans():
        candidates.append({'id':'platform_plan_'+plan['id'], 'label':'Choose '+plan['name'],
                           'url':origin+'/console/subscription?plan='+plan['id'],
                           'purpose':'Sign in to select this subscription plan, accept a referral if eligible and review checkout; no payment occurs by opening it.'})
    # Explicit owner configuration, including disabled destinations, wins.
    configured_urls = {row['url'] for row in configured}
    configured_ids = {row['id'] for row in configured}
    try:
        return [row for row in validate(candidates) if row['url'] not in configured_urls and row['id'] not in configured_ids]
    except ValueError:
        return []  # Non-public development origins have no customer links.


def public_plan_context(tenant):
    """Current, allowlisted entitlements; legacy unenforced counters are omitted."""
    if not tenant or not subscriptions.internal_business(tenant):
        return None
    return {
        'authority': 'Current platform billing catalogue; do not infer features from plan names.',
        'plans': [{'id': plan['id'], 'name': plan['name'],
                   **{key: plan[key] for key in ('locations', 'staff_accounts', 'analytics', 'api_access', 'onboarding')}}
                  for plan in public_plans()],
        'usage': 'AI processing credit is separately prepaid; none is included. There is no fixed message allowance. Usage depends on the selected model and tokens.',
        'whatsapp': 'WhatsApp requires provider setup. Business phone numbers and Meta/provider messaging fees are separate costs.',
        'vat_percent': vat_percent(),
    }


def automatic_offer_answer(question, knowledge):
    """Exact live policy remains available if paid AI is unavailable."""
    import re
    if not knowledge or not re.search(r'\b(?:referr?al|refer|referrals|invitar|recomendar|parrainage|parrainer)\b|إحالة|الإحالات',question,re.I):
        return None
    if not knowledge['enabled']:
        return 'New referrals are paused. Previously accepted offers and earned rewards keep their saved terms. Sign in to Account & security to view your referral.'
    setup = 'no setup fee (£0)' if knowledge['joining_setup_percent']==100 else f"{knowledge['joining_setup_percent']}% off unpaid setup"
    return (f"A new referred business receives {knowledge['percent']}% off its first subscription month and {setup}. "
            'It must accept a valid referral code before its first checkout. '
            f"The referrer earns {knowledge['percent']}% off its next subscription month and {knowledge['sponsor_setup_percent']}% off any unpaid setup after the first subscription payment is verified. "
            'AI credit is separate. Existing setup payments are not refunded and discounts do not stack. '
            'Sign in to Account & security or Subscription to share or accept a referral.')


def automatic_plan_answer(question, knowledge, history=None):
    """Render actual billing plans for narrow marketing-plan questions only."""
    if not knowledge or re.search(r'\b(cancel|refund|referr?al|refer)\b', question, re.I):
        return None
    # A factual tariff shortcut cannot qualify a customer or recommend a plan.
    # Let the existing single grounded model call use actual needs and limits.
    if re.search(r'\b(?:recommend\w*|suggest\w*|should|suit\w*|best|right for|'
                 r'help me (?:choose|pick|decide)|recomiend\w*|recommand\w*)\b|أنسب|تنصح', question, re.I):
        return None
    plans = public_plans()
    names = '|'.join(re.escape(plan['name']) for plan in plans)
    plan_context = rf'\b(?:{names}|plans?|pricing)\b'
    details = r'\b(?:compar\w*|pric\w*|cost\w*|monthly|fees?|how much|staff|locations?|limits?)\b'
    explicit = bool(re.search(plan_context, question, re.I) and re.search(details, question, re.I))
    explicit = explicit or bool(re.fullmatch(r'\s*(?:show (?:me )?(?:your )?)?(?:plans|pricing)\s*[?.!]?\s*', question, re.I))
    prior = [row['content'] for row in (history or []) if isinstance(row, dict)
             and row.get('role') == 'user' and isinstance(row.get('content'), str)]
    follow_up = (bool(re.search(r'\b(?:which (?:one|plan)|how many (?:staff|locations?))\b', question, re.I))
                 and bool(re.search(r'\b(?:staff|locations?|limits?)\b', question, re.I))
                 and any(re.search(plan_context, text, re.I) and re.search(details, text, re.I)
                         for text in prior[-4:]))
    if not explicit and not follow_up:
        return None
    named = [plan for plan in plans if re.search(r'\b'+re.escape(plan['name'])+r'\b', question, re.I)]
    selected = named or plans
    lines = [f"{plan['name']}: £{plan['monthly_pence']/100:.2f}/month plus £{plan['setup_pence']/100:.2f} one-time setup; "
             f"{plan['locations']} location(s), {plan['staff_accounts']} staff accounts."
             for plan in selected]
    from service.plan_catalog import vat_percent
    tax = f' VAT is charged at {vat_percent()}%.' if vat_percent() else ''
    if not tax and re.search(r'\b(?:vat|tax|taxes)\b', question, re.I):
        tax = ' No VAT is added to the published prices.'
    lines.append('Subscription and setup fees are separate from prepaid AI processing credit. No AI credit is included and there is no fixed message allowance. '
                 'Usage depends on the selected model and tokens. Paid AI pauses when credit cannot cover the next request; there are no automatic overages or recharges.' + tax)
    return '\n\n'.join(lines)
