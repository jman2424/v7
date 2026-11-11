<script lang="ts">
  import DraftGuard from './DraftGuard.svelte';
  import ConfirmDialog from './ConfirmDialog.svelte';
  let draftConfirmation:ConfirmDialog;
  let savedDraft='';
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
  $: dirty=Boolean(savedDraft&&savedDraft!==JSON.stringify(parameters));
  let busy = false;
  let error = '';
  let status = '';
  const controller = new AbortController();
  onMount(() => { void load(); });
  onDestroy(() => controller.abort());
  async function load() {
    if(dirty&&!await draftConfirmation.ask())return;
    busy = true; error = '';
    try {
      const response = await fetch(apiPrefix+'/admin/api/ai-model/parameters?tenant='+encodeURIComponent(tenant), {credentials:'same-origin',signal:controller.signal});
      if (!response.ok) throw new Error();
      configuration = await response.json();
      if (!configuration) throw new Error();
      parameters = {...configuration.parameters};
      savedDraft=JSON.stringify(parameters);
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
      parameters = {...configuration.parameters};
      savedDraft=JSON.stringify(parameters); status = 'AI parameters saved.';
    } catch { if (!controller.signal.aborted) error = 'Could not save AI settings. Try again.'; }
    finally { busy = false; }
  }
</script>
<DraftGuard {dirty}/><ConfirmDialog bind:this={draftConfirmation}/>

<section class="parameters" aria-labelledby="parameters-title">
  <header><div><p class="eyebrow">{$t('Response controls')}</p><h2 id="parameters-title">{$t('AI parameters')}</h2></div><button type="button" disabled={busy} on:click={load}>{$t('Refresh')}</button></header>
  <p class="description">{$t('Tune response length and reasoning for this business. Business facts, permissions and safety rules remain required.')}</p>
  {#if configuration}
    <div class="model"><div><span class="model-label">{$t('Current model')}</span><strong>{configuration.model}</strong></div><span class="api-label">{configuration.effective.api === 'responses' ? 'Responses API' : 'Chat Completions API'}</span></div>
    <form aria-busy={busy} on:submit|preventDefault={save}>
      <label>{$t('Maximum output tokens')}<input type="number" min={configuration.capabilities.max_output_tokens.min} max={configuration.capabilities.max_output_tokens.max} step="1" bind:value={parameters.max_output_tokens} disabled={busy} required/><small>{$t('Includes reasoning tokens. Larger limits can increase cost and response time.')}</small></label>
      <label>{$t('Request timeout (seconds)')}<input type="number" min={configuration.capabilities.timeout_seconds.min} max={configuration.capabilities.timeout_seconds.max} step="1" bind:value={parameters.timeout_seconds} disabled={busy} required/></label>
      {#if configuration.capabilities.reasoning_efforts.length}
        <label>{$t('Reasoning effort')}<select bind:value={parameters.reasoning_effort} disabled={busy}>{#each configuration.capabilities.reasoning_efforts as effort}<option value={effort}>{$t(effort)}</option>{/each}</select></label>
      {/if}
      <label>{$t('Temperature')}<input type="number" min="0" max="1" step=".05" bind:value={parameters.temperature} disabled={busy || !temperatureSupported} required/><small>{temperatureSupported ? $t('Lower values keep wording more consistent.') : $t('This model uses reasoning controls instead of temperature.')}</small></label>
      <div class="actions"><button class="primary" type="submit" disabled={busy}>{$t(busy?'Saving…':'Save changes')}</button>{#if status}<p class="save-status" role="status">{$t(status)}</p>{/if}</div>
    </form>
    <details><summary>{$t('Agent boundaries')}</summary><ul>{#each configuration.guardrails as rule}<li>{$t(rule)}</li>{/each}</ul></details>
  {:else if !error}<p class="loading" role="status"><span class="loading-indicator" aria-hidden="true"></span>{$t('Loading…')}</p>{/if}
  {#if error}<p class="error" role="alert">{$t(error)}</p>{/if}
</section>

<style>
  .parameters { min-width:0; background:var(--v7-surface, #fff); border:1px solid var(--v7-line, var(--v7-line)); border-radius:var(--v7-radius-panel); padding:24px; margin-bottom:24px; color:var(--v7-ink, var(--v7-ink)); overflow-wrap:anywhere; }
  header, .model, .actions { display:flex; align-items:center; justify-content:space-between; gap:16px; flex-wrap:wrap; }
  header > div { min-width:0; }
  .eyebrow { margin:0 0 8px; color:var(--v7-accent, var(--v7-accent)); font-size:var(--v7-text-xs); font-weight:700; text-transform:uppercase; letter-spacing:.08em; }
  h2 { margin:0; font-size:var(--v7-text-xl); font-weight:650; letter-spacing:-.025em; }
  p, li { line-height:1.65; color:var(--v7-muted, var(--v7-muted)); font-size:var(--v7-text-sm); }
  .description { max-width:72ch; margin:12px 0 0; }
  .model { padding:16px 18px; background:var(--v7-canvas, var(--v7-canvas)); border:1px solid var(--v7-line, var(--v7-line)); border-radius:var(--v7-radius-control); margin:22px 0; }
  .model > div { display:grid; gap:4px; min-width:0; }
  .model strong { font-size:var(--v7-text-sm); font-weight:600; }
  .model-label { font-size:var(--v7-text-xs); font-weight:600; color:var(--v7-muted, var(--v7-muted)); }
  .api-label { padding:5px 9px; border:1px solid var(--v7-line, var(--v7-line)); border-radius:var(--v7-radius-control); background:var(--v7-surface, #fff); font-size:var(--v7-text-xs); color:var(--v7-muted, var(--v7-muted)); }
  form { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:22px 24px; }
  label { display:flex; flex-direction:column; align-items:stretch; gap:8px; min-width:0; font-size:var(--v7-text-sm); font-weight:600; }
  input, select { width:100%; min-width:0; min-height:44px; padding:10px 12px; border:1px solid var(--v7-control-line, var(--v7-control-line)); border-radius:var(--v7-radius-control); font:inherit; color:inherit; background:var(--v7-surface, #fff); }
  input:disabled, select:disabled { background:var(--v7-canvas, var(--v7-canvas)); color:var(--v7-muted, var(--v7-muted)); }
  small { font-size:var(--v7-text-xs); font-weight:400; color:var(--v7-muted, var(--v7-muted)); line-height:1.6; }
  .actions { grid-column:1/-1; justify-content:flex-start; padding-top:18px; margin-top:2px; border-top:1px solid var(--v7-line, var(--v7-line)); }
  button { min-height:44px; padding:10px 16px; border:1px solid var(--v7-control-line, var(--v7-control-line)); border-radius:var(--v7-radius-control); color:inherit; background:var(--v7-surface, #fff); font:inherit; font-size:var(--v7-text-sm); font-weight:600; }
  button:hover:not(:disabled) { background:var(--v7-soft, var(--v7-tint)); border-color:var(--v7-accent, var(--v7-accent)); }
  .primary { background:var(--v7-accent, var(--v7-accent)); color:#fff; border-color:var(--v7-accent, var(--v7-accent)); }
  .primary:hover:not(:disabled) { background:var(--v7-accent-hover); border-color:var(--v7-accent-hover); }
  .save-status { margin:0; font-size:var(--v7-text-sm); color:var(--v7-accent, var(--v7-accent)); }
  details { margin-top:24px; padding-top:8px; border-top:1px solid var(--v7-line, var(--v7-line)); }
  summary { min-height:44px; padding:10px 0; font-size:var(--v7-text-sm); font-weight:600; cursor:pointer; }
  details ul { margin:6px 0 0; padding-inline-start:20px; }
  details li { margin-bottom:6px; font-size:var(--v7-text-sm); }
  .loading { display:flex; align-items:center; gap:10px; padding:18px; margin:22px 0 0; border-radius:var(--v7-radius-control); background:var(--v7-canvas, var(--v7-canvas)); font-size:var(--v7-text-sm); }
  .loading-indicator { width:14px; height:14px; border:2px solid var(--v7-tint-line); border-top-color:var(--v7-accent, var(--v7-accent)); border-radius:50%; animation:parameters-spin .8s linear infinite; }
  .error { padding:12px 14px; margin:18px 0 0; border:1px solid var(--v7-danger-line); border-radius:var(--v7-radius-control); background:var(--v7-danger-soft); color:var(--v7-danger); font-size:var(--v7-text-sm); }
  :is(button, input, select, summary):focus-visible { outline:3px solid var(--v7-focus); outline-offset:3px; }
  @keyframes parameters-spin { to { transform:rotate(360deg); } }
  @media (prefers-reduced-motion:reduce) { .loading-indicator { animation:none; } }
  @media (max-width:700px) { form { grid-template-columns:1fr; gap:20px; } .parameters { padding:18px; } }
  @media (max-width:420px) { header > button { width:100%; } .actions > button { width:100%; } }
</style>
