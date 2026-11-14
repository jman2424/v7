// Plain-language wording for Data Sources & Sync. Codes from the server never reach the page.
export type Source = {
  id: string; kind: string; label: string; status: string; host: string; auto_sync: boolean; auto_apply: boolean;
  interval_minutes: number; last_success: number | null; last_attempt: number | null; problem: string; stale: boolean;
  ownership: Record<string, string>; source_type: string; source_ref: string; tool: string; syncs: boolean; version: number;
};
export type Row = {
  n: number; kind: string; action: string; name: string; category?: string; sku?: string; issues: string[]; include: boolean;
  fields: Record<string, { from: unknown; to: unknown }>; values?: Record<string, unknown>;
};
export type Summary = { source_label?: string; reasons?: string[]; counts?: Record<string, number>; applied?: number };
export type Change = { id: string; state: string; version: number; summary: Summary; rows: Row[]; total_rows: number; can_undo: boolean };
export type HistoryItem = { id: string; state: string; origin: string; summary: Summary; updated: number; version: number; can_undo: boolean };
export type Listing = {
  sources: Source[]; reviews: HistoryItem[]; history: HistoryItem[]; authorisation_statement: string;
  terms_version: string; can_manage: boolean; automatic_updates_running: boolean;
  website_statement: string; website: string; permissions: Permission[];
};
export type Permission = {
  kind: string; domain: string; statement: string; terms_version: string; account: string;
  granted: number; ended: number; end_reason: string; ended_by: string;
};

const KINDS: Record<string, string> = { woocommerce: 'WooCommerce', shopify: 'Shopify', custom_feed: 'your product feed', upload: 'Uploaded file', website: 'your website' };

export function sourceTitle(source: Source): string {
  if (source.kind === 'upload') return 'Uploaded file';
  if (source.kind === 'website') return source.status === 'attention' ? 'Reading your website — needs attention' : 'Reading your website with your permission';
  const name = KINDS[source.kind] || 'your store';
  if (source.status === 'reconnect') return `Connection to ${name} needs renewing`;
  if (source.status === 'attention') return `Connected to ${name} — needs attention`;
  return `Connected to ${name}`;
}

export function sourceProblem(source: Source): string {
  if (source.kind === 'website') {
    if (source.problem === 'website_changed') return 'The website address in your Business profile has changed. Your permission covered the old address only, so nothing is being read. Stop reading this one and add your website again.';
    if (source.status === 'attention') return 'We could not read your website after several tries. Your assistant keeps what was read before. Check the site is online and that its robots rules allow V7.';
    if (source.problem === 'some_lines_skipped') return 'Some text on your website looked like instructions to an AI system rather than business information, so it was left out.';
    if (source.stale) return 'Your website has not been read for a while, so recent changes may not be here yet.';
    return '';
  }
  if (source.status === 'reconnect') return 'Your store connection needs attention. Its access details were refused — disconnect and connect again with new ones.';
  if (source.status === 'attention') {
    if (source.problem === 'legacy_catalogue') return 'Your product list uses an older layout that cannot be synchronised. Ask your platform operator to convert it.';
    return 'Your store connection needs attention. We could not reach it after several tries; we will keep your current information until it works again.';
  }
  if (source.problem === 'some_items_skipped') return 'Some product updates couldn’t be imported because a name or price was missing.';
  if (source.stale) return 'This has not updated for a while, so recent changes in your store may not be here yet.';
  return '';
}

export function agoText(seconds: number | null, now = Date.now() / 1000): string {
  if (!seconds) return 'Not yet';
  const minutes = Math.max(0, Math.round((now - seconds) / 60));
  if (minutes < 1) return 'Just now';
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'} ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`;
  const days = Math.round(hours / 24);
  return `${days} day${days === 1 ? '' : 's'} ago`;
}

export function syncingText(source: Source): string {
  if (source.kind === 'website') return 'Public pages of your website (up to 20)';
  const labels: Record<string, string> = { names: 'products', prices: 'prices', categories: 'categories', availability: 'availability' };
  const owned = Object.keys(labels).filter(key => (source.ownership || {})[key] !== 'v7').map(key => labels[key]);
  if (!owned.length) return 'Nothing — V7 keeps what you enter';
  const text = owned.length > 1 ? owned.slice(0, -1).join(', ') + ' and ' + owned[owned.length - 1] : owned[0];
  return text.charAt(0).toUpperCase() + text.slice(1);
}

const REASONS: Record<string, string> = {
  first_import: 'This is the first import from this source.',
  conflicting_edits: 'Some items were changed both here and in your store.',
  suspicious_text: 'Some text looked unusual and was left out.',
  large_price_change: 'A price changed by a large amount.',
  matched_existing: 'Some items match products you already have.',
  empty_source: 'Your store returned no products, so nothing was removed.',
  many_removals: 'Many products are missing from your store.',
  removed_in_v7: 'A product you removed here changed in your store.',
  previously_declined: 'A product you declined before has changed.',
  currency_mismatch: 'Your store uses a different currency from your V7 price list.',
};
export const reasonText = (reason: string): string => REASONS[reason] || '';

const ISSUES: Record<string, string> = {
  missing_name: 'No name', invalid_price: 'No usable price', invalid_row: 'Could not be read',
  duplicate_in_source: 'Appears twice in the source', suspicious_text: 'Unusual text — left out unless you include it',
  edited_in_v7: 'You changed this here; your version is kept unless you tick it', large_price_change: 'Large price change',
  matched_existing: 'Matches a product you already have', missing_from_source: 'No longer in your store',
  deleted_at_source: 'Deleted in your store', unpublished_at_source: 'No longer published in your store',
  removed_in_v7: 'You removed this here', previously_declined: 'You declined this before',
  missing_answer: 'No answer', missing_postcode: 'No postcode', currency_mismatch: 'Different currency',
};
export const issueText = (issue: string): string => ISSUES[issue] || '';

export function changeTitle(row: Row): string {
  const noun = row.kind === 'faq' ? 'answer' : row.kind === 'location' ? 'location' : 'product';
  if (row.action === 'create') return `New ${noun}`;
  if (row.action === 'remove') return `Remove ${noun}`;
  if (row.action === 'invalid') return 'Cannot be imported';
  if (row.action === 'conflict') return `Changed in both places`;
  return `Update ${noun}`;
}

const ERRORS: Record<string, string> = {
  authorisation_required: 'Please confirm you are authorised to share this information.',
  invalid_store_address: 'Enter your store’s public https:// address.',
  invalid_connection_details: 'Some connection details are missing or not valid.',
  unsupported_source: 'That action is not available for this source.',
  data_source_limit: 'You have reached the limit of ten connected sources.',
  data_source_changed: 'These settings changed in another session. Refresh and try again.',
  change_already_handled: 'These changes were already handled or have changed. Refresh and review them again.',
  changed_since_import: 'This information has been edited since, so it cannot be undone automatically.',
  undo_unavailable: 'This change can no longer be undone.',
  import_file_empty: 'That file has nothing to import.',
  import_file_unreadable: 'That file could not be read. Check it is a valid CSV or JSON file.',
  import_columns_missing: 'The file needs at least a name column and a price column.',
  import_too_large: 'That file is too large. Split it into smaller files.',
  import_format_unsupported: 'Use a CSV or JSON file. Save Excel sheets as CSV first.',
  invalid_import: 'Give this source a name and say where it came from.',
  invalid_correction: 'That correction is not valid.',
  legacy_catalogue: 'Your product list uses an older layout that cannot be imported into. Ask your platform operator to convert it.',
  location_limit_reached: 'Your plan’s location limit has been reached.',
  sync_rate_limited: 'Too many updates at once. Try again shortly.',
  source_address_changed: 'That is a different store. Add it as a new source instead.',
  website_missing: 'Save your public https:// website address in Business profile first.',
  website_already_connected: 'You have already given permission for this website.',
  website_permission_required: 'Give permission to read your website first.',
};
const PERMISSION_KINDS: Record<string, string> = { website: 'Read the public pages of', woocommerce: 'Read products from WooCommerce at', shopify: 'Read products from Shopify at', custom_feed: 'Read the product feed at', upload: 'Import a file' };
/** One line of the permission record, in plain words. */
export function permissionText(row: Permission, format: (seconds: number) => string = seconds => new Date(seconds * 1000).toLocaleString()): string {
  const what = (PERMISSION_KINDS[row.kind] || 'Read') + (row.domain ? ' ' + row.domain : '');
  const end = !row.ended ? 'Still in force.' : row.end_reason === 'renewed' ? `Replaced by a newer permission on ${format(row.ended)}.` : `Withdrawn on ${format(row.ended)}${row.ended_by ? ' by ' + row.ended_by : ''}.`;
  return `${what}. Given on ${format(row.granted)} by ${row.account}. ${end}`;
}

export const importError = (code: string): string => ERRORS[code] || 'That did not work. Try again, or refresh the page.';
