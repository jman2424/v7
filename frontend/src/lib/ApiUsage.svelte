<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  export let tenant: string;
  export let isPlatform = false;
  export let csrf = '';
  export let apiPrefix = '';
  type Totals = { calls: number; failed_calls: number; missing_usage_calls: number; unpriced_calls: number;
    input_tokens: number; cached_tokens: number; output_tokens: number; total_tokens: number; estimated_cost_gbp: number | null };
  type Row = Totals & { tenant: string; model: string; requested_model: string; channel: string; purpose: string };
  type Usage = { totals: Totals; breakdown: Row[]; breakdown_truncated: boolean; first_recorded_at: string | null;
    price_version: string; exchange_rate: { rate: number; date: string; source: string; stale: boolean } | null; configuration: { mode: string; planning_model: string; planning_enabled: boolean;
      rewriting_model: string; rewriting_enabled: boolean; can_change_model:boolean; model_options:{id:string;input_usd_per_million:number|null;cached_usd_per_million:number|null;output_usd_per_million:number|null}[] } };
  let data: Usage | null = null;
  let scope = 'company';
  let selectedModel = '';
  let step = 0;
  let changeToken = '';
  let changeBusy = false;
  let accepted = false;
  let savedMessage = '';
  function cancelChange() { step=0; changeToken=''; accepted=false; }
  async function changeModel(action:'review'|'confirm'|'save') {
    changeBusy=true; error=''; savedMessage='';
    try {
      const payload = action==='review' ? {model:selectedModel} : action==='confirm' ? {token:changeToken,acknowledge_cost_and_responses:accepted} : {token:changeToken,confirm_and_save:accepted};
      const response = await fetch(apiPrefix+'/admin/api/ai-model'+(action==='save'?'':'/'+action)+'?tenant='+encodeURIComponent(tenant), {method:action==='save'?'PUT':'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(payload)});
      if(!response.ok)throw new Error('Model change could not be saved. Refresh and review it again.');
      const result=await response.json();
      if(action==='save'){cancelChange();await refresh(tenant,scope,days);savedMessage='Model saved. New AI calls use this model. Test your agent to check its responses.';}
      else {selectedModel=result.model;changeToken=result.token;step=action==='review'?1:2;accepted=false;}
    } catch(failure) {cancelChange();error=failure instanceof Error?failure.message:'Could not change model.';}
    finally {changeBusy=false;}
  }
  let days = 30;
  let busy = false;
  let error = '';
  let mounted = false;
  let controller: AbortController | undefined;
  $: if (mounted) refresh(tenant, scope, days);
  onMount(() => { mounted = true; });
  onDestroy(() => controller?.abort());
  const number = (value: number) => value.toLocaleString();
  const money = (value: number | null) => value === null ? 'Unavailable' : value > 0 && value < 0.000001 ? '<£0.000001' : new Intl.NumberFormat('en-GB', {
    style: 'currency', currency: 'GBP', minimumFractionDigits: 2, maximumFractionDigits: 6
  }).format(value);

  async function refresh(company: string, selectedScope: string, period: number) {
    cancelChange();
    controller?.abort();
    const request = new AbortController();
    controller = request;
    busy = true;
    error = '';
    data = null;
    const timeout = setTimeout(() => request.abort(), 20000);
    try {
      const query = new URLSearchParams({ tenant: company, scope: selectedScope, days: String(period) });
      const response = await fetch(apiPrefix + '/admin/api/api-usage?' + query, {
        credentials: 'same-origin', signal: request.signal
      });
      if (!response.ok) throw new Error(response.status === 401 ? 'Your session expired. Sign in again.' : 'Could not load API usage. Try refreshing.');
      const result: Usage = await response.json();
      if (controller === request && !request.signal.aborted) { data = result; selectedModel=result.configuration.planning_model; }
    } catch (failure) {
      if (controller === request) error = request.signal.aborted ? 'The request timed out. Try refreshing.' : failure instanceof Error ? failure.message : 'Unable to load usage.';
    } finally {
      clearTimeout(timeout);
      if (controller === request) busy = false;
    }
  }
</script>

<section class="usage" aria-label="API usage and cost" aria-busy={busy}>
  <div class="toolbar">
    <div><h2>API usage &amp; cost</h2><p>Track the agent's OpenAI calls, including Test agent conversations.</p></div>
    <div class="controls">
      {#if isPlatform}<label>View<select bind:value={scope} disabled={changeBusy}><option value="company">Selected company</option><option value="all">All companies</option></select></label>{/if}
      <label>Time period<select bind:value={days} disabled={changeBusy}><option value={1}>Last 24 hours</option><option value={7}>Last 7 days</option><option value={30}>Last 30 days</option><option value={90}>Last 90 days</option></select></label>
      <button type="button" disabled={busy||changeBusy} on:click={() => refresh(tenant, scope, days)}>Refresh</button>
    </div>
  </div>
  {#if error}<p class="notice error" role="alert">{error}</p>{/if}
  {#if savedMessage}<p class="notice" role="status">{savedMessage}</p>{/if}
  {#if busy}<p class="notice" role="status">Loading API usage…</p>{/if}
  {#if data}
    <article class="panel">
      <h3>Current setup · {tenant}</h3>
      <div class="models">
        <div><span>Agent mode</span><strong>{data.configuration.mode}</strong></div>
        <div><span>Planning model</span><strong>{data.configuration.planning_model}</strong><small>{data.configuration.planning_enabled ? 'Available for AI planning' : 'AI planning inactive'}</small></div>
        <div><span>Reply rewriting model</span><strong>{data.configuration.rewriting_model}</strong><small>{data.configuration.rewriting_enabled ? 'Available when rewriting is needed' : 'AI rewriting inactive'}</small></div>
      </div>
      <p>Some answers use saved business information directly and need no API call. Actual response models appear below.</p>
      {#if scope==='company' && data.configuration.can_change_model}
        <h3>Change this business’s AI model</h3>
        <p>This changes both planning and reply rewriting. It can affect response wording, accuracy, speed and token usage. API costs can increase or decrease and are billed separately from your platform subscription.</p>
        <label>AI model<select bind:value={selectedModel} disabled={step>0||changeBusy}>
          {#if !data.configuration.model_options.some(option=>option.id===selectedModel)}<option value={selectedModel} disabled>{selectedModel} (current server configuration)</option>{/if}
          {#each data.configuration.model_options as option}<option value={option.id}>{option.id}</option>{/each}
        </select></label>
        {#each data.configuration.model_options.filter(option=>option.id===selectedModel) as option}
          {#if option.input_usd_per_million !== null}
            <p>Standard text rates per 1 million tokens: input ${option.input_usd_per_million}, cached input ${option.cached_usd_per_million}, output ${option.output_usd_per_million} USD. These are estimates, not a fixed per-message price. Actual costs depend on usage, exchange rates and provider pricing.</p>
          {:else}
            <p>Current pricing is not tracked for this model. Its calls and tokens will be recorded, but the API cost estimate will be unavailable. Check your provider billing before selecting it.</p>
          {/if}
        {/each}
        {#if step===0}<button type="button" disabled={changeBusy||!data.configuration.model_options.some(option=>option.id===selectedModel)} on:click={()=>changeModel('review')}>Review model change</button>
        {:else if step===1}
          <div class="notice" role="region" aria-label="First confirmation"><h4>Confirmation 1 of 2</h4><p>Switch {tenant} from {data.configuration.planning_model} to {selectedModel}. Response quality, behaviour and API charges may change. Availability depends on the platform’s provider account.</p><label><input type="checkbox" bind:checked={accepted} disabled={changeBusy}/> I understand that API usage, costs and responses may change.</label><button type="button" disabled={!accepted||changeBusy} on:click={()=>changeModel('confirm')}>Confirm and continue</button><button type="button" disabled={changeBusy} on:click={cancelChange}>Cancel</button></div>
        {:else}
          <div class="notice" role="region" aria-label="Final confirmation"><h4>Confirmation 2 of 2 — save</h4><p>Save {selectedModel} for {tenant}? This takes effect for new AI calls and may affect your charges and customer responses. You can change it again later using this same confirmation process.</p><label><input type="checkbox" bind:checked={accepted} disabled={changeBusy}/> I confirm this model and accept the possible cost and response changes.</label><button type="button" disabled={!accepted||changeBusy} on:click={()=>changeModel('save')}>{changeBusy?'Saving…':'Confirm again and save'}</button><button type="button" disabled={changeBusy} on:click={cancelChange}>Cancel</button></div>
        {/if}
      {/if}
    </article>
    <div class="metrics">
      <article class="panel"><span>Estimated cost · GBP</span><strong class="value">{money(data.totals.estimated_cost_gbp)}</strong><small>{data.totals.calls === 0 ? 'No API calls recorded in this period' : data.totals.unpriced_calls ? `${number(data.totals.unpriced_calls)} calls excluded: price or usage unavailable` : 'Based on recorded, priced calls'}</small></article>
      <article class="panel"><span>Recorded tokens</span><strong class="value">{number(data.totals.total_tokens)}</strong><small>{number(data.totals.input_tokens)} input · {number(data.totals.output_tokens)} output</small></article>
      <article class="panel"><span>Cached input tokens</span><strong class="value">{number(data.totals.cached_tokens)}</strong><small>Included in input tokens; discounted where priced</small></article>
      <article class="panel"><span>API calls</span><strong class="value">{number(data.totals.calls)}</strong><small>{number(data.totals.failed_calls)} failed · {number(data.totals.missing_usage_calls)} without token counts</small></article>
    </div>
    <article class="panel">
      <h3>Usage breakdown {scope === 'all' ? '· all companies' : '· selected company'}</h3>
      {#if data.breakdown.length}
        <!-- svelte-ignore a11y_no_noninteractive_tabindex (Keyboard users need to scroll the table horizontally on small screens.) -->
        <div class="table-wrap" role="region" aria-label="Usage by model and channel" tabindex="0">
          <table><thead><tr>{#if scope === 'all'}<th>Company</th>{/if}<th>Response model</th><th>Use</th><th>Calls</th><th>Input</th><th>Cached</th><th>Output</th><th>Est. GBP</th></tr></thead>
            <tbody>{#each data.breakdown as row}<tr>
              {#if scope === 'all'}<td>{row.tenant}</td>{/if}
              <td><strong>{row.model === 'unknown' ? 'Model not returned' : row.model}</strong><small>Requested: {row.requested_model}</small></td>
              <td>{row.purpose}<small>{row.channel === 'test' ? 'Test agent' : row.channel}</small></td>
              <td>{number(row.calls)}{#if row.failed_calls}<small>{row.failed_calls} failed</small>{/if}</td>
              <td>{number(row.input_tokens)}</td><td>{number(row.cached_tokens)}</td><td>{number(row.output_tokens)}</td>
              <td>{money(row.estimated_cost_gbp)}{#if row.unpriced_calls}<small>{row.unpriced_calls} unpriced</small>{/if}</td>
            </tr>{/each}</tbody></table>
        </div>
        {#if data.breakdown_truncated}<p>Showing the first 200 groups. Totals include all groups; narrow the company or time period for detail.</p>{/if}
      {:else}<p class="empty">No API calls recorded in this period. Try a conversation in Test agent with AI enabled to begin recording usage.</p>{/if}
    </article>
    {#if !data.exchange_rate}<p class="notice error" role="status">The pound conversion rate is unavailable. Token counts are still shown; refresh to retry the cost estimate.</p>
    {:else}<p class="footnote">Pound estimates use £{data.exchange_rate.rate} per US dollar · {data.exchange_rate.source}, {data.exchange_rate.date}.{data.exchange_rate.stale ? ' A newer rate is unavailable; the last saved reference rate is being used.' : ''} This reference conversion may differ from your card charge. <a href="https://frankfurter.dev/" target="_blank" rel="noreferrer">Rate source</a></p>{/if}
    <p class="footnote">Tracking starts with this feature; earlier spending is not imported. {#if data.first_recorded_at}Earliest retained call: {new Date(data.first_recorded_at).toLocaleString()}.{/if}
      Estimates use standard text prices checked on {data.price_version}, including cached-input discounts. Unknown models, missing usage and nonstandard service tiers are excluded, not counted as free.
      This is V7 usage, not your provider invoice; taxes, credits, other apps and unreported retries are not included.
      <a href="https://developers.openai.com/api/docs/pricing" target="_blank" rel="noreferrer">OpenAI pricing</a></p>
  {/if}
</section>

<style>
  .usage { display: grid; gap: 20px; min-width: 0; overflow-wrap: anywhere; }
  .toolbar, .controls { display: flex; flex-wrap: wrap; align-items: end; justify-content: space-between; gap: 14px; }
  .controls { justify-content: start; }
  h2, h3, p { margin: 0; } h2 { font-size: 20px; } h3 { font-size: 17px; margin-bottom: 16px; }
  p { color: #63716a; line-height: 1.55; } .toolbar p { margin-top: 7px; }
  label { display: grid; gap: 6px; font-size: 13px; font-weight: 600; }
  button, select { border: 1px solid #bbc4bc; border-radius: 6px; padding: 10px 12px; min-height: 42px; background: #fff; color: #26332b; font: inherit; max-width: 100%; }
  button { cursor: pointer; font-weight: 600; } button:disabled { opacity: .6; cursor: wait; }
  button:focus-visible, select:focus-visible, a:focus-visible, .table-wrap:focus-visible { outline: 3px solid #8bcdc0; outline-offset: 2px; }
  .panel { min-width: 0; padding: 20px; border: 1px solid #d9ddd7; border-radius: 8px; background: #fff; }
  .models { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 20px; margin-bottom: 18px; }
  .models strong, small, .value { display: block; } .models strong { margin-top: 6px; }
  .metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; }
  span, small { color: #63716a; } small { margin-top: 7px; font-size: 12px; line-height: 1.5; }
  .value { margin: 10px 0; color: #007d70; font-size: 27px; }
  .table-wrap { max-width: 100%; overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th, td { text-align: left; padding: 12px 10px; border-bottom: 1px solid #e4e8e1; vertical-align: top; }
  th { background: #f5f7f3; font-size: 12px; } td { min-width: 75px; } td:has(strong) { min-width: 160px; }
  .empty { padding: 12px 0; } .notice { padding: 20px; background: #fff; border-radius: 8px; }
  .error { color: #a12622; } .footnote { font-size: 12px; } a { color: #007d70; }
  @media(max-width: 1100px) { .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
  @media(max-width: 600px) { .models, .metrics { grid-template-columns: minmax(0, 1fr); } .panel { padding: 16px; } .controls { width: 100%; } }
</style>
