<script lang="ts">
  // Shown only to the platform administrator: business applications waiting for a decision.
  import { onMount, onDestroy } from 'svelte';
  import { waitingText } from './applicationsText';
  export let href: string;
  export let apiPrefix = '';
  let pending = 0;
  const controller = new AbortController();
  onMount(async () => {
    try {
      const response = await fetch(apiPrefix + '/business-applications/queue?page=1', { credentials: 'same-origin', signal: controller.signal });
      if (!response.ok) return;
      const data = await response.json();
      if (Number.isInteger(data.pending) && data.pending > 0) pending = data.pending;
    } catch { /* The queue page reports its own errors; an alert that cannot load stays hidden. */ }
  });
  onDestroy(() => controller.abort());
</script>

{#if pending}
  <aside class="applications-alert" aria-label="Business applications">
    <p><strong>{waitingText(pending)}</strong> <span>Nothing is approved or paid for until you decide.</span></p>
    <a {href}>Review applications</a>
  </aside>
{/if}

<style>
  .applications-alert{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:var(--v7-space-3) var(--v7-space-5);margin-bottom:var(--v7-space-5);padding:var(--v7-space-3) var(--v7-space-4);border:1px solid var(--v7-mint-line);border-radius:var(--v7-radius-panel);background:var(--v7-mint-soft);color:var(--v7-on-mint)}
  p{margin:0;font-size:var(--v7-text-sm);line-height:1.5}
  span{color:var(--v7-ink-soft)}
  a{display:inline-flex;align-items:center;min-height:44px;padding:0 var(--v7-space-4);border-radius:var(--v7-radius-control);background:var(--v7-accent);color:#fff;font-size:var(--v7-text-sm);font-weight:600;text-decoration:none;transition:background-color .15s}
  a:hover{background:var(--v7-accent-hover)}
  a:focus-visible{outline:3px solid var(--v7-focus);outline-offset:3px}
</style>
