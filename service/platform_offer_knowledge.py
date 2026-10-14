"""Live public V7 terms for the configured internal marketing agent only.

Other tenants use their own saved offers. No account, referral code or payment
record is supplied to a public conversation.
"""
from decimal import Decimal, ROUND_HALF_UP
from flask import current_app

from service import referrals, subscriptions
from service.plan_catalog import public_plans
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
