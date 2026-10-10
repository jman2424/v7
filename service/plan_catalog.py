"""Server-owned monthly V7 prices and included allowances (GBP before VAT)."""

PLANS = {
    'starter': {
        'id': 'starter', 'name': 'Starter', 'audience': 'Small businesses',
        'monthly_pence': 9900, 'setup_pence': 14900,
        'website_conversations': 300, 'whatsapp_messages': 500,
        'ai_budget_pence': 500, 'locations': 1, 'staff': 2, 'staff_accounts': 2,
        'analytics': 'Basic', 'api_access': 'Basic', 'onboarding': 'Basic',
    },
    'business': {
        'id': 'business', 'name': 'Business', 'audience': 'Growing businesses',
        'monthly_pence': 19900, 'setup_pence': 29900,
        'website_conversations': 1000, 'whatsapp_messages': 2000,
        'ai_budget_pence': 2000, 'locations': 5, 'staff': 5, 'staff_accounts': 5,
        'analytics': 'Advanced', 'api_access': 'Standard', 'onboarding': 'Assisted',
    },
    'scale': {
        'id': 'scale', 'name': 'Scale', 'audience': 'Busy businesses',
        'monthly_pence': 34900, 'setup_pence': 59900,
        'website_conversations': 3000, 'whatsapp_messages': 5000,
        'ai_budget_pence': 5000, 'locations': 15, 'staff': 15, 'staff_accounts': 15,
        'analytics': 'Advanced', 'api_access': 'Standard', 'onboarding': 'Priority',
    },
}


def get_plan(plan_id):
    if not isinstance(plan_id, str) or plan_id not in PLANS:
        raise ValueError('invalid_subscription_plan')
    return dict(PLANS[plan_id])


def public_plans():
    return [dict(plan) for plan in PLANS.values()]
