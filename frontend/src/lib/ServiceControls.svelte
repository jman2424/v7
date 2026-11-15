<script lang="ts">
  import {onMount,onDestroy} from 'svelte';
  import { businessLabel } from './businessLabel';
  export let tenant:string;
  export let csrf:string;
  export let apiPrefix='';
  export let platform=false;
  type Channel='web'|'whatsapp'|'email'|'phone';
  type State={all_paused:boolean;suspended_by_platform:boolean;can_pause:boolean;channels:Record<Channel,{paused:boolean;suspended_by_platform:boolean}>};
  type Control={scope:string;reason:string;actor:string;updated:number};
  const names:Record<Channel,string>={web:'Website chat',whatsapp:'WhatsApp',email:'Email',phone:'Phone calls'};
  const channels:Channel[]=['web','whatsapp','email','phone'];
  let state:State|undefined, controls:Control[]=[], loading=true, busy=false, disposed=false, message='', error=false;
  let target:'all'|'channel'|'business'|'business_channel'='business', targetChannel:Channel='web', reason='';
  const controllers=new Set<AbortController>();

  async function call(path:string, method='GET', body?:unknown) {
    const controller=new AbortController();controllers.add(controller);
    const timer=setTimeout(()=>controller.abort(),20000);
    try {
      const response=await fetch(`${apiPrefix}/admin/api/${path}`,{method,credentials:'same-origin',signal:controller.signal,
        headers:{'X-CSRF-Token':csrf,...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{})});
      const data=await response.json().catch(()=>({}));
      if(!response.ok){
        if(data.error==='service_control_reason_required')throw new Error('Write a short reason (at least 5 characters). It is kept with the suspension.');
        if(data.error==='service_controls_unavailable')throw new Error('Service controls are not available yet. The database update for them has not been applied.');
        if(response.status===403)throw new Error('You do not have permission to change this.');
        throw new Error('The change could not be saved. Refresh and try again.');
      }
      return data;
    } catch(err) {
      if(controller.signal.aborted)throw new Error('The request timed out. Refresh to check whether it saved.');
      throw err;
    } finally {clearTimeout(timer);controllers.delete(controller);}
  }
  const ownPath=()=>`service-controls?tenant=${encodeURIComponent(tenant)}`;
  async function load() {
    loading=true;message='';error=false;
    try {
      const own=await call(ownPath());
      const all=platform?await call('platform/service-controls'):undefined;
      if(!disposed){state=own;if(all)controls=all.controls;}
    } catch(err){if(!disposed){error=true;message=err instanceof Error?err.message:'Service controls are unavailable.';}}
    finally{if(!disposed)loading=false;}
  }
  async function pause(scope:'all'|Channel, paused:boolean) {
    if(busy)return;
    if(paused&&scope==='all'&&!window.confirm('Pause all AI for this business? Customers who message or call will be told to contact you by email. Nothing is deleted, and you can resume at any time.'))return;
    busy=true;message='';error=false;
    try {
      state=await call(ownPath(),'PUT',{scope,paused});
      message=paused?(scope==='all'?'All AI is paused. Customers are told how to contact you.':`${names[scope as Channel]} is paused.`):(scope==='all'?'AI is running again.':`${names[scope as Channel]} is running again.`);
    } catch(err){error=true;message=err instanceof Error?err.message:'Could not save.';}
    finally{busy=false;}
  }
  function describe(scope:string) {
    const parts=scope.split(':');const who=parts.includes('tenant')?parts[parts.indexOf('tenant')+1]:'';
    const channel=parts.includes('channel')?names[parts[parts.indexOf('channel')+1] as Channel]:'';
    if(who&&channel)return `${channel} for ${who}`;
    if(who)return `All AI for ${who}`;
    if(channel)return `${channel} for every business`;
    return 'The whole platform';
  }
  async function platformChange(tenantKey:string|null, channel:Channel|null, paused:boolean, why='') {
    if(busy)return;busy=true;message='';error=false;
    try {
      const data=await call('platform/service-controls','PUT',{tenant:tenantKey,channel,paused,reason:why});
      controls=data.controls;state=await call(ownPath());reason='';
      message=paused?'Suspended. It takes effect within a few seconds on every server.':'Restored.';
    } catch(err){error=true;message=err instanceof Error?err.message:'Could not save.';}
    finally{busy=false;}
  }
  function suspend() {
    const tenantKey=target==='business'||target==='business_channel'?tenant:null;
    const channel=target==='channel'||target==='business_channel'?targetChannel:null;
    const label=describe(['platform',...(tenantKey?['tenant',tenantKey]:[]),...(channel?['channel',channel]:[])].join(':'));
    if(!window.confirm(`Suspend ${label.charAt(0).toLowerCase()+label.slice(1)}? Customers get no AI replies until you restore it.`))return;
    void platformChange(tenantKey,channel,true,reason);
  }
  function restore(control:Control) {
    const parts=control.scope.split(':');
    const tenantKey=parts.includes('tenant')?parts[parts.indexOf('tenant')+1]:null;
    const channel=parts.includes('channel')?parts[parts.indexOf('channel')+1] as Channel:null;
    void platformChange(tenantKey,channel,false);
  }
  onMount(load);
  onDestroy(()=>{disposed=true;for(const controller of controllers)controller.abort();});
</script>

<section class="controls" aria-labelledby="service-controls-title">
  <h3 id="service-controls-title">Service controls for {$businessLabel || tenant}</h3>
  <p>Pause the AI assistant without changing any settings. While it is paused, customers who message or call are told how to contact you by email. Nothing is deleted.</p>
  {#if loading}<p role="status">Loading service controls…</p>{:else if state}
    {#if state.suspended_by_platform}<p class="notice error" role="status"><strong>Suspended by the platform.</strong> The platform operator has stopped this business’s AI. Contact them to restore it.</p>{/if}
    <div class="all">
      <div><strong>{state.all_paused?'All AI is paused':'AI is running'}</strong><p class="hint">{state.all_paused?'Every channel is paused until you resume.':'Pausing stops every channel at once.'}</p></div>
      {#if state.can_pause}<button class:danger={!state.all_paused} disabled={busy} on:click={()=>state&&pause('all',!state.all_paused)}>{state.all_paused?'Resume all AI':'Pause all AI'}</button>{/if}
    </div>
    <ul>
      {#each channels as channel}{@const row=state.channels[channel]}
        <li><span>{names[channel]}</span>
          <span class="status">{row.suspended_by_platform?'Suspended by the platform':row.paused?'Paused':state.all_paused?'Paused (all AI)':'Running'}</span>
          {#if state.can_pause}<button disabled={busy} on:click={()=>pause(channel,!row.paused)}>{row.paused?'Resume':'Pause'}</button>{/if}
        </li>
      {/each}
    </ul>
    {#if !state.can_pause}<p class="hint">Ask your business owner for the “pause and resume AI” permission to change these.</p>{/if}
  {/if}

  {#if platform && !loading}
    <h3>Platform kill switch</h3>
    <p class="hint">For incidents and abuse. A suspension here cannot be lifted by the business. It takes effect within a few seconds on every server, and every change is audited.</p>
    {#if controls.length}<ul>{#each controls as control}
      <li><span>{describe(control.scope)}</span><span class="status">{control.reason} · {new Date(control.updated*1000).toLocaleString()}</span><button disabled={busy} on:click={()=>restore(control)}>Restore</button></li>
    {/each}</ul>{:else}<p class="hint">Nothing is suspended.</p>{/if}
    <form on:submit|preventDefault={suspend}>
      <label>What to suspend<select bind:value={target} disabled={busy}>
        <option value="business">All AI for this business</option><option value="business_channel">One channel for this business</option>
        <option value="channel">One channel for every business</option><option value="all">The whole platform</option></select></label>
      {#if target==='channel'||target==='business_channel'}<label>Channel<select bind:value={targetChannel} disabled={busy}>{#each channels as channel}<option value={channel}>{names[channel]}</option>{/each}</select></label>{/if}
      <label>Reason (kept with the suspension)<input bind:value={reason} maxlength="500" required minlength="5" disabled={busy}/></label>
      <button class="danger" type="submit" disabled={busy||reason.trim().length<5}>Suspend</button>
    </form>
  {/if}
  {#if message}<p role="status" class:error>{message}</p>{/if}
</section>

<style>
  .controls{padding:1.25rem;border:1px solid var(--v7-line);border-radius:var(--v7-radius-panel);background:var(--v7-surface);margin-bottom:1rem}h3{margin:.2rem 0 .6rem}p{line-height:1.5;max-width:70ch}.hint{font-size:.85rem;color:var(--v7-muted);margin:.2rem 0}.all{display:flex;justify-content:space-between;align-items:center;gap:1rem;flex-wrap:wrap;padding:.8rem 0;border-bottom:1px solid var(--v7-line)}ul{list-style:none;padding:0;margin:.5rem 0}li{display:flex;align-items:center;gap:.75rem;flex-wrap:wrap;padding:.55rem 0;border-bottom:1px solid var(--v7-line)}li span:first-child{flex:1 1 10rem;font-weight:600}.status{color:var(--v7-muted);overflow-wrap:anywhere}form{display:grid;gap:.6rem;max-width:520px;margin-top:.8rem}label{display:grid;gap:.35rem;font-weight:600}select,input{font:inherit;padding:.6rem;border:1px solid var(--v7-control-line);border-radius:var(--v7-radius-control);background:var(--v7-surface)}button{font:inherit;padding:.6rem .9rem;min-height:44px;border:1px solid var(--v7-control-line);border-radius:var(--v7-radius-control);color:var(--v7-accent-hover);background:var(--v7-canvas);cursor:pointer}button.danger{color:var(--v7-danger)}button:disabled{opacity:.55;cursor:not-allowed}.error{color:var(--v7-danger)}.notice{padding:.7rem;border:1px solid var(--v7-line);border-radius:var(--v7-radius-control)}
</style>
