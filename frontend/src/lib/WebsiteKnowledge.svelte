<script lang="ts">
  import { onMount } from 'svelte';
  import { t } from './i18n';

  export let tenant: string;
  export let csrf: string;
  export let profileWebsite = '';
  export let apiPrefix = '';
  export let canEdit = false;

  type Summary = { source_url: string; fetched_at: string; page_count: number };
  let summary: Summary | null = null;
  let busy = false;
  let status = '';
  let failed = false;
  type Destination = {id:string;label:string;url:string;purpose:string;enabled:boolean};
  let destinations: Destination[] = [];
  let linksStatus = '';
  let linksBusy = false;
  const linksEndpoint = () => `${apiPrefix}/admin/api/website-destinations?tenant=${encodeURIComponent(tenant)}`;

  async function loadDestinations() {
    const requestedTenant = tenant;
    try {
      const response = await fetch(linksEndpoint(), {credentials:'same-origin'});
      if (!response.ok) throw new Error();
      const data = await response.json();
      if (requestedTenant === tenant) destinations = data.destinations || [];
    } catch { if (requestedTenant === tenant) linksStatus = 'Could not load website destinations.'; }
  }

  async function saveDestinations() {
    if (!canEdit || linksBusy) return;
    const requestedTenant = tenant;
    linksBusy = true;
    linksStatus = '';
    try {
      const response = await fetch(linksEndpoint(), {method:'PUT',credentials:'same-origin',
        headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(destinations)});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Could not save website destinations.');
      if (requestedTenant === tenant) { destinations = data.destinations; linksStatus = 'Website destinations saved.'; }
    } catch (error) { if (requestedTenant === tenant) linksStatus = error instanceof Error ? error.message : 'Could not save website destinations.'; }
    finally { linksBusy = false; }
  }

  function addDestination() {
    destinations = [...destinations,{id:'link_'+crypto.randomUUID().replaceAll('-','').slice(0,16),label:'',url:'',purpose:'',enabled:true}];
  }
  const endpoint = () => `${apiPrefix}/admin/api/website-knowledge?tenant=${encodeURIComponent(tenant)}`;

  async function load() {
    try {
      const response = await fetch(endpoint(), { credentials: 'same-origin' });
      if (!response.ok) throw new Error('Could not load website knowledge.');
      summary = await response.json() as Summary;
    } catch (error) {
      failed = true;
      status = error instanceof Error ? error.message : 'Could not load website knowledge.';
    }
  }

  async function importSite() {
    if (!canEdit || busy) return;
    busy = true;
    failed = false;
    status = 'Importing public pages…';
    try {
      const response = await fetch(`${apiPrefix}/admin/api/website-knowledge/import?tenant=${encodeURIComponent(tenant)}`, {
        method: 'POST', credentials: 'same-origin', headers: { 'X-CSRF-Token': csrf }
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.error || 'Website import could not complete.');
      summary = result as Summary;
      status = `Imported ${summary.page_count} public ${summary.page_count === 1 ? 'page' : 'pages'}. New test conversations can use this information.`;
    } catch (error) {
      failed = true;
      status = error instanceof Error ? error.message : 'Website import could not complete.';
    } finally {
      busy = false;
    }
  }

  onMount(()=>{load();loadDestinations();});
</script>

<section class="knowledge" aria-labelledby="knowledge-heading">
  <div><h2 id="knowledge-heading">Business website knowledge</h2>
    <p>{$t('Import up to 20 public pages from your business website. The agent retrieves relevant passages for each question; saved products, FAQs and policies remain authoritative. Private pages and unsupported files are excluded.')}</p>
    {#if summary?.page_count}<p class="source">Current import: {summary.page_count} pages from {summary.source_url}. Imported {new Date(summary.fetched_at).toLocaleString()}.</p>
    {:else}<p class="source">No website pages imported yet.</p>{/if}
  </div>
  <div class="controls">
    <button type="button" disabled={!canEdit || busy || !profileWebsite} on:click={importSite}>{busy ? 'Importing…' : summary?.page_count ? 'Refresh website pages' : 'Import website'}</button>
    {#if !canEdit}<p>You have viewing access. Ask your owner to update website knowledge.</p>{/if}
    {#if !profileWebsite}<p>Save a public HTTPS website URL in Business profile first.</p>{/if}
    {#if status}<p class:error={failed} role="status">{status}</p>{/if}
  </div>
</section>

<section class="destinations" aria-label={$t('Website destinations')}>
  <h2>{$t('Website destinations')}</h2>
  <p>{$t('Give the agent approved links to products, plans, checkout, booking, policies or other pages. Describe when to offer each link. Customers choose whether to open it; the agent does not submit purchases or bookings.')}</p>
  <p>{$t('Imported website pages can also appear as navigation suggestions. Use specific destinations for external checkout providers or sections such as #pricing.')}</p>
  <form on:submit|preventDefault={saveDestinations}>
    {#each destinations as destination,index (destination.id)}
      <fieldset disabled={!canEdit || linksBusy}>
        <legend>{$t('Destination')} {index+1}</legend>
        <label>{$t('Button label')}<input bind:value={destination.label} required maxlength="80"/></label>
        <label>{$t('Destination URL')}<input type="url" bind:value={destination.url} required placeholder="https://your-business.com/pricing"/></label>
        <label>{$t('When should the agent offer this link?')}<textarea bind:value={destination.purpose} maxlength="400" placeholder={$t('For customers who want to compare plans or choose this product.')}></textarea></label>
        <label class="enabled"><input type="checkbox" bind:checked={destination.enabled}/>{$t('Enabled')}</label>
        <button type="button" on:click={()=>destinations=destinations.filter(row=>row.id!==destination.id)}>{$t('Remove destination')}</button>
      </fieldset>
    {/each}
    <div class="destination-controls"><button type="button" disabled={!canEdit||linksBusy||destinations.length>=30} on:click={addDestination}>{$t('Add destination')}</button><button disabled={!canEdit||linksBusy}>{$t('Save website destinations')}</button></div>
    {#if linksStatus}<p role="status">{$t(linksStatus)}</p>{/if}
  </form>
</section>

<style>
  .knowledge { display:flex; flex-wrap:wrap; justify-content:space-between; gap:20px; padding:24px; border:1px solid var(--v7-line); border-radius:var(--v7-radius, 18px); background:#fff;box-shadow:var(--v7-card-shadow, 0 8px 28px #203b3008);}
  .knowledge > div:first-child { flex:1 1 350px; }
  h2 { margin:0 0 8px; font-size:21px; }
  p { margin:0; color:var(--v7-muted); font-size:14px; line-height:1.65; }
  .source { margin-top:12px; color:var(--v7-ink); overflow-wrap:anywhere; }
  .controls { flex:0 1 260px; display:grid; align-content:start; gap:8px; }
  button { min-height:44px; padding:8px 14px; border:0; border-radius:10px; color:#fff; background:var(--v7-accent); font-weight:700; cursor:pointer; }
  button:disabled { opacity:.55; cursor:default; }
  button:focus-visible { outline:3px solid var(--v7-focus); outline-offset:2px; }
  .error { color:#b42318; }
  .destinations { padding:24px; margin-top:16px; border:1px solid var(--v7-line); border-radius:var(--v7-radius,18px); background:var(--v7-surface,#fff); }
  .destinations form { display:grid; gap:16px; margin-top:16px; }
  fieldset { border:1px solid var(--v7-line); border-radius:12px; padding:16px; display:grid; gap:12px; min-width:0; }
  label { display:grid; gap:6px; font-size:14px; font-weight:600; }
  input,textarea { box-sizing:border-box; width:100%; min-height:44px; border:1px solid var(--v7-line); border-radius:8px; padding:10px; background:var(--v7-surface,#fff); color:var(--v7-ink); }
  .enabled { display:flex; align-items:center; } .enabled input { width:auto; min-height:auto; }
  .destination-controls { display:flex; flex-wrap:wrap; gap:10px; }
</style>
