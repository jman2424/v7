<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { t } from './i18n';
  export let tenant: string;
  export let csrf: string;
  export let apiPrefix = '';
  type Parameters = {temperature:number;max_output_tokens:number;reasoning_effort:string|null;timeout_seconds:number};
  type Configuration = {model:string;revision:string;parameters:Parameters;effective:{temperature:number|null;reasoning_effort:string|null;api:string};capabilities:{temperature:boolean;reasoning_efforts:string[];max_output_tokens:{min:number;max:number};timeout_seconds:{min:number;max:number}};guardrails:string[]};
  let configuration: Configuration|null = null;
  let parameters: Parameters = {temperature:.2,max_output_tokens:1024,reasoning_effort:'low',timeout_seconds:30};
  $: temperatureSupported = Boolean(configuration && (configuration.capabilities.reasoning_efforts.length ? parameters.reasoning_effort === 'none' : configuration.capabilities.temperature));
  let busy = false;
  let error = '';
  let status = '';
  const controller = new AbortController();
  onMount(() => { void load(); });
  onDestroy(() => controller.abort());
  async function load() {
    busy = true; error = '';
    try {
      const response = await fetch(apiPrefix+'/admin/api/ai-model/parameters?tenant='+encodeURIComponent(tenant), {credentials:'same-origin',signal:controller.signal});
      if (!response.ok) throw new Error();
      configuration = await response.json();
      if (!configuration) throw new Error();
      parameters = {...configuration.parameters};
    } catch { if (!controller.signal.aborted) error = 'Could not load AI settings. Refresh or sign in again.'; }
    finally { busy = false; }
  }
  async function save() {
    if (busy || !configuration) return;
    busy = true; error = ''; status = '';
    try {
      const response = await fetch(apiPrefix+'/admin/api/ai-model/parameters?tenant='+encodeURIComponent(tenant), {method:'PUT',credentials:'same-origin',signal:controller.signal,headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify({parameters,revision:configuration.revision})});
      if (response.status === 409) { error = 'These settings changed in another session. Refresh before saving.'; return; }
      if (!response.ok) { error = 'Could not save AI settings. Check the values or sign in again.'; return; }
      configuration = await response.json();
      if (!configuration) throw new Error();
      parameters = {...configuration.parameters}; status = 'AI parameters saved.';
    } catch { if (!controller.signal.aborted) error = 'Could not save AI settings. Try again.'; }
    finally { busy = false; }
  }
</script>

<section class="parameters" aria-labelledby="parameters-title">
  <header><div><p class="eyebrow">{$t('Response controls')}</p><h2 id="parameters-title">{$t('AI parameters')}</h2></div><button type="button" disabled={busy} on:click={load}>{$t('Refresh')}</button></header>
  <p>{$t('Tune response length and reasoning for this business. Business facts, permissions and safety rules remain required.')}</p>
  {#if configuration}
    <div class="model"><strong>{configuration.model}</strong><span>{configuration.effective.api === 'responses' ? 'Responses API' : 'Chat Completions API'}</span></div>
    <form aria-busy={busy} on:submit|preventDefault={save}>
      <label>{$t('Maximum output tokens')}<input type="number" min={configuration.capabilities.max_output_tokens.min} max={configuration.capabilities.max_output_tokens.max} step="1" bind:value={parameters.max_output_tokens} disabled={busy} required/><small>{$t('Includes reasoning tokens. Larger limits can increase cost and response time.')}</small></label>
      <label>{$t('Request timeout (seconds)')}<input type="number" min={configuration.capabilities.timeout_seconds.min} max={configuration.capabilities.timeout_seconds.max} step="1" bind:value={parameters.timeout_seconds} disabled={busy} required/></label>
      {#if configuration.capabilities.reasoning_efforts.length}
        <label>{$t('Reasoning effort')}<select bind:value={parameters.reasoning_effort} disabled={busy}>{#each configuration.capabilities.reasoning_efforts as effort}<option value={effort}>{$t(effort)}</option>{/each}</select></label>
      {/if}
      <label>{$t('Temperature')}<input type="number" min="0" max="1" step=".05" bind:value={parameters.temperature} disabled={busy || !temperatureSupported} required/><small>{temperatureSupported ? $t('Lower values keep wording more consistent.') : $t('This model uses reasoning controls instead of temperature.')}</small></label>
      <div class="actions"><button class="primary" type="submit" disabled={busy}>{$t(busy?'Saving…':'Save changes')}</button>{#if status}<p role="status">{$t(status)}</p>{/if}</div>
    </form>
    <details><summary>{$t('Agent boundaries')}</summary><ul>{#each configuration.guardrails as rule}<li>{$t(rule)}</li>{/each}</ul></details>
  {:else if !error}<p role="status">{$t('Loading…')}</p>{/if}
  {#if error}<p class="error" role="alert">{$t(error)}</p>{/if}
</section>

<style>
  .parameters{background:#fff;border:1px solid #dce2ed;border-radius:18px;padding:24px;margin-bottom:24px;color:#17233c}header,.model,.actions{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}.eyebrow{font-size:11px;color:#5e6b82;text-transform:uppercase;letter-spacing:.1em;margin:0 0 8px}h2{font-size:22px;margin:0}p,li{line-height:1.6;color:#5e6b82;font-size:14px}.model{justify-content:flex-start;padding:12px 16px;background:#f4f6fd;border-radius:10px;margin:18px 0}.model span{font-size:12px;color:#5e6b82}form{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}label{display:grid;gap:8px;font-size:13px;font-weight:650}input,select{width:100%;min-height:44px;padding:10px;border:1px solid #bec9dc;border-radius:9px;font:inherit;color:inherit;background:white}input:disabled{background:#f3f5fa}small{font-weight:400;color:#5e6b82;line-height:1.5}.actions{grid-column:1/-1;justify-content:flex-start}button{min-height:42px;padding:10px 16px;border:1px solid #bec9dc;border-radius:9px;color:inherit;background:white;font:inherit}.primary{background:#3e53c4;color:white;border-color:#3e53c4}details{margin-top:20px;padding-top:16px;border-top:1px solid #dce2ed}summary{font-weight:650;cursor:pointer}.error{color:#a61b2b}@media(max-width:700px){form{grid-template-columns:1fr}.parameters{padding:18px}}
</style>
