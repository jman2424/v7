<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { choosePreferences, preferenceChoice, t } from './i18n';
  let open = false;
  let panelHeight = 0;
  let reopened = false;
  let opener: HTMLButtonElement;
  let closeButton: HTMLButtonElement;
  onMount(() => {
    open = !preferenceChoice();
    const updateChoice = () => { open = false; };
    window.addEventListener('v7-preferences-changed', updateChoice);
    return () => window.removeEventListener('v7-preferences-changed', updateChoice);
  });
  async function showPreferences() {
    reopened = true;
    open = true;
    await tick();
    closeButton?.focus();
  }
  function dismiss() {
    open = false;
    if (reopened) opener?.focus();
    reopened = false;
  }
  function save(choice: 'essential' | 'all') {
    choosePreferences(choice);
    dismiss();
  }
  function measurePanel(node: HTMLElement) {
    const measure = () => { panelHeight = Math.ceil(node.getBoundingClientRect().height) + 28; };
    measure();
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure);
    observer?.observe(node);
    return { destroy() { observer?.disconnect(); panelHeight = 0; } };
  }
</script>
<svelte:window on:keydown={(event) => { if (open && event.key === 'Escape') dismiss(); }} />
{#if open}
  <aside id="workspace-cookie-preferences" class="cookie-panel" aria-label={$t('Cookie preferences')} use:measurePanel>
    <div class="cookie-heading"><strong>{$t('Your privacy choices')}</strong><button class="close-choice" type="button" aria-label={$t('Close cookie preferences')} bind:this={closeButton} on:click={dismiss}><span aria-hidden="true">×</span></button></div>
    <p>{$t('Sign-in and security cookies are essential. Saving your language is optional. No advertising cookies are used.')}</p>
    <div class="cookie-actions"><button type="button" on:click={() => save('essential')}>{$t('Essential only')}</button><button class="primary" type="button" on:click={() => save('all')}>{$t('Save my preferences')}</button></div>
    <a href="/cookies" target="_blank" rel="noopener">{$t('Cookie information')} <span aria-hidden="true">↗</span></a>
  </aside>
{/if}
<div class="privacy-footer" style:padding-bottom={(open ? panelHeight : 0) + 'px'}><button class="privacy-choice" type="button" aria-expanded={open} aria-controls={open ? 'workspace-cookie-preferences' : undefined} bind:this={opener} on:click={showPreferences}>{$t('Cookie preferences')}</button></div>
<style>
  .cookie-panel{position:fixed;bottom:max(16px,env(safe-area-inset-bottom));inset-inline-end:16px;z-index:1000;display:grid;gap:12px;width:min(440px,calc(100% - 32px));max-height:calc(100dvh - 32px);overflow:auto;padding:18px 20px;border:1px solid #c9ddcf;border-radius:18px;background:#fff;box-shadow:0 12px 45px #203b3024;color:var(--v7-ink);box-sizing:border-box}
  .cookie-heading{display:flex;align-items:center;justify-content:space-between;gap:12px}.cookie-heading strong{font-size:15px;color:var(--v7-brand,#203b30)}p{font-size:13px;margin:0;line-height:1.6;}a{font-size:12px;color:var(--v7-accent);justify-self:start;text-underline-offset:3px}.cookie-actions{display:flex;gap:8px;flex-wrap:wrap}button{font:inherit;font-size:12px;font-weight:600;padding:10px 13px;border:1px solid var(--v7-control-line,#b5c5bc);border-radius:10px;background:#fff;color:var(--v7-ink);cursor:pointer;min-height:44px;}.cookie-actions button{flex:1}.primary{background:var(--v7-brand,#203b30);color:#fff;border-color:var(--v7-brand,#203b30)}.close-choice{padding:0;width:44px;flex-shrink:0;border:0;background:#f0f6f2;color:#365945;font-size:24px;line-height:1}.close-choice:hover{background:#e3efe7}.privacy-footer{box-sizing:content-box}.privacy-choice{display:block;margin:12px auto;font-size:12px;background:transparent;border:0;color:var(--v7-muted);min-height:44px;}
  @media(max-width:480px){.cookie-panel{inset-inline:12px;bottom:max(12px,env(safe-area-inset-bottom));width:auto;padding:16px}.cookie-actions button{padding-inline:8px}}
  button:focus-visible,a:focus-visible { outline:3px solid #8bcdc0; outline-offset:3px; }
</style>
