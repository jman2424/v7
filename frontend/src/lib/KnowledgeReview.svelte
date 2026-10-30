<script lang="ts">
  import { onDestroy } from 'svelte';
  import { t } from './i18n';

  export let endpoint: string;
  export let tenant: string;
  export let consoleBase: string;
  export let accessibleSections: string[] = [];
  type Issue = { code: string; message: string; section: string; severity: string };
  type Review = { generated_at: string; complete: boolean; scope: string; counts: Record<string, number>; issues: Issue[] };
  let report: Review | null = null;
  let busy = false;
  let error = '';
  let sequence = 0;
  let controller: AbortController | null = null;
  const editors: Record<string, string> = { profile: 'Business profile', agent: 'Agent playbook', catalog: 'Catalogue', faqs: 'Questions & answers', website: 'Website widget' };

  async function refresh() {
    const current = ++sequence;
    controller?.abort();
    const activeController = new AbortController();
    controller = activeController;
    const signal = activeController.signal;
    const timeout = setTimeout(() => activeController.abort(), 20000);
    busy = true;
    report = null;
    error = '';
    try {
      const response = await fetch(endpoint, { credentials: 'same-origin', cache: 'no-store', signal });
      const data = await response.json();
      if (current !== sequence || signal.aborted) return;
      if (!response.ok || data.tenant !== tenant || !Array.isArray(data.issues) || !data.counts || typeof data.counts !== 'object') throw new Error('unavailable');
      report = data as Review;
    } catch {
      if (current === sequence) error = 'The knowledge review could not load. Check your connection and try again.';
    } finally {
      clearTimeout(timeout);
      if (current === sequence) busy = false;
    }
  }

  function dispose() { sequence++; controller?.abort(); }
  onDestroy(dispose);
</script>

<section class="surface knowledge-review" aria-labelledby="knowledge-review-heading">
  <div class="surface-head">
    <div><h2 id="knowledge-review-heading">{$t('Knowledge review')}</h2><p>{$t('Check the saved information your assistant uses. Available on every plan.')}</p></div>
    <button class="secondary" type="button" disabled={busy} on:click={refresh}>{$t(busy ? 'Checking...' : 'Review saved knowledge')}</button>
  </div>
  <div class="surface-body" aria-live="polite" aria-busy={busy}>
    {#if error}<p class="error">{$t(error)}</p>{/if}
    {#if report}
      <p>{$t('This checks saved business information, not live website changes or every possible contradiction. Refresh after editing your settings.')}</p>
      {#if !report.complete}<p class="error">{$t('This review is incomplete. Some records or issues exceeded the review limit.')}</p>{/if}
      <p class="counts">{$t('Catalogue items')}: {report.counts.active_catalogue_items_reviewed} · {$t('Other offerings')}: {report.counts.active_native_offerings_reviewed} · {$t('FAQ topics')}: {report.counts.faq_topics_reviewed} · {$t('Imported pages')}: {report.counts.usable_imported_pages}</p>
      {#if report.issues.length}
        <ul>{#each report.issues as issue}
          <li><p class:error={issue.severity === 'error'}>{issue.message}</p>
            {#if editors[issue.section] && accessibleSections.includes(issue.section)}
              <a href={`${consoleBase}/${issue.section}?tenant=${encodeURIComponent(tenant)}`}>{$t(editors[issue.section])} ↗</a>
            {/if}
          </li>
        {/each}</ul>
      {:else}
        <p>{$t('No issues found by these checks. Test realistic customer conversations before launch.')}</p>
      {/if}
    {:else if !busy && !error}
      <p>{$t('Review missing information, duplicate FAQs, conflicting answers and website import freshness. Your saved information is not changed.')}</p>
    {/if}
  </div>
</section>

<style>
  .knowledge-review{padding:24px;border:1px solid var(--v7-line,#dce4e0);border-radius:var(--v7-radius,18px);background:var(--v7-surface,#fff);box-shadow:var(--v7-card-shadow,0 8px 28px #203b3008)}
  .surface-head{display:flex;align-items:center;justify-content:space-between;gap:1rem;flex-wrap:wrap}
  h2{margin:0;font-size:21px}.surface-head p{margin:.5rem 0 0;max-width:48rem}
  p{font-size:14px;line-height:1.65;color:var(--v7-muted,#53635d)}
  .surface-body{padding-top:12px}.counts{line-height:1.8}
  ul{padding-inline-start:1.4rem}li{margin:1rem 0}li p{margin:0 0 .35rem;white-space:pre-wrap;overflow-wrap:anywhere}
  .error{color:#a21c25}a{display:inline-block;color:var(--v7-accent,#087f5b);font-size:14px}
  button{min-height:44px;padding:10px 16px;border:1px solid var(--v7-control-line,#c7d2cc);border-radius:8px;background:var(--v7-surface,#fff);color:var(--v7-ink,#23352c);font:inherit;font-size:13px;font-weight:600;cursor:pointer}
  button:hover:not(:disabled){background:var(--v7-soft,#edf6f1)}button:disabled{opacity:.6;cursor:default}
  :is(button,a):focus-visible{outline:3px solid var(--v7-focus,#91cdb6);outline-offset:3px}
  @media(max-width:700px){.knowledge-review{padding:18px}.surface-head button{width:100%}}
</style>
