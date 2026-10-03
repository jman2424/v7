<script lang="ts">
  import { onMount } from 'svelte';

  export let tenant: string;
  export let csrf: string;
  export let profileWebsite = '';
  export let apiPrefix = '';

  type Summary = { source_url: string; fetched_at: string; page_count: number };
  let summary: Summary | null = null;
  let busy = false;
  let status = '';
  let failed = false;
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

  onMount(load);
</script>

<section class="knowledge" aria-labelledby="knowledge-heading">
  <div><h2 id="knowledge-heading">Business website knowledge</h2>
    <p>Import up to six public pages from the website saved in Business profile. The agent can use verified excerpts for questions the structured information does not cover.</p>
    {#if summary?.page_count}<p class="source">Current import: {summary.page_count} pages from {summary.source_url}. Imported {new Date(summary.fetched_at).toLocaleString()}.</p>
    {:else}<p class="source">No website pages imported yet.</p>{/if}
  </div>
  <div class="controls">
    <button type="button" disabled={busy || !profileWebsite} on:click={importSite}>{busy ? 'Importing…' : summary?.page_count ? 'Refresh website pages' : 'Import website'}</button>
    {#if !profileWebsite}<p>Save a public HTTPS website URL in Business profile first.</p>{/if}
    {#if status}<p class:error={failed} role="status">{status}</p>{/if}
  </div>
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
  button:focus-visible { outline:3px solid #8bcdc0; outline-offset:2px; }
  .error { color:#b42318; }
</style>
