"""Server-owned monthly V7 prices and included allowances (GBP before VAT)."""

VAT_PERCENT = 20

PLANS = {
    'starter': {
        'id': 'starter', 'name': 'Starter', 'audience': 'Small businesses',
        'monthly_pence': 9900, 'setup_pence': 14900,
        'message_usage_model': 'ai_cost', 'ai_credit_model': 'prepaid', 'usage_billing_mode': 'prepaid',
        'website_conversations': 300, 'whatsapp_messages': 500,
        'ai_budget_pence': 0, 'locations': 1, 'staff': 2, 'staff_accounts': 2,
        'analytics': 'Basic', 'api_access': 'Basic', 'onboarding': 'Basic',
    },
    'business': {
        'id': 'business', 'name': 'Business', 'audience': 'Growing businesses',
        'monthly_pence': 19900, 'setup_pence': 29900,
        'message_usage_model': 'ai_cost', 'ai_credit_model': 'prepaid', 'usage_billing_mode': 'prepaid',
        'website_conversations': 1000, 'whatsapp_messages': 2000,
        'ai_budget_pence': 0, 'locations': 5, 'staff': 5, 'staff_accounts': 5,
        'analytics': 'Advanced', 'api_access': 'Standard', 'onboarding': 'Assisted',
    },
    'scale': {
        'id': 'scale', 'name': 'Scale', 'audience': 'Busy businesses',
        'monthly_pence': 34900, 'setup_pence': 59900,
        'message_usage_model': 'ai_cost', 'ai_credit_model': 'prepaid', 'usage_billing_mode': 'prepaid',
        'website_conversations': 3000, 'whatsapp_messages': 5000,
        'ai_budget_pence': 0, 'locations': 15, 'staff': 15, 'staff_accounts': 15,
        'analytics': 'Advanced', 'api_access': 'Standard', 'onboarding': 'Priority',
    },
}


def get_plan(plan_id):
    if not isinstance(plan_id, str) or plan_id not in PLANS:
        raise ValueError('invalid_subscription_plan')
    return {**PLANS[plan_id], 'website_conversations_enforced': False,
            'whatsapp_messages_enforced': False}


def public_plans():
    return [get_plan(plan_id) for plan_id in PLANS]
