<script lang="ts">
  import { onMount } from 'svelte';
  import { choosePreferences, preferenceChoice, t } from './i18n';
  let open = false;
  onMount(() => { open = !preferenceChoice(); });
</script>
{#if open}
  <aside class="cookie-panel" aria-label={$t('Cookie preferences')}>
    <div><strong>{$t('Your privacy choices')}</strong><p>{$t('Sign-in and security cookies are essential. Saving your language is optional. No advertising cookies are used.')}</p><a href="/cookies" target="_blank" rel="noopener">{$t('Cookie information')}</a></div>
    <div class="cookie-actions"><button type="button" on:click={() => {choosePreferences('essential'); open = false;}}>{$t('Essential only')}</button><button class="primary" type="button" on:click={() => {choosePreferences('all'); open = false;}}>{$t('Save my preferences')}</button></div>
  </aside>
{/if}
<button class="privacy-choice" type="button" on:click={() => open = true}>{$t('Cookie preferences')}</button>
<style>
  .cookie-panel{position:fixed;bottom:22px;inset-inline:22px;z-index:1000;display:flex;align-items:center;gap:24px;max-width:1040px;margin:auto;padding:22px;border:1px solid var(--v7-line);border-radius:18px;background:#fff;box-shadow:0 20px 70px #263f3014;color:var(--v7-ink)}
  p{font-size:13px;max-width:620px;margin:8px 0;line-height:1.65;}a{font-size:12px;color:var(--v7-accent)}.cookie-actions{display:flex;gap:10px;flex:none;flex-wrap:wrap}button{font:inherit;padding:10px 13px;border:1px solid var(--v7-control-line, #b5c5bc);border-radius:10px;background:#fff;color:var(--v7-ink);cursor:pointer;min-height:44px;}.primary{background:var(--v7-accent);color:#fff;border-color:var(--v7-accent)}.privacy-choice{display:block;margin:20px auto;font-size:12px;background:transparent;border:0;color:var(--v7-muted);min-height:44px;}
  @media(max-width:700px){.cookie-panel{inset-inline:12px;bottom:12px;flex-direction:column;align-items:stretch;gap:12px}.cookie-actions button{flex:1}}
  button:focus-visible,a:focus-visible { outline:3px solid #8bcdc0; outline-offset:3px; }
</style>
