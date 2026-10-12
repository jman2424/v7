<script lang="ts">
  import {onMount,onDestroy} from 'svelte';
  import {t,language} from './i18n';
  import {subscriptionLocales} from './subscription-format';
  export let tenant:string;
  export let csrf:string;
  export let apiPrefix='';
  export let enabled=true;
  type Option={id:string;input_usd_per_million:number|null;cached_usd_per_million:number|null;output_usd_per_million:number|null};
  type Configuration={tenant:string;model:string;model_options:Option[];can_change_model:boolean};
  let data:Configuration|null=null;
  let selected='';
  let busy=false;
  let error='';
  let saved=false;
  let step=0;
  let token='';
  let accepted=false;
  let disposed=false;
  let controller:AbortController|undefined;
  $: rate=(value:number|null)=>value==null?$t('Not available'):new Intl.NumberFormat(subscriptionLocales[$language],{style:'currency',currency:'USD',maximumFractionDigits:6}).format(value);
  function cancel(){step=0;token='';accepted=false;}
  async function run(action:'load'|'review'|'confirm'|'save') {
    if(busy||disposed||!enabled)return;
    if(action!=='load'&&(!data?.can_change_model||!data.model_options.some(row=>row.id===selected&&row.input_usd_per_million!=null&&row.output_usd_per_million!=null)))return;
    if((action==='confirm'||action==='save')&&!accepted)return;
    busy=true;error='';saved=false;
    const pending=new AbortController();controller=pending;
    const timeout=setTimeout(()=>pending.abort(),20000);
    try {
      const payload=action==='review'?{model:selected}:action==='confirm'?{token,acknowledge_cost_and_responses:accepted}:{token,confirm_and_save:accepted};
      const response=await fetch(apiPrefix+'/admin/api/ai-model'+(action==='load'||action==='save'?'':'/'+action)+'?tenant='+encodeURIComponent(tenant),{
        credentials:'same-origin',signal:pending.signal,...(action==='load'?{}:{method:action==='save'?'PUT':'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(payload)})});
      if(!response.ok)throw new Error('model_request_failed');
      const result=await response.json();
      if(disposed||pending.signal.aborted)return;
      if(action==='load') {
        if(result.tenant!==tenant||!Array.isArray(result.model_options)||typeof result.model!=='string')throw new Error('model_response_invalid');
        data=result;selected=result.model;
      } else if(action==='save') {cancel();if(data)data={...data,model:result.model};selected=result.model;saved=true;}
      else {if(typeof result.token!=='string'||result.model!==selected)throw new Error('model_response_invalid');token=result.token;step=action==='review'?1:2;accepted=false;}
    } catch {
      if(!disposed){cancel();error='AI models could not be updated. Refresh and review the change again.';}
    } finally {clearTimeout(timeout);if(controller===pending)controller=undefined;if(!disposed)busy=false;}
  }
  onMount(()=>{if(enabled)void run('load');});
  onDestroy(()=>{disposed=true;controller?.abort();});
</script>

<section class="models" aria-label={$t('AI model and message capacity')}>
  <header><div><h2>{$t('AI model and message capacity')}</h2><p>{$t('There is no fixed message or conversation cap. Your prepaid credit pays for the selected model and the tokens each request uses. Lower-cost models usually allow more messages; longer conversations and replies use more credit.')}</p></div><button disabled={busy||!enabled} on:click={()=>{cancel();run('load');}}>{$t('Refresh models')}</button></header>
  {#if !enabled}<p>{$t('Activate your subscription before changing the AI model.')}</p>{/if}
  {#if error}<p role="alert">{$t(error)}</p>{/if}
  {#if busy}<p role="status">{$t('Updating AI model…')}</p>{/if}
  {#if saved}<p role="status">{$t('AI model saved. New requests use its pricing; earlier charges keep their recorded rates.')}</p>{/if}
  {#if data}
    {#if !data.can_change_model}<p>{$t('Model changes require business activation and owner permissions.')}</p>{/if}
    <p>{$t('Current AI model: {model}',{model:data.model})}</p>
    <p>{$t('One customer message can require multiple AI calls. Charges include input, conversation context, cached input and output tokens. There is no guaranteed number of messages per top-up.')}</p>
    <p>{$t('Provider prices per million tokens in USD. Your usage ledger converts charges to GBP using the recorded exchange rate and agreed markup. Model access still depends on the central provider account.')}</p>
    <details><summary>{$t('Compare all available models')}</summary>
      <!-- svelte-ignore a11y_no_noninteractive_tabindex (Keyboard users need to scroll this price table on small screens.) -->
      <div class="scroll" role="region" aria-label={$t('AI model prices')} tabindex="0"><table><thead><tr><th>{$t('AI model')}</th><th>{$t('Input tokens')}</th><th>{$t('Cached input')}</th><th>{$t('Output tokens')}</th></tr></thead><tbody>{#each data.model_options as row}<tr class:current={row.id===data.model}><td><bdi>{row.id}</bdi></td><td><bdi>{rate(row.input_usd_per_million)}</bdi></td><td><bdi>{rate(row.cached_usd_per_million)}</bdi></td><td><bdi>{rate(row.output_usd_per_million)}</bdi></td></tr>{/each}</tbody></table></div></details>
    {#if data.can_change_model}
      <label>{$t('Choose an AI model')}<select bind:value={selected} disabled={busy||step>0}>{#if !data.model_options.some(row=>row.id===selected)}<option value={selected} disabled>{selected}</option>{/if}{#each data.model_options as row}<option value={row.id} disabled={row.input_usd_per_million==null||row.output_usd_per_million==null}>{row.id} · {rate(row.input_usd_per_million)} / {rate(row.output_usd_per_million)}</option>{/each}</select></label>
      <p>{$t('Changing the model affects both AI planning and reply rewriting, including response quality, speed and credit consumption. This does not fund or activate the provider account.')}</p>
      {#if step===0}<button disabled={busy||selected===data.model} on:click={()=>run('review')}>{$t('Review model change')}</button>
      {:else if step===1}<label class="confirmation"><input type="checkbox" bind:checked={accepted} disabled={busy}/>{$t('I understand that this model changes response behaviour and usage-credit costs.')}</label><button disabled={busy||!accepted} on:click={()=>run('confirm')}>{$t('Confirm model choice')}</button>
      {:else}<label class="confirmation"><input type="checkbox" bind:checked={accepted} disabled={busy}/>{$t('I confirm this model for {tenant}.',{tenant})}</label><button disabled={busy||!accepted} on:click={()=>run('save')}>{$t('Save AI model')}</button>{/if}
      {#if step>0}<button disabled={busy} on:click={cancel}>{$t('Cancel')}</button>{/if}
    {/if}
  {/if}
</section>
<style>
  .models{padding:20px;border:1px solid var(--v7-line);border-radius:12px;background:var(--v7-surface);min-width:0;overflow-wrap:anywhere}
  header{display:flex;align-items:start;gap:16px;justify-content:space-between;flex-wrap:wrap}header>div{flex:1 1 300px}
  h2{font-size:21px;margin:0 0 8px}p{font-size:13px;line-height:1.65;color:var(--v7-muted)}
  label{display:grid;gap:8px;margin:16px 0;font-weight:600;font-size:13px}select{width:100%;min-height:44px;padding:10px;border:1px solid var(--v7-control-line);border-radius:8px;background:var(--v7-surface);color:var(--v7-ink)}
  button{min-height:44px;padding:10px 16px;border-radius:8px;border:1px solid var(--v7-control-line);background:var(--v7-surface);color:var(--v7-ink);margin-inline-end:8px}
  .confirmation{display:flex;align-items:start;font-weight:400}.confirmation input{margin-block-start:3px}
  summary{cursor:pointer;padding:12px 0;font-weight:600}.scroll{overflow:auto;max-width:100%}table{width:100%;border-collapse:collapse;font-size:13px}th,td{padding:12px;text-align:start;border-bottom:1px solid var(--v7-line)}.current{background:var(--v7-tint)}
</style>
