export type SubscriptionLanguage = 'en' | 'es' | 'fr' | 'ar';
export const subscriptionLocales: Record<SubscriptionLanguage, string> = {
  en: 'en-GB', es: 'es-ES', fr: 'fr-FR', ar: 'ar-u-nu-arab'
};

export function subscriptionMoney(pence: number, locale: string): string {
  return new Intl.NumberFormat(locale, {style: 'currency', currency: 'GBP'}).format(pence / 100);
}

export function subscriptionPrice(pence: number, discountPercent = 0, vatPercent = 20) {
  // Prices and discounts are stored in pence; show the same rounded line amount
  // and exclusive VAT as checkout rather than round a floating-point total.
  const beforeVat = Math.round(pence * (100 - discountPercent) / 100);
  const vat = Math.round(beforeVat * vatPercent / 100);
  return {beforeVat, vat, total: beforeVat + vat};
}

export function subscriptionMonth(value: string, locale: string): string {
  if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(value)) return value;
  return new Intl.DateTimeFormat(locale, {month: 'long', year: 'numeric', timeZone: 'UTC'})
    .format(new Date(value + '-01T00:00:00Z'));
}

export function subscriptionCreditAlerts<T extends {code: string}>(alerts: T[]): T[] {
  const requiresReview = alerts.some(alert => ['financial_review_required', 'pricing_unavailable'].includes(alert.code));
  return alerts.filter(alert => alert.code !== 'low_credit' || !requiresReview);
}

const billingErrors: Record<string, string> = {
  invalid_discount_code: 'This discount code is not valid.',
  stripe_discount_invalid: 'The discount could not be applied. Contact your platform administrator.',
  existing_subscription_requires_review: 'Contact your platform administrator to change an existing subscription.',
  paid_setup_plan_requires_review: 'Contact your platform administrator before changing a plan with paid setup.',
  existing_setup_requires_review: 'Contact your platform administrator to review your existing setup.',
  cancel_pending_checkout_before_changing_plan: 'Cancel the pending checkout before choosing another plan.',
  checkout_creation_in_progress: 'A checkout is being prepared. Refresh payments shortly.',
  payment_processing_refresh_soon: 'Your payment is processing. Refresh payments shortly.',
  stripe_setup_required: 'Payments are not connected. Contact your platform administrator.',
  stripe_tax_rate_must_be_20_percent_exclusive: 'Payment tax settings need review by your platform administrator.',
  whatsapp_included_in_subscription: 'WhatsApp is already included in this plan.',
  extra_usage_charges_disabled: 'Extra usage charges are disabled for this plan.',
  implementation_already_paid: 'Setup is already paid.',
  active_platform_subscription_required: 'Activate your platform subscription first.',
  api_charge_not_approved: 'This API charge has not been approved.',
  subscription_already_exists: 'A subscription already exists. Refresh payments.',
  checkout_plan_changed_refresh: 'Your selected plan changed. Refresh payments before continuing.',
  whatsapp_subscription_required: 'An active WhatsApp subscription is required.',
  subscription_required: 'A subscription is required to manage payments.',
  subscription_already_cancelling: 'Renewal is already cancelled. Refresh payments to see the end date.',
  scheduled_subscription_requires_review: 'This subscription has a scheduled change. Contact your platform administrator.',
  subscription_change_requires_review: 'This subscription needs review before its plan can change. Contact your platform administrator.',
  subscription_plan_already_active: 'This is already your current plan.',
  choose_a_completed_month: 'Choose a completed usage month.',
  invalid_api_charge: 'Enter a valid API charge amount.',
  month_already_approved: 'This usage month has already been approved.',
  internal_business_has_no_customer_subscription: 'This internal workspace does not require a customer subscription.',
  unknown_billing_plan: 'Choose an available plan.',
  company_owner_required: 'Only your business owner can manage payments.',
  forbidden: 'You do not have permission for this billing action.',
  unauthorized: 'Your sign-in has expired. Sign in again.',
};

export function subscriptionError(code: string): string {
  return billingErrors[code] || (Object.values(billingErrors).includes(code) ? code :
    'Billing could not be updated. Refresh payments and try again, or contact your platform administrator.');
}
