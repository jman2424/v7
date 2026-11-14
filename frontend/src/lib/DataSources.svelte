<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { t } from './i18n';
  import { sourceTitle, sourceProblem, agoText, syncingText, reasonText, issueText, importError, changeTitle, permissionText } from './dataSourceText';
  import type { Source, Row, Change, Listing } from './dataSourceText';

  export let tenant: string;
  export let csrf: string;
  export let canEdit = false;
  export let isPlatform = false;
  export let apiPrefix = '';

  let listing: Listing | null = null;
  let error = '';
  let status = '';
  let busy = false;
  let adding: '' | 'woocommerce' | 'shopify' | 'custom_feed' | 'upload' | 'website' = '';
  let authorised = false;
  let form: Record<string, string> = {};
  let automatic = true;
  let autoApply = false;
  let fileText = '';
  let fileName = '';
  let fileFormat: 'csv' | 'json' = 'csv';
  let completeList = false;
  let refreshSource = '';
  let instant: { url: string; secret: string; kind: string } | null = null;
  let review: Change | null = null;
  let settingsFor = '';
  let diagnostics: unknown = null;
  const controller = new AbortController();
  const base = () => `${apiPrefix}/admin/api/data-sources`;
  const query = () => `?tenant=${encodeURIComponent(tenant)}`;
  $: manage = canEdit && Boolean(listing?.can_manage);

  async function call(path: string, method = 'GET', body?: unknown) {
    const response = await fetch(base() + path + query(), {
      method, credentials: 'same-origin', signal: controller.signal,
      headers: method === 'GET' ? {} : { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
      body: body === undefined ? undefined : JSON.stringify(body)
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof data.error === 'string' ? data.error : 'request_failed');
    return data;
  }

  async function load() {
    try { listing = await call(''); error = ''; }
    catch { if (!controller.signal.aborted) error = 'Could not load your data sources. Refresh or sign in again.'; }
  }

  async function act(work: () => Promise<void>, done = '') {
    if (busy) return;
    busy = true; error = ''; status = '';
    try { await work(); status = done; await load(); }
    catch (failure) { if (!controller.signal.aborted) error = importError(failure instanceof Error ? failure.message : ''); }
    finally { busy = false; }
  }

  function begin(kind: typeof adding, sourceId = '') {
    adding = kind; authorised = false; form = {}; fileText = ''; fileName = ''; completeList = false;
    refreshSource = sourceId; instant = null; status = ''; error = '';
  }

  async function connectWebsite() {
    let read = false;
    await act(async () => {
      read = Boolean((await call('', 'POST', { kind: 'website', authorised, auto_sync: automatic })).source?.last_success);
      adding = '';
    });
    if (!error) status = read ? 'Thank you. Your permission is recorded and your website has been read. Your assistant can now use it.'
      : 'Thank you. Your permission is recorded. Your website has not been read yet — choose Read again now in a moment.';
  }

  const connect = () => act(async () => {
    const data = await call('', 'POST', { kind: adding, connection: form, authorised, auto_sync: automatic, auto_apply: autoApply });
    instant = data.instant_updates; adding = '';
  }, 'Connected. The first import will appear here for your approval — nothing is added until you approve it.');

  async function chooseFile(event: Event) {
    const file = (event.currentTarget as HTMLInputElement).files?.[0];
    if (!file) return;
    if (file.size > 900_000) { error = importError('import_too_large'); return; }
    fileName = file.name; fileFormat = file.name.toLowerCase().endsWith('.json') ? 'json' : 'csv';
    fileText = await file.text();
  }

  const upload = () => act(async () => {
    const body: Record<string, unknown> = { format: fileFormat, content: fileText, authorised, complete_list: completeList };
    if (refreshSource) body.source_id = refreshSource;
    else Object.assign(body, { label: form.label || fileName, source_type: form.source_type || 'file', source_ref: form.source_ref || fileName, tool: form.tool || 'none' });
    const data = await call('/imports', 'POST', body);
    adding = '';
    if (data.change) review = data.change; else status = 'Nothing new to import: this information is already up to date.';
  });

  const openReview = (id: string) => act(async () => { review = (await call('/changes/' + id)).change; });
  async function syncNow(id: string) {
    const before = listing?.sources.find(source => source.id === id)?.last_success || 0;
    let after = 0;
    await act(async () => { after = (await call(`/${id}/sync`, 'POST', {})).source?.last_success || 0; });
    if (!error) status = after > before ? 'Checked for updates.'
      : listing?.automatic_updates_running ? 'Update requested. It will show here shortly.'
      : 'That could not be completed just now. Your current information is kept. Try again in a moment.';
  }
  const disconnect = (source: Source) => {
    if (source.kind === 'website') {
      if (!confirm($t('Withdraw your permission? V7 will stop reading your website and remove the pages it has stored. Your products, prices and answers are not affected.'))) return;
      return act(async () => { await call(`/${source.id}/disconnect`, 'POST', {}); }, 'Permission withdrawn. Your website is no longer read.');
    }
    if (!confirm($t('Disconnect this source? V7 will stop reading from it and delete its saved access details. Information already imported stays.'))) return;
    return act(async () => { await call(`/${source.id}/disconnect`, 'POST', {}); }, 'Disconnected.');
  };
  const saveSettings = (source: Source) => act(async () => {
    await call('/' + source.id, 'PUT', { version: source.version, auto_sync: source.auto_sync, auto_apply: source.auto_apply, interval_minutes: Number(source.interval_minutes), ownership: source.ownership });
    settingsFor = '';
  }, 'Settings saved.');

  async function toggle(row: Row) {
    if (!review || busy) return;
    const current = review;
    await act(async () => { review = (await call('/changes/' + current.id, 'PUT', { version: current.version, rows: [{ n: row.n, include: !row.include }] })).change; });
  }
  const decide = (decision: 'apply' | 'reject') => act(async () => {
    if (!review) return;
    await call(`/changes/${review.id}/${decision}`, 'POST', { version: review.version });
    review = null;
  }, decision === 'apply' ? 'Changes applied. Your assistant now uses the updated information.' : 'Changes discarded. Nothing was altered.');
  const undo = (id: string) => {
    if (!confirm($t('Undo this change and restore the previous information?'))) return;
    return act(async () => { await call(`/changes/${id}/undo`, 'POST', {}); }, 'Previous information restored.');
  };
  const showDiagnostics = () => act(async () => { diagnostics = await call('/diagnostics'); });
  const value = (item: unknown) => item === true ? 'In stock' : item === false ? 'Out of stock' : item === null || item === undefined ? '—' : typeof item === 'object' ? Object.entries(item as object).map(([k, v]) => `${k} ${v}`).join(', ') : String(item);

  onMount(() => { void load(); });
  onDestroy(() => controller.abort());
</script>

<section class="sources" aria-label={$t('Data Sources & Sync')}>
  <header><p>{$t('Connect the place your products and prices already live, and V7 keeps your assistant up to date. You approve what is imported.')}</p></header>
  {#if error}<p class="notice error" role="alert">{$t(error)}</p>{/if}
  {#if status}<p class="notice" role="status">{$t(status)}</p>{/if}

  {#if !listing && !error}<p role="status">{$t('Loading…')}</p>{/if}
  {#if listing}
    {#each listing.reviews as item (item.id)}
      <div class="attention" role="status">
        <div><strong>{$t('Changes are waiting for your approval')}</strong>
          <span>{item.summary.source_label || ''} · {(item.summary.reasons || []).map(reason => $t(reasonText(reason))).filter(Boolean).join(' ')}</span></div>
        <button type="button" class="primary" disabled={busy} on:click={() => openReview(item.id)}>{$t('Review changes')}</button>
      </div>
    {/each}

    {#if review}
      <div class="review" aria-labelledby="review-title">
        <h3 id="review-title">{$t('Review changes')}</h3>
        <p>{$t('Untick anything that looks wrong. Nothing is changed until you choose Apply.')}</p>
        <div class="table" role="group" aria-label={$t('Proposed changes')}>
          {#each review.rows as row (row.n)}
            <label class="row" class:off={!row.include}>
              <input type="checkbox" checked={row.include} disabled={busy || !manage || row.action === 'invalid' || review.state !== 'pending'} on:change={() => toggle(row)} />
              <span class="what"><strong>{row.name || $t('Unnamed item')}</strong>
                <em>{$t(changeTitle(row))}{#if row.category}{' · '}{row.category}{/if}</em>
                {#each Object.entries(row.fields || {}) as [field, change]}<span class="change">{$t(field.replace('_', ' '))}: <s>{value(change.from)}</s> → <b>{value(change.to)}</b></span>{/each}
                {#if row.values?.price !== undefined}<span class="change">{$t('price')}: <b>{row.values.price}</b></span>{/if}
                {#each row.issues as issue}{#if issueText(issue)}<span class="issue">{$t(issueText(issue))}</span>{/if}{/each}
              </span>
            </label>
          {/each}
        </div>
        {#if review.total_rows > review.rows.length}<p>{$t('Showing the first')} {review.rows.length} {$t('of')} {review.total_rows}.</p>{/if}
        <div class="actions">
          {#if manage && review.state === 'pending'}
            <button type="button" class="primary" disabled={busy} on:click={() => decide('apply')}>{$t('Apply selected changes')}</button>
            <button type="button" disabled={busy} on:click={() => decide('reject')}>{$t('Discard all')}</button>
          {/if}
          <button type="button" disabled={busy} on:click={() => (review = null)}>{$t('Close')}</button>
        </div>
      </div>
    {/if}

    {#each listing.sources as source (source.id)}
      <article class="source" class:problem={source.status !== 'connected'}>
        <div class="summary">
          <h3>{source.label}</h3>
          <p class="state">{$t(sourceTitle(source))}</p>
          {#if sourceProblem(source)}<p class="issue" role="status">{$t(sourceProblem(source))}</p>{/if}
          <dl>
            {#if source.syncs}
              <div><dt>{$t(source.kind === 'website' ? 'Last read' : 'Last updated')}</dt><dd>{$t(agoText(source.last_success))}</dd></div>
              <div><dt>{$t('Automatic updates')}</dt><dd>{$t(source.auto_sync ? (listing.automatic_updates_running ? 'Enabled' : 'Enabled — starts once your platform operator switches automatic updates on') : 'Off')}</dd></div>
              <div><dt>{$t(source.kind === 'website' ? 'What is read' : 'Synchronising')}</dt><dd>{$t(syncingText(source))}</dd></div>
            {:else}
              <div><dt>{$t('Source')}</dt><dd>{source.source_ref || $t('Uploaded file')}</dd></div>
              <div><dt>{$t('Last import')}</dt><dd>{$t(agoText(source.last_attempt))}</dd></div>
            {/if}
          </dl>
        </div>
        {#if manage}
          <div class="actions">
            {#if source.syncs}
              <button type="button" class="primary" disabled={busy || source.status === 'reconnect'} on:click={() => syncNow(source.id)}>{$t(source.kind === 'website' ? 'Read again now' : 'Sync Now')}</button>
              <button type="button" disabled={busy} on:click={() => (settingsFor = settingsFor === source.id ? '' : source.id)}>{$t('Change Settings')}</button>
            {:else}
              <button type="button" class="primary" disabled={busy} on:click={() => begin('upload', source.id)}>{$t('Import updated file')}</button>
            {/if}
            <button type="button" class="quiet" disabled={busy} on:click={() => disconnect(source)}>{$t(source.kind === 'website' ? 'Withdraw permission' : 'Disconnect')}</button>
          </div>
        {/if}
        {#if settingsFor === source.id}
          <form class="settings" on:submit|preventDefault={() => saveSettings(source)}>
            <label class="check"><input type="checkbox" bind:checked={source.auto_sync} />{$t(source.kind === 'website' ? 'Read my website again once a day' : 'Check for updates automatically')}</label>
            {#if source.kind !== 'website'}
            <label>{$t('How often')}<select bind:value={source.interval_minutes}><option value={15}>{$t('Every 15 minutes')}</option><option value={60}>{$t('Every hour')}</option><option value={360}>{$t('Every 6 hours')}</option><option value={1440}>{$t('Once a day')}</option></select></label>
            <label class="check"><input type="checkbox" bind:checked={source.auto_apply} />{$t('Apply routine updates without asking me')}</label>
            <p class="hint">{$t('Unusual changes — big price swings, many removals, or anything that clashes with an edit you made here — always wait for your approval.')}</p>
            <fieldset><legend>{$t('Which side decides')}</legend>
              {#each [['prices', 'Prices'], ['names', 'Product names'], ['categories', 'Categories'], ['availability', 'Availability']] as [key, label]}
                <label>{$t(label)}<select bind:value={source.ownership[key]}><option value="source">{$t('My store')}</option><option value="v7">{$t('What I enter in V7')}</option></select></label>
              {/each}
            </fieldset>
            {/if}
            <div class="actions"><button class="primary" disabled={busy}>{$t('Save settings')}</button></div>
          </form>
        {/if}
      </article>
    {:else}
      <p class="empty">{$t('No sources connected yet. Add one below, or keep editing your information by hand — both work.')}</p>
    {/each}

    {#if instant && instant.url}
      <div class="instant" role="status">
        <h3>{$t('Optional: instant updates')}</h3>
        <p>{$t('V7 already checks your store on a schedule. To be told about changes the moment they happen, add a webhook for product created, updated and deleted in your store using this address. This is shown once.')}</p>
        <label>{$t('Delivery address')}<input readonly value={instant.url} /></label>
        {#if instant.secret}<label>{$t('Secret')}<input readonly value={instant.secret} /></label>
        {:else}<p class="hint">{$t('Shopify signs these with your app’s own secret key, which you already entered.')}</p>{/if}
        <button type="button" on:click={() => (instant = null)}>{$t('Done')}</button>
      </div>
    {/if}

    {#if manage && !adding}
      <div class="add">
        <h3>{$t('Add a source')}</h3>
        <div class="choices">
          <button type="button" on:click={() => begin('woocommerce')}><strong>WooCommerce</strong><span>{$t('Products, prices and stock')}</span></button>
          <button type="button" on:click={() => begin('shopify')}><strong>Shopify</strong><span>{$t('Products, prices and stock')}</span></button>
          <button type="button" on:click={() => begin('custom_feed')}><strong>{$t('Another website or system')}</strong><span>{$t('A product feed your developer provides')}</span></button>
          {#if !listing.sources.some(source => source.kind === 'website' && source.host === listing?.website)}<button type="button" on:click={() => begin('website')}><strong>{$t('Your website')}</strong><span>{$t('Public pages, read with your permission')}</span></button>{/if}
          <button type="button" on:click={() => begin('upload')}><strong>{$t('Upload a file')}</strong><span>{$t('Spreadsheet (CSV) or prepared import file')}</span></button>
        </div>
      </div>
    {/if}

    {#if adding}
      <form class="connect" on:submit|preventDefault={adding === 'upload' ? upload : adding === 'website' ? connectWebsite : connect}>
        <h3>{$t(adding === 'upload' ? (refreshSource ? 'Import an updated file' : 'Upload a file') : adding === 'website' ? 'Let V7 read your website' : 'Connect your store')}</h3>
        {#if adding === 'website'}
          {#if listing.website}
            <p class="site">{$t('Website')}: <strong>{listing.website}</strong></p>
            <ul class="plain">
              <li>{$t('V7 reads up to 20 public pages of this website so your assistant can answer from them.')}</li>
              <li>{$t('It never signs in, fills in forms or changes anything, and it follows your website’s robots rules.')}</li>
              <li>{$t('Your saved products, prices and answers always take priority over website text.')}</li>
              <li>{$t('You can withdraw permission at any time. V7 then stops reading and removes the stored pages.')}</li>
            </ul>
            <label class="check"><input type="checkbox" bind:checked={automatic} />{$t('Read my website again once a day')}</label>
          {:else}
            <p class="issue">{$t('Save your public https:// website address in Business profile first.')}</p>
          {/if}
        {:else if adding === 'woocommerce'}
          <label>{$t('Store address')}<input type="url" required placeholder="https://your-shop.com" bind:value={form.store_url} /></label>
          <label>{$t('Consumer key')}<input required autocomplete="off" bind:value={form.consumer_key} /></label>
          <label>{$t('Consumer secret')}<input type="password" required autocomplete="off" bind:value={form.consumer_secret} /></label>
          <p class="hint">{$t('In WooCommerce: Settings → Advanced → REST API → Add key. Choose Read permission only — V7 never changes your store.')}</p>
        {:else if adding === 'shopify'}
          <label>{$t('Shop domain')}<input required placeholder="your-shop.myshopify.com" bind:value={form.shop_domain} /></label>
          <label>{$t('Client ID')}<input autocomplete="off" bind:value={form.client_id} /></label>
          <label>{$t('Client secret')}<input type="password" autocomplete="off" bind:value={form.client_secret} /></label>
          <label>{$t('Or: Admin API access token')}<input type="password" autocomplete="off" bind:value={form.access_token} /></label>
          <p class="hint">{$t('Create an app for your own shop with the read_products permission only. Enter its client ID and secret, or its Admin API access token.')}</p>
        {:else if adding === 'custom_feed'}
          <label>{$t('Feed address')}<input type="url" required placeholder="https://your-site.com/v7-products.json" bind:value={form.feed_url} /></label>
          <label>{$t('Access token (optional)')}<input type="password" autocomplete="off" bind:value={form.access_token} /></label>
          <p class="hint">{$t('Your developer can find the simple feed format in the V7 import guide.')}</p>
        {:else}
          <label>{$t('File')}<input type="file" accept=".csv,.json,text/csv,application/json" required on:change={chooseFile} /></label>
          {#if !refreshSource}
            <label>{$t('Name for this source')}<input maxlength="80" placeholder={fileName || 'Price list'} bind:value={form.label} /></label>
            <label>{$t('Where did this information come from?')}<select bind:value={form.source_type}><option value="file">{$t('A file from the business')}</option><option value="website">{$t('The business website')}</option><option value="database">{$t('An export from another system')}</option><option value="document">{$t('A document from the business')}</option><option value="other">{$t('Something else')}</option></select></label>
            <label>{$t('Prepared with an AI tool?')}<select bind:value={form.tool}><option value="none">{$t('No')}</option><option value="claude">Claude</option><option value="codex">Codex</option><option value="other">{$t('Another tool')}</option></select></label>
          {/if}
          <label class="check"><input type="checkbox" bind:checked={completeList} />{$t('This file is the complete list — suggest removing products from this source that are no longer in it')}</label>
        {/if}
        {#if adding !== 'upload' && adding !== 'website'}
          <label class="check"><input type="checkbox" bind:checked={automatic} />{$t('Check for updates automatically')}</label>
          <label class="check"><input type="checkbox" bind:checked={autoApply} />{$t('Apply routine updates without asking me (the first import is always shown to you first)')}</label>
        {/if}
        <label class="check consent"><input type="checkbox" bind:checked={authorised} required />{adding === 'website' ? listing.website_statement : listing.authorisation_statement}</label>
        <p class="hint">{$t('Your answer is saved with your account, the date and the terms version')} ({listing.terms_version}).</p>
        <div class="actions">
          <button class="primary" disabled={busy || !authorised || (adding === 'upload' && !fileText) || (adding === 'website' && !listing.website)}>{$t(busy ? 'Working…' : adding === 'upload' ? 'Preview import' : adding === 'website' ? 'Give permission and read my website' : 'Connect')}</button>
          <button type="button" disabled={busy} on:click={() => (adding = '')}>{$t('Cancel')}</button>
        </div>
      </form>
    {/if}

    {#if listing.history.length}
      <div class="history">
        <h3>{$t('Recent changes')}</h3>
        <ul>{#each listing.history as item (item.id)}
          <li><span><strong>{item.summary.source_label || $t('Import')}</strong> · {$t(item.state === 'applied' ? 'Applied' : item.state === 'rejected' ? 'Discarded' : 'Undone')} · {new Date(item.updated * 1000).toLocaleString()}{#if item.summary.applied !== undefined} · {item.summary.applied} {$t('changes')}{/if}</span>
            <span class="actions"><button type="button" class="quiet" disabled={busy} on:click={() => openReview(item.id)}>{$t('View')}</button>{#if manage && item.can_undo}<button type="button" class="quiet" disabled={busy} on:click={() => undo(item.id)}>{$t('Undo')}</button>{/if}</span></li>
        {/each}</ul>
      </div>
    {/if}

    {#if listing.permissions.length}
      <details class="permissions"><summary>{$t('Permission records')}</summary>
        <p class="hint">{$t('Every permission given for this business, including ones that have ended. These records are kept and cannot be edited.')}</p>
        <ul>{#each listing.permissions as row}<li><span>{permissionText(row)}</span><span class="hint">{row.terms_version}</span></li>{/each}</ul>
      </details>
    {/if}

    {#if isPlatform}
      <details class="diagnostics"><summary on:click={showDiagnostics}>{$t('Operator diagnostics')}</summary>
        {#if diagnostics}<pre>{JSON.stringify(diagnostics, null, 2)}</pre>{/if}</details>
    {/if}
  {/if}
</section>

<style>
  .sources{display:grid;gap:var(--v7-space-4,16px);color:var(--v7-ink)}
  header p,.hint,.empty,dd,.what em{color:var(--v7-muted);font-size:var(--v7-text-sm);line-height:1.6;margin:0}
  h3{margin:0 0 8px;font-size:var(--v7-text-lg,1.1rem)}
  .source,.review,.connect,.add,.history,.instant,.attention{background:var(--v7-surface);border:1px solid var(--v7-line);border-radius:var(--v7-radius-panel);padding:20px}
  .source{display:flex;flex-wrap:wrap;gap:16px;justify-content:space-between;align-items:flex-start}
  .source.problem,.attention{border-color:var(--v7-danger-line,var(--v7-line))}
  .summary{flex:1 1 280px;min-inline-size:0}.state{margin:0;font-weight:600}
  dl{display:grid;gap:6px;margin:12px 0 0}dl div{display:flex;gap:8px;flex-wrap:wrap}dt{font-weight:600;font-size:var(--v7-text-sm)}dd{margin:0}
  .actions{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
  button{min-block-size:44px;padding:8px 14px;border:1px solid var(--v7-control-line,var(--v7-line));border-radius:var(--v7-radius-control);background:var(--v7-surface);color:var(--v7-ink);font:inherit;font-weight:600;cursor:pointer}
  button.primary{background:var(--v7-accent);border-color:var(--v7-accent);color:#fff}
  button.quiet{border-color:transparent;color:var(--v7-accent);padding-inline:8px}
  button:disabled{opacity:.55;cursor:default}button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid var(--v7-focus);outline-offset:2px}
  .attention{display:flex;flex-wrap:wrap;gap:12px;justify-content:space-between;align-items:center;background:var(--v7-danger-soft,var(--v7-soft))}
  .attention div{display:grid;gap:4px}.attention span{font-size:var(--v7-text-sm)}
  .notice{margin:0;padding:12px 14px;border-radius:var(--v7-radius-control);background:var(--v7-mint-soft,var(--v7-soft))}
  .error,.issue{color:var(--v7-danger)}.notice.error{background:var(--v7-danger-soft,var(--v7-soft))}
  .issue{display:block;font-size:var(--v7-text-sm);margin:4px 0 0}
  .table{display:grid;border-block-start:1px solid var(--v7-line);margin-block:12px;max-block-size:420px;overflow:auto}
  .row{display:flex;gap:12px;align-items:flex-start;padding:10px 4px;border-block-end:1px solid var(--v7-line)}
  .row.off .what strong{color:var(--v7-muted);text-decoration:line-through}
  .row input{inline-size:20px;block-size:20px;margin-block-start:2px;flex:none}
  .what{display:grid;gap:2px;min-inline-size:0;overflow-wrap:anywhere}.what em{font-style:normal}.change{font-size:var(--v7-text-sm)}
  .choices{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px}
  .choices button{display:grid;gap:4px;text-align:start;padding:14px}.choices span{font-weight:400;color:var(--v7-muted);font-size:var(--v7-text-sm)}
  form{display:grid;gap:12px}.settings{flex:1 1 100%;border-block-start:1px solid var(--v7-line);padding-block-start:16px}
  label{display:grid;gap:6px;font-size:var(--v7-text-sm);font-weight:600}
  label.check{display:flex;gap:10px;align-items:flex-start;font-weight:400;line-height:1.5}label.check input{flex:none;inline-size:18px;block-size:18px;margin-block-start:2px}
  .consent{padding:12px;border-radius:var(--v7-radius-control);background:var(--v7-soft)}
  input:not([type=checkbox]),select{box-sizing:border-box;inline-size:100%;min-block-size:44px;padding:10px;border:1px solid var(--v7-control-line,var(--v7-line));border-radius:var(--v7-radius-control);background:var(--v7-surface);color:var(--v7-ink);font:inherit}
  fieldset{border:1px solid var(--v7-line);border-radius:var(--v7-radius-control);padding:12px;display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;min-inline-size:0}
  ul{list-style:none;margin:0;padding:0}li{display:flex;flex-wrap:wrap;gap:8px;justify-content:space-between;align-items:center;padding:8px 0;border-block-end:1px solid var(--v7-line);font-size:var(--v7-text-sm)}
  .permissions{background:var(--v7-surface);border:1px solid var(--v7-line);border-radius:var(--v7-radius-panel);padding:12px 20px}
  .permissions summary{min-block-size:44px;align-content:center;font-weight:600;cursor:pointer}.permissions li{overflow-wrap:anywhere}
  .site{margin:0;overflow-wrap:anywhere}.plain{display:grid;gap:6px;padding-inline-start:20px;list-style:disc;color:var(--v7-ink-soft,var(--v7-muted));font-size:var(--v7-text-sm);line-height:1.5}.plain li{display:list-item;border:0;padding:0}
  pre{overflow:auto;font-size:var(--v7-text-xs);background:var(--v7-soft);padding:12px;border-radius:var(--v7-radius-control)}
</style>
