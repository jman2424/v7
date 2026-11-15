<script lang="ts">
  import {onMount,onDestroy} from 'svelte';
  import DraftGuard from './DraftGuard.svelte';
  import { businessLabel } from './businessLabel';
  export let tenant:string;
  export let csrf:string;
  export let apiPrefix='';
  type Routes={version:number;phone:string[];email:{address:string;sender:string}[];whatsapp_twilio:string[];whatsapp_meta:string[]};
  let revision='',loading=true,busy=false,disposed=false,message='',error=false,saved='';
  let phone='',email='',whatsapp='',meta='';
  const controllers=new Set<AbortController>();
  $: draft=JSON.stringify([phone,email,whatsapp,meta]);
  $: dirty=Boolean(saved&&saved!==draft);
  const lines=(value:string)=>value.split('\n').map(line=>line.trim()).filter(Boolean);
  function emailRows(value:string) {
    // "support@shop.example" or "support@shop.example > help@shop.example" (inbound > reply-from).
    return lines(value).map(line=>{const [address,sender]=line.split('>').map(part=>part.trim());return {address,sender:sender||address};});
  }
  function apply(routes:Routes) {
    phone=routes.phone.join('\n');whatsapp=routes.whatsapp_twilio.join('\n');meta=routes.whatsapp_meta.join('\n');
    email=routes.email.map(row=>row.sender&&row.sender!==row.address?`${row.address} > ${row.sender}`:row.address).join('\n');
    saved=JSON.stringify([phone,email,whatsapp,meta]);
  }
  async function request(method='GET') {
    const controller=new AbortController();controllers.add(controller);
    const timer=setTimeout(()=>controller.abort(),20000);
    try {
      const response=await fetch(`${apiPrefix}/admin/api/channel-routes?tenant=${encodeURIComponent(tenant)}`,{
        method,credentials:'same-origin',signal:controller.signal,
        headers:{'X-CSRF-Token':csrf,...(method==='PUT'?{'Content-Type':'application/json'}:{})},
        ...(method==='PUT'?{body:JSON.stringify({revision,routes:{version:1,phone:lines(phone),email:emailRows(email),whatsapp_twilio:lines(whatsapp),whatsapp_meta:lines(meta)}})}:{})});
      const data=await response.json().catch(()=>({}));
      if(!response.ok){
        if(data.error==='route_assigned_elsewhere')throw new Error(`Already assigned to another business: ${(data.recipients||[]).join(', ')}. Remove it there first.`);
        if(data.error==='invalid_channel_routes')throw new Error('Check the entries. Phone and WhatsApp numbers need the country code (for example +447700900123), email addresses must be complete, and each list holds up to 10 entries.');
        if(response.status===409)throw new Error('Someone else changed these assignments. Refresh, then try again.');
        throw new Error('The assignments could not be loaded or saved. Refresh and check your permissions.');
      }
      return data;
    } catch(err) {
      if(controller.signal.aborted)throw new Error('The request timed out. Refresh to check whether it saved before trying again.');
      throw err;
    } finally {clearTimeout(timer);controllers.delete(controller);}
  }
  async function load() {
    loading=true;message='';error=false;
    try {const data=await request();if(!disposed){revision=data.revision;apply(data.routes);}}
    catch(err){if(!disposed){error=true;message=err instanceof Error?err.message:'Assignments are unavailable.';}}
    finally{if(!disposed)loading=false;}
  }
  async function save() {
    if(busy)return;busy=true;message='';error=false;
    try {const data=await request('PUT');if(!disposed){revision=data.revision;apply(data.routes);message='Saved. New messages and calls to these numbers and addresses now reach this business.';}}
    catch(err){if(!disposed){error=true;message=err instanceof Error?err.message:'Could not save.';}}
    finally{if(!disposed)busy=false;}
  }
  onMount(load);
  onDestroy(()=>{disposed=true;for(const controller of controllers)controller.abort();});
</script>
<DraftGuard {dirty}/>

<section class="routes" aria-labelledby="channel-routes-title">
  <h3 id="channel-routes-title">Numbers and addresses for {$businessLabel || tenant}</h3>
  <p>Link the phone numbers, email addresses and WhatsApp senders that belong to this business. Messages and calls to them are then answered by this business’s assistant. One number or address can belong to only one business.</p>
  <p class="hint">This only links them. The number or address must already exist with the provider: a voice number in the platform Twilio account, a sender verified in Resend, or a WhatsApp sender approved by Meta or Twilio. Assignments made in server settings still apply and are not shown here.</p>
  {#if loading}<p role="status">Loading assignments…</p>{:else}
    <form on:submit|preventDefault={save}>
      <label>Phone numbers for calls<textarea bind:value={phone} rows="2" placeholder="+447700900123" disabled={busy}></textarea></label>
      <p class="hint">One per line, with the country code.</p>
      <label>Support email addresses<textarea bind:value={email} rows="2" placeholder="support@shop.example" disabled={busy}></textarea></label>
      <p class="hint">One per line. Replies come from the same address. To reply from a different verified address, write it after a “&gt;”, for example <code>inbound@yourdomain.example &gt; support@shop.example</code>.</p>
      <label>WhatsApp numbers (Twilio)<textarea bind:value={whatsapp} rows="2" placeholder="+447700900123" disabled={busy}></textarea></label>
      <label>WhatsApp phone number IDs (Meta)<textarea bind:value={meta} rows="2" placeholder="123456789012345" disabled={busy}></textarea></label>
      <p class="hint">Meta shows the phone number ID in WhatsApp API setup. It is not the phone number itself.</p>
      <div class="buttons"><button type="submit" disabled={busy||!dirty}>{busy?'Saving…':'Save assignments'}</button><button type="button" on:click={load} disabled={busy}>Refresh</button></div>
    </form>
  {/if}
  {#if message}<p role="status" class:error>{message}</p>{/if}
</section>

<style>
  .routes{padding:1.25rem;border:1px solid var(--v7-line);border-radius:var(--v7-radius-panel);background:var(--v7-surface)}h3{margin:.2rem 0 .6rem}p{line-height:1.5;max-width:70ch}form{max-width:620px}label{display:grid;gap:.4rem;margin:1rem 0 .3rem;font-weight:600}textarea{font:inherit;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;padding:.65rem;border:1px solid var(--v7-control-line);border-radius:var(--v7-radius-control);background:var(--v7-surface);box-sizing:border-box;width:100%;resize:vertical}.hint{font-size:.85rem;color:var(--v7-muted);margin:.2rem 0}.buttons{display:flex;gap:.5rem;flex-wrap:wrap;margin-top:1rem}button{font:inherit;padding:.65rem .9rem;min-height:44px;border:1px solid var(--v7-control-line);border-radius:var(--v7-radius-control);color:var(--v7-accent-hover);background:var(--v7-canvas);cursor:pointer}button:disabled{opacity:.55;cursor:not-allowed}.error{color:var(--v7-danger)}code{overflow-wrap:anywhere}
</style>
