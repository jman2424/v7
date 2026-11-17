<script lang="ts">
  import {onMount,onDestroy} from 'svelte';
  export let tenant:string;
  export let csrf:string;
  export let channel:'web'|'whatsapp';
  export let canEdit=false;
  export let apiPrefix='';
  type Settings={limits:Record<'web'|'whatsapp',number|null>;default:number;minimum:number;maximum:number};
  const where={web:'website chat',whatsapp:'WhatsApp'}[channel];
  let settings:Settings|undefined, value=40, unlimited=false, saved:number|null=40;
  let loading=true, busy=false, message='', error=false, disposed=false;
  const controllers=new Set<AbortController>();

  async function call(method='GET', body?:unknown) {
    const controller=new AbortController();controllers.add(controller);
    const timer=setTimeout(()=>controller.abort(),20000);
    try {
      const response=await fetch(`${apiPrefix}/admin/api/message-limits?tenant=${encodeURIComponent(tenant)}`,{method,credentials:'same-origin',
        signal:controller.signal,headers:{'X-CSRF-Token':csrf,...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{})});
      const data=await response.json().catch(()=>({}));
      if(!response.ok){
        if(data.error==='message_limits_unavailable')throw new Error('Message limits are not available yet. The database update for them has not been applied.');
        if(response.status===403)throw new Error('You do not have permission to change this.');
        throw new Error('The limit could not be saved. Refresh and try again.');
      }
      return data as Settings;
    } catch(err) {
      if(controller.signal.aborted)throw new Error('The request timed out. Refresh to check whether it saved.');
      throw err;
    } finally {clearTimeout(timer);controllers.delete(controller);}
  }
  function show(data:Settings) {
    settings=data;saved=data.limits[channel];
    unlimited=saved===null;value=saved??data.default;
  }
  async function load() {
    loading=true;message='';error=false;
    try {const data=await call();if(!disposed)show(data);}
    catch(err){if(!disposed){error=true;message=err instanceof Error?err.message:'Message limits are unavailable.';}}
    finally{if(!disposed)loading=false;}
  }
  async function save() {
    if(busy||!canEdit)return;busy=true;message='';error=false;
    try {
      show(await call('PUT',{channel,limit:unlimited?null:value}));
      message=unlimited?`Customers can send unlimited ${where} messages.`:`Saved. Each customer can send up to ${value} ${where} messages a day.`;
    } catch(err){error=true;message=err instanceof Error?err.message:'Could not save.';}
    finally{busy=false;}
  }
  $: changed=settings!==undefined&&(unlimited?null:value)!==saved;
  onMount(load);
  onDestroy(()=>{disposed=true;for(const controller of controllers)controller.abort();});
</script>

<section class="limit" aria-labelledby={`message-limit-${channel}`}>
  <h3 id={`message-limit-${channel}`}>Customer message limit</h3>
  <p class="hint">How many {where} messages one customer can send each day. It resets at midnight UTC. When a customer reaches it, they are told to try again tomorrow and given your contact email, and no AI is used.</p>
  {#if loading}<p role="status">Loading…</p>{:else if settings}
    <form on:submit|preventDefault={save}>
      <label class="toggle"><input type="checkbox" bind:checked={unlimited} disabled={!canEdit||busy}/> Unlimited</label>
      <label class="slider" class:off={unlimited}>
        <span><strong>{unlimited?'Unlimited':value}</strong>{unlimited?'':' messages per customer per day'}</span>
        <input type="range" min={settings.minimum} max={settings.maximum} step="5" bind:value
          disabled={!canEdit||busy||unlimited} aria-valuetext={`${value} messages per customer per day`}/>
        <span class="scale"><span>{settings.minimum}</span><span>{settings.maximum}</span></span>
      </label>
      {#if channel==='web'}<p class="hint">A visitor who restarts the chat keeps the same count. One internet connection, such as an office, can send up to five customers’ worth.</p>{/if}
      {#if canEdit}<button type="submit" disabled={busy||!changed}>{busy?'Saving…':'Save limit'}</button>
      {:else}<p class="hint">Ask your business owner for permission to change business settings.</p>{/if}
    </form>
  {/if}
  {#if message}<p role="status" class:error>{message}</p>{/if}
</section>

<style>
  .limit{padding:1.25rem;border:1px solid var(--v7-line);border-radius:var(--v7-radius-panel);background:var(--v7-surface);margin:1rem 0}
  h3{margin:.2rem 0 .4rem}p{line-height:1.5;max-width:70ch}.hint{font-size:.85rem;color:var(--v7-muted);margin:.2rem 0}
  form{display:grid;gap:.75rem;max-width:520px;margin-top:.6rem}
  .toggle{display:flex;align-items:center;gap:.5rem;font-weight:600;min-height:44px}
  .toggle input{width:1.2rem;height:1.2rem}
  .slider{display:grid;gap:.35rem}.slider.off{opacity:.55}
  .slider input{width:100%;min-height:44px;accent-color:var(--v7-accent)}
  .scale{display:flex;justify-content:space-between;font-size:.8rem;color:var(--v7-muted)}
  button{justify-self:start;font:inherit;padding:.6rem .9rem;min-height:44px;border:1px solid var(--v7-control-line);border-radius:var(--v7-radius-control);color:var(--v7-accent-hover);background:var(--v7-canvas);cursor:pointer}
  button:disabled{opacity:.55;cursor:not-allowed}.error{color:var(--v7-danger)}
</style>
