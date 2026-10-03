<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { t } from './i18n';
  export let tenant: string;
  export let apiPrefix = '';
  type Provider = {enabled:boolean;configured:boolean;state:string;recipients:string[];missing_settings:string[];invalid_settings:string[]};
  type Status = {provider_mode:string;ready:boolean;tenant_active:boolean;subscription_enabled:boolean;blockers:{code:string;action:string}[];providers:{meta:Provider;twilio:Provider};voice:{configured:boolean;ready:boolean;transcription_model:string;reply_mode:string;missing_settings:string[];invalid_settings:string[]}};
  let status: Status|null = null;
  let busy = false;
  let error = '';
  let controller = new AbortController();
  const stateNames:Record<string,string> = {disabled:'Disabled',unassigned:'Business number not assigned',missing_settings:'Awaiting provider settings',invalid_configuration:'Configuration needs attention',configured:'Configured locally'};
  onMount(() => { void load(); });
  onDestroy(() => controller.abort());
  async function load() {
    if (busy) return;
    if (controller.signal.aborted) controller = new AbortController();
    busy = true; error = '';
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(apiPrefix+'/admin/api/integrations?tenant='+encodeURIComponent(tenant), {credentials:'same-origin',signal:controller.signal});
      if (!response.ok) throw new Error();
      const data = await response.json();
      if (!data.whatsapp) throw new Error();
      status = data.whatsapp;
    } catch { error = 'Could not load WhatsApp setup. Reload or sign in again.'; }
    finally { clearTimeout(timeout); busy = false; }
  }
</script>

<section class="whatsapp" aria-labelledby="whatsapp-setup-title">
  <header><div><p class="eyebrow">{$t('Customer channels')}</p><h2 id="whatsapp-setup-title">{$t('WhatsApp setup')}</h2></div><button type="button" disabled={busy} on:click={load}>{$t('Refresh')}</button></header>
  <p>{$t('Review the connection assigned to this business. These checks inspect local settings; they do not confirm delivery with the provider.')}</p>
  {#if status}
    <div class="summary"><strong>{$t(status.ready?'Configured locally':'Setup needs attention')}</strong><span>{$t('Provider')}: {status.provider_mode}</span></div>
    {#if status.blockers.length}<ul class="blockers">{#each status.blockers as blocker}<li>{$t(blocker.action)}</li>{/each}</ul>{/if}
    <div class="providers">
      {#each Object.entries(status.providers) as [name,provider]}
        <article><div class="provider-head"><h3>{name === 'meta'?'Meta Cloud API':'Twilio'}</h3><span>{$t(stateNames[provider.state]||'Configuration needs attention')}</span></div>
          <p>{$t('Assigned business numbers')}: {provider.recipients.length?provider.recipients.join(', '):$t('None assigned')}</p>
          {#if provider.enabled && provider.missing_settings.length}<p>{$t('Missing server settings')}: <code>{provider.missing_settings.join(', ')}</code></p>{/if}
          {#if provider.invalid_settings.length}<p class="error">{$t('Check server settings')}: <code>{provider.invalid_settings.join(', ')}</code></p>{/if}
        </article>
      {/each}
    </div>
    <article class="voice"><h3>{$t('Voice messages')}</h3><p>{$t(status.voice.ready?'Voice transcription configured locally':'Voice transcription awaiting setup')}</p><p>{$t('Transcription model')}: <code>{status.voice.transcription_model}</code></p><p>{$t('Customers can send supported audio messages. The agent replies with text; it does not send generated voice replies.')}</p>{#if status.voice.missing_settings.length}<p>{$t('Missing server settings')}: <code>{status.voice.missing_settings.join(', ')}</code></p>{/if}{#if status.voice.invalid_settings.length}<p class="error">{$t('Check server settings')}: <code>{status.voice.invalid_settings.join(', ')}</code></p>{/if}</article>
  {:else if !error}<p role="status">{$t('Loading…')}</p>{/if}
  {#if error}<p class="error" role="alert">{$t(error)}</p>{/if}
</section>

<style>
  .whatsapp{grid-column:1/-1;border:1px solid var(--v7-line);background:white;border-radius:var(--v7-radius, 18px);padding:24px;color:var(--v7-ink);margin-bottom:24px;box-shadow:var(--v7-card-shadow, 0 8px 28px #203b3008);}header,.summary,.provider-head{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.eyebrow{font-size:11px;letter-spacing:.1em;text-transform:uppercase;margin:0 0 8px;color:var(--v7-accent);font-weight:700;}h2{font-size:22px;margin:0}h3{font-size:16px;margin:0}.summary{padding:18px;background:var(--v7-soft, #f0f6f2);border-radius:10px;border:1px solid var(--v7-line);margin-top:20px;}.summary span,.provider-head span{font-size:12px;color:var(--v7-muted)}p,li{font-size:14px;line-height:1.6;color:var(--v7-muted)}.providers{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin:20px 0}article{padding:20px;border:1px solid var(--v7-line);border-radius:14px;min-width:0;background:var(--v7-soft, #f0f6f2);}code{overflow-wrap:anywhere;font-size:12px}.error{color:#a61b2b}.blockers{padding:16px 16px 16px 32px;background:#fff8e8;border:1px solid #e6d6b0;border-radius:12px}button{min-height:44px;padding:10px 16px;border:1px solid var(--v7-control-line, #b5c5bc);border-radius:10px;color:inherit;background:white;font:inherit}@media(max-width:700px){.providers{grid-template-columns:1fr}.whatsapp{padding:18px}}
</style>
