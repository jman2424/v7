<script lang="ts">
  import {onMount, onDestroy} from 'svelte';
  export let tenant:string;
  export let csrf='';
  export let apiPrefix='';
  type Settings={enabled:boolean;history_messages:number;history_tokens:number;retention_minutes:number};
  type Configuration={settings:Settings;revision:string;model:string;scope:string;storage:string;cost:{price_version:string;input_usd_per_million:number|null;history_usd_per_1000_replies:number|null}};
  let configuration:Configuration|null=null;
  let settings:Settings={enabled:true,history_messages:12,history_tokens:2048,retention_minutes:60};
  let busy=false,error='',message='',confirmClear=false;
  const controller=new AbortController();
  $: estimated=configuration?.cost.input_usd_per_million==null?null:(settings.enabled?settings.history_tokens:0)*configuration.cost.input_usd_per_million/1000;
  const dollars=(value:number|null)=>value===null?'Unavailable':new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:6}).format(value);
  onMount(()=>{void load();});
  onDestroy(()=>controller.abort());
  async function load(){busy=true;error='';try{
    const result=await fetch(apiPrefix+'/admin/api/ai-model/memory?tenant='+encodeURIComponent(tenant),{credentials:'same-origin',signal:controller.signal});
    if(!result.ok)throw new Error();configuration=await result.json();if(!configuration)throw new Error();settings={...configuration.settings};
  }catch{if(!controller.signal.aborted)error='Could not load conversation memory settings.';}finally{busy=false;}}
  async function save(clear=false){if(busy||!configuration||(clear&&!confirmClear))return;busy=true;error='';message='';try{
    const result=await fetch(apiPrefix+'/admin/api/ai-model/memory?tenant='+encodeURIComponent(tenant),{method:clear?'DELETE':'PUT',credentials:'same-origin',signal:controller.signal,headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify({settings,revision:configuration.revision})});
    if(result.status===409){error='Settings changed in another session. Refresh before saving.';return;}if(!result.ok)throw new Error();
    configuration=await result.json();if(!configuration)throw new Error();settings={...configuration.settings};confirmClear=false;message=clear?'Active conversation memory cleared.':'Conversation memory settings saved.';
  }catch{if(!controller.signal.aborted)error='Could not save memory settings. Check the values or sign in again.';}finally{busy=false;}}
</script>

<section class="memory" aria-labelledby="memory-title" aria-busy={busy}>
  <header><div><p class="eyebrow">Conversation controls</p><h2 id="memory-title">AI memory</h2></div><button disabled={busy} on:click={load}>Refresh</button></header>
  <p>Remember the current conversation’s recent messages, choices and stated needs. Each conversation stays separate; returning customers are not matched across conversations.</p>
  {#if configuration}
    <form on:submit|preventDefault={()=>save()}>
      <label class="toggle"><input type="checkbox" bind:checked={settings.enabled} disabled={busy}/> Enable conversation memory</label>
      <div class="fields">
        <label>Recent messages<input type="number" min="2" max="40" step="1" bind:value={settings.history_messages} required disabled={busy||!settings.enabled}/><small>Individual customer and agent messages, not pairs.</small></label>
        <label>Transcript token budget<input type="number" min="256" max="16384" step="1" bind:value={settings.history_tokens} required disabled={busy||!settings.enabled}/><small>A conservative byte-based limit. Recent messages are preferred; messages too large to fit are omitted. Verified task facts are kept separately.</small></label>
        <label>Memory lifetime (minutes)<input type="number" min="5" max="10080" step="1" bind:value={settings.retention_minutes} required disabled={busy||!settings.enabled}/><small>Expires each remembered item after its last update. Expired rows are cleaned up during subsequent activity.</small></label>
      </div>
      <aside><strong>Estimated transcript input cost: up to {dollars(estimated)} per 1,000 replies</strong><p>Uses {configuration.model} and the server’s configured uncached input rate. More history can increase cost and response time. Shorter history can reduce recall. No extra summarization AI call is added.</p><p>This estimate covers only the recent transcript. Business knowledge, verified task facts, new messages, outputs and reasoning add cost. Caching can reduce input charges; actual provider usage, exchange rates and wallet pricing determine your charge.</p></aside>
      <button class="primary" disabled={busy}>{busy?'Saving…':'Save memory settings'}</button>
    </form>
    <details><summary>Clear active memory</summary><p>This forgets active AI context for this business’s conversations. It does not delete conversation records, leads or billing history.</p><label class="toggle"><input type="checkbox" bind:checked={confirmClear} disabled={busy}/> Clear active memory for this business</label><button type="button" disabled={busy||!confirmClear} on:click={()=>save(true)}>Clear memory</button></details>
  {/if}
  {#if error}<p class="error" role="alert">{error}</p>{/if}
  {#if message}<p role="status">{message}</p>{/if}
</section>

<style>
  .memory{border:1px solid var(--v7-line,#e1e7e4);border-radius:12px;background:var(--v7-surface,#fff);padding:24px;margin:24px 0;color:var(--v7-ink,#172b26);overflow-wrap:anywhere}header{display:flex;justify-content:space-between;align-items:center;gap:16px}h2{margin:0}.eyebrow{color:var(--v7-accent,#087f5b);font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.08em}.fields{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px;margin:20px 0}label{display:grid;gap:8px;font-size:14px;font-weight:600}.toggle{display:flex;align-items:center;gap:10px;margin:16px 0}input:not([type=checkbox]){width:100%;box-sizing:border-box;padding:10px;border:1px solid var(--v7-line,#e1e7e4);border-radius:7px;background:var(--v7-surface,#fff);color:inherit}p,small{line-height:1.6;color:var(--v7-muted,#64716d);font-weight:400}small{font-size:12px}aside{padding:18px;background:var(--v7-canvas,#f5f7f7);border-radius:8px;margin:20px 0}aside p{font-size:13px}button{padding:10px 14px;border:1px solid var(--v7-line,#e1e7e4);border-radius:7px;background:var(--v7-surface,#fff);color:inherit;cursor:pointer}.primary{background:var(--v7-accent,#087f5b);color:white}button:disabled{opacity:.55;cursor:not-allowed}details{margin-top:24px;border-top:1px solid var(--v7-line,#e1e7e4);padding-top:18px}summary{cursor:pointer;font-weight:600}.error{color:#a12622}:is(button,input,summary):focus-visible{outline:3px solid var(--v7-focus);outline-offset:3px}@media(max-width:700px){.fields{grid-template-columns:1fr}.memory{padding:18px}}
</style>
