"""Live public V7 terms for the configured internal marketing agent only.

Other tenants use their own saved offers. No account, referral code or payment
record is supplied to a public conversation.
"""
from decimal import Decimal, ROUND_HALF_UP
import re
from typing import Any
from flask import current_app

from service import referrals, subscriptions
from service.plan_catalog import public_plans, vat_percent
from service.website_destinations import validate


def setup_support() -> str:
    from service.platform_promotions import public_flags
    flags = public_flags()
    text = ('Your workspace includes the embed snippet and step-by-step guidance; your team or website developer adds and tests it. '
            'Optional one-time assistance costs £100 before applicable tax or an accepted discount. It covers help importing authorised business data, fixing AI answers and improving responses, and guidance for phone, email and WhatsApp setup where included in your plan. Public website imports require your authorisation and review. '
            'A business that sets itself up does not need it. '
            'Website editing, installation by Vertex Seven, custom development and third-party integrations '
            'are not included as a done-for-you implementation service. ')
    if not flags['assistance_enabled']:
        text += ('New setup assistance checkouts are temporarily paused while we work through existing requests. '
                 'You can still subscribe and set up V7 yourself. Already-paid assistance remains supported. ')
    if flags['highstreet_enabled'] and flags['highstreet_public']:
        text += ('MHIGHSTREET gives free optional one-time assistance and 50% off the first subscription month only; '
                 'later months use the normal plan price. ')
    return text + ('Business approval and verified checkout completion are required. '
                   'Accepted discounts do not stack or cover AI credit or provider fees. '
                   'Previously accepted offers keep their saved terms.')


_PRIVATE_CODE_REPLY = ('Promotional codes are checked privately in Subscription before checkout. '
                       'I can explain standard plan prices and optional setup assistance.')


def _withheld_pattern(tenant):
    if not tenant:
        return None
    from flask import has_request_context, request
    cache = request.environ.setdefault('v7.offer_privacy', {}) if has_request_context() else {}
    if tenant in cache:
        return cache[tenant]
    parts = []
    if subscriptions.internal_business(tenant):
        from service.platform_promotions import public_flags
        flags = public_flags()
        parts = [r'(?-i:\bSETUP\b)', r'\b(?:code\s+setup|setup\s+(?:offer|code))\b']
        if not flags['highstreet_enabled'] or not flags['highstreet_public']:
            parts.append(r'\b(?:m[\s_-]*high[\s_-]*street|muslim[\s_-]*high[\s_-]*street)\b')
        if not flags['referrals_public']:
            parts.append(r'\breferr?als?\b')
    from flask import has_app_context
    if has_app_context():
        try:
            rows = current_app.container.storage.read_json(tenant, 'offers.json')
        except FileNotFoundError:
            rows = []
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict) and row.get('agent_visible') is False:
                    for key in ('code', 'title'):
                        value = row.get(key)
                        if isinstance(value, str) and value.strip():
                            parts.append(r'(?<!\w)'+re.escape(value.strip())+r'(?!\w)')
    cache[tenant] = re.compile('|'.join(parts), re.I) if parts else None
    return cache[tenant]



def private_code_answer(question, tenant):
    """Never confirm a private or retired campaign, even when named by a visitor."""
    pattern = _withheld_pattern(tenant)
    return _PRIVATE_CODE_REPLY if pattern and pattern.search(question) else None


def automatic_setup_answer(question: str, tenant: str, *, all_offers: bool = False) -> str | None:
    """Only public, active promotions can be described to customers."""
    if not tenant or not subscriptions.internal_business(tenant):
        return None
    private = private_code_answer(question, tenant)
    if private:
        return private
    from service.platform_promotions import public_flags
    flags = public_flags()
    if re.search(r'\bMHIGHSTREET\b', question, re.I) and flags['highstreet_public'] and flags['highstreet_enabled']:
        return setup_support()
    if not all_offers:
        return None
    rows = []
    if flags['highstreet_enabled'] and flags['highstreet_public']:
        rows.append(setup_support())
    if flags['referrals_public'] and referrals.public_offer(tenant)['enabled']:
        rows.append('A referral offer is available. Ask for its current eligibility and reward terms.')
    return '\n\n'.join(rows) or 'No public promotional offers are currently advertised. Check any code privately in Subscription before checkout.'



def public_setup_policy(tenant):
    if not tenant or not subscriptions.internal_business(tenant):
        return None
    return {'question': 'What do setup guidance, optional assistance and assistance codes include?',
            'answer': setup_support(), 'answer_complete': True,
            'authority': 'Current platform service scope and billing offers override older imported implementation claims.'}


def public_knowledge(tenant):
    if not tenant or not subscriptions.internal_business(tenant):
        return None
    from service.platform_promotions import public_flags
    if not public_flags()['referrals_public']:
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
            'joining_business':'First subscription month discounted; the accepted joining assistance percentage applies only to unpaid assistance.',
            'referrer':'Reward earned only after verified first subscription payment. Applies to its next subscription month and any unpaid assistance.',
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
         'purpose':'Compare current platform subscription plans and assistance fees.'},
    ]
    from service.platform_promotions import public_flags
    if not public_flags()['referrals_public']:
        candidates = [row for row in candidates if row['id'] != 'platform_referrals']
    for plan in public_plans():
        candidates.append({'id':'platform_plan_'+plan['id'], 'label':'Choose '+plan['name'],
                           'url':origin+'/console/subscription?plan='+plan['id'],
                           'purpose':'Sign in to select this subscription plan and review checkout; no payment occurs by opening it.'})
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
                   'channels': plan['channel_summary'],
                   **{key: plan[key] for key in ('locations', 'staff_accounts', 'analytics', 'api_access', 'onboarding')}}
                  for plan in public_plans()],
        'usage': 'AI processing credit is separately prepaid; none is included. There is no fixed message allowance. Usage depends on the selected model and tokens.',
        'whatsapp': 'WhatsApp and calls are included only in Scale; email starts at Business. WhatsApp requires provider setup. Business phone numbers and Meta/provider messaging fees are separate costs.',
        'implementation_support': setup_support(),
        'vat_percent': vat_percent(),
    }


def automatic_offer_answer(question, knowledge):
    """Exact live policy remains available if paid AI is unavailable."""
    import re
    if not knowledge or not re.search(r'\b(?:referr?al|refer|referrals|invitar|recomendar|parrainage|parrainer)\b|إحالة|الإحالات',question,re.I):
        return None
    if not knowledge['enabled']:
        return 'New referrals are paused. Previously accepted offers and earned rewards keep their saved terms. Sign in to Account & security to view your referral.'
    setup = 'no assistance fee (£0)' if knowledge['joining_setup_percent']==100 else f"{knowledge['joining_setup_percent']}% off unpaid assistance"
    return (f"A new referred business receives {knowledge['percent']}% off its first subscription month and {setup}. "
            'It must accept a valid referral code before its first checkout. '
            f"The referrer earns {knowledge['percent']}% off its next subscription month and {knowledge['sponsor_setup_percent']}% off any unpaid assistance after the first subscription payment is verified. "
            'AI credit is separate. Existing assistance payments are not refunded and discounts do not stack. '
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
    lines = [f"{plan['name']}: £{plan['monthly_pence']/100:.2f}/month, billed monthly, "
             f"plus £{plan['setup_pence']/100:.2f} optional one-time assistance; "
             f"{plan['channel_summary']}; {plan['locations']} location(s), {plan['staff_accounts']} staff accounts."
             for plan in selected]
    from service.plan_catalog import vat_percent
    tax = f' VAT is charged at {vat_percent()}%.' if vat_percent() else ''
    if not tax and re.search(r'\b(?:vat|tax|taxes)\b', question, re.I):
        tax = ' No VAT is added to the published prices.'
    lines.append('Subscription and assistance fees are separate from prepaid AI processing credit. No AI credit is included and there is no fixed message allowance. '
                 'Usage depends on the selected model and tokens. Paid AI pauses when credit cannot cover the next request; there are no automatic overage charges. Optional £5 automatic recharge requires explicit authorisation, a monthly purchase cap and platform availability.' + tax)
    from service.platform_promotions import public_flags
    if not public_flags()['assistance_enabled']:
        lines.append('New setup assistance checkouts are temporarily paused. You can still subscribe and set up V7 yourself.')
    lines.append('One-time assistance is an optional add-on and is not needed to activate; your team or website developer installs the widget.')
    return '\n\n'.join(lines)


def current_promotion_reply(tenant: str, text: str) -> str:
    """Withhold private/retired codes from stale FAQs, history and model output."""
    pattern = _withheld_pattern(tenant)
    if pattern and isinstance(text, str) and pattern.search(text):
        return _PRIVATE_CODE_REPLY
    return text


def current_promotion_knowledge(tenant: str, knowledge: dict[str, Any]) -> dict[str, Any]:
    """Withhold private promotions from every public knowledge source."""
    pattern = _withheld_pattern(tenant)
    if not pattern:
        return knowledge
    return {key: value for key, value in knowledge.items() if not pattern.search(str(value))}


def current_promotion_history(tenant, history):
    """Do not reintroduce a private offer through an older conversation turn."""
    pattern = _withheld_pattern(tenant)
    return [row for row in history if not pattern or not pattern.search(str(row))]
