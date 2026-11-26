<script lang="ts">
  import {recordAnchor} from './workspaceSearch';
  import {onMount,onDestroy} from 'svelte';
  export let tenant:string;
  export let csrf:string;
  export let apiPrefix='';
  export let isPlatform=false;
  export let canManageBilling=false;
  export let setupChannel:''|'phone'|'whatsapp'='';
  let useExisting=true, businessNumber='', region='';
  $: channelName=setupChannel==='phone'?'Phone':'WhatsApp';
  $: requestPrefix=channelName+' connection request';
  $: visibleRequests=setupChannel?requests.filter(row=>row.kind==='setup'&&row.message.startsWith(requestPrefix+'\n')):requests;
  $: pending=Boolean(setupChannel&&visibleRequests.some(row=>row.state==='needs_review'));
  type Request={id:string;kind:string;message:string;contact:string;state:string;reply:string;version:number};
  let requests:Request[]=[],message='',kind='setup',error='',notice='',busy=false,alive=true;
  let requestId=crypto.randomUUID().replaceAll('-','');
  const controllers=new Set<AbortController>();
  async function api(path='',body?:unknown){
    const controller=new AbortController();controllers.add(controller);
    const timeout=setTimeout(()=>controller.abort(),20000);
    try{
      const response=await fetch(apiPrefix+'/billing/support'+path+'?tenant='+encodeURIComponent(tenant),{credentials:'same-origin',signal:controller.signal,...(body?{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(body)}:{})});
      const data=await response.json();
      if(!response.ok)throw new Error(response.status===401?'Your session expired. Sign in again.':data.error==='support_daily_limit'?'You have reached the daily request limit. Email support@vertex-seven.com for help.':'Could not save or load support. Check request status before trying again.');
      return data;
    }finally{clearTimeout(timeout);controllers.delete(controller);}
  }
  async function load(){const data=await api();if(alive)requests=data.requests;}
  async function send(){
    if(busy)return;busy=true;error='';notice='';
    const details=setupChannel?[requestPrefix,useExisting?'Keep existing number: '+businessNumber.trim():'Request a new number', 'Country or region: '+region.trim()].join('\n'):message;
    try{const result=await api('',{kind,message:details,request_id:requestId});if(!alive)return;requestId=crypto.randomUUID().replaceAll('-','');message='';notice='Request saved. Reference '+result.reference+'. You can track updates below.';await load();}
    catch(failure){if(alive)error=failure instanceof Error?failure.message:'Could not send request.';}
    finally{if(alive)busy=false;}
  }
  async function complete(row:Request){if(busy)return;busy=true;error='';try{await api('/'+row.id,{decision:'complete',version:row.version,reply:row.reply});await load();}catch(failure){if(alive)error=failure instanceof Error?failure.message:'Could not update request.';}finally{if(alive)busy=false;}}
  onMount(()=>{load().catch(()=>{if(alive)error='Support requests could not be loaded. Email support@vertex-seven.com for help.';});});
  onDestroy(()=>{alive=false;for(const controller of controllers)controller.abort();});
</script>

<section id={setupChannel?setupChannel+"-managed-setup":"billing-support"} class="support" aria-label={setupChannel?channelName+" setup":"Setup and billing support"}>
  <h2>{setupChannel?'Ask Vertex Seven to connect '+channelName:'Setup and billing support'}</h2>
  {#if setupChannel}
    <p>{setupChannel==='phone'?'Keep your published number and forward calls to your V7 line, or request a new line for customers to call directly.':'Request a WhatsApp sender for this business. You may need to confirm ownership of the number with Meta.'} Your request goes to the V7 team. Any number rental or usage charges are confirmed separately.</p>
  {:else}
  <p>Ask for setup assistance, help with a payment or account access. Never include passwords, card details or customer records.</p>
  <p>For an urgent access problem, email <a href="mailto:support@vertex-seven.com">support@vertex-seven.com</a> with your business name and request reference.</p>{/if}
  {#if error}<p role="alert">{error}</p>{/if}{#if notice}<p role="status">{notice}</p>{/if}
  {#if canManageBilling&&!pending}<form on:submit|preventDefault={send}>
    {#if setupChannel}
      <label>Which number would you like to use?<select bind:value={useExisting} disabled={busy}><option value={true}>Keep my existing business number</option><option value={false}>Request a new number</option></select></label>
      {#if useExisting}<label>Existing business number<input type="tel" bind:value={businessNumber} autocomplete="tel" placeholder="+44 7700 900123" pattern={'[+][1-9]( *[0-9]){6,14}'} maxlength="31" required disabled={busy}/></label>{/if}
      <label>Country or region<input bind:value={region} autocomplete="country-name" maxlength="80" required disabled={busy}/></label>
    {:else}<label>What do you need?<select bind:value={kind} disabled={busy}><option value="setup">Setup assistance</option><option value="billing">Billing question</option><option value="access">Account access</option></select></label>
    <label>Tell us what you need help with<textarea bind:value={message} minlength="10" maxlength="2000" rows="3" required disabled={busy}></textarea></label>{/if}
    <button disabled={busy}>{busy?'Saving…':setupChannel?'Request '+channelName+' setup':'Send support request'}</button>
  </form>{/if}
  <div class="requests">{#each visibleRequests as row}<article id={recordAnchor('support',row.id)}><h3>{row.kind==='demo'?'Demo enquiry':row.kind==='setup'?'Setup assistance':row.kind==='billing'?'Billing question':'Account access'}</h3><p>Reference {row.id} · {row.state==='needs_review'?'Waiting for support':row.state==='completed'?'Completed':'Closed'}</p><p class="message">{row.message}</p>{#if isPlatform}<p>Contact: {row.contact}</p>{/if}{#if row.reply}<p class="message">{row.reply}</p>{/if}
    {#if isPlatform&&row.state==='needs_review'}<label>Update for the customer<textarea bind:value={row.reply} maxlength="6000" rows="2"></textarea></label><button disabled={busy} on:click={()=>complete(row)}>Save update and complete</button>{/if}
  </article>{:else}{#if !setupChannel}<p>No support requests recorded for this business.</p>{/if}{/each}</div>
</section>

<style>
  .support{padding:24px;background:var(--v7-surface);border:1px solid var(--v7-line);border-radius:var(--v7-radius-panel);scroll-margin-top:24px}h2{margin:0 0 12px}p{line-height:1.6;color:var(--v7-muted)}form,label{display:grid;gap:10px}form{gap:16px}input,textarea,select,button{font:inherit;box-sizing:border-box;max-width:100%;padding:12px;border:1px solid var(--v7-control-line);border-radius:var(--v7-radius-control);background:var(--v7-surface);color:var(--v7-ink);min-height:44px}button{cursor:pointer;justify-self:start}button:disabled{opacity:.5}article{border-top:1px solid var(--v7-line);padding:16px 0}.message{white-space:pre-wrap;overflow-wrap:anywhere}a{color:var(--v7-accent)}
</style>
