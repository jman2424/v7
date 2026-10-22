// A referral link can prefill a customer-requested offer without browser storage.
export function referralCodeFromSearch(search: string): string {
  const code = new URLSearchParams(search).get('ref') || '';
  return /^V7-[A-Fa-f0-9]{32}$/.test(code) ? code.toUpperCase() : '';
}
