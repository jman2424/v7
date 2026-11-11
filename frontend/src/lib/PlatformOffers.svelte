<script lang="ts">
  import {onMount,onDestroy} from 'svelte';
  export let tenant:string;
  export let csrf:string;
  export let canManage=false;
  export let apiPrefix='';
  let available:boolean|null=null,loading=true,busy='',status='',error=false,disposed=false;
  let settings={setup_enabled:true,highstreet_enabled:true},revision='';
  let referral={enabled:false,percent:0,joining_setup_percent:0};
  const controllers=new Set<AbortController>();
  const offers=[{key:'setup_enabled' as const,code:'SETUP',title:'Free one-time setup',details:'Waives unpaid business and agent setup. Monthly subscriptions keep their normal price.'},
    {key:'highstreet_enabled' as const,code:'MHIGHSTREET',title:'Free setup + 50% off the first month',details:'Waives unpaid setup and discounts the first subscription month only. Later months keep their normal price.'}];
  async function request(path:string,method='GET',body?:unknown) {
    const controller=new AbortController();controllers.add(controller);
    const timeout=setTimeout(()=>controller.abort(),20000);
    try {
      const response=await fetch(`${apiPrefix}${path}?tenant=${encodeURIComponent(tenant)}`,{
        method,credentials:'same-origin',signal:controller.signal,
        headers:{'X-CSRF-Token':csrf,...(body?{'Content-Type':'application/json'}:{})},
        ...(body?{body:JSON.stringify(body)}:{})});
      const data=await response.json();
      if(!response.ok)throw new Error(response.status===409?'Offer settings changed. Refresh their status before trying again.':
        'Could not update platform offers. Check your platform permissions and refresh their status.');
      return data;
    } catch(err) {
      if(controller.signal.aborted)throw new Error('The update could not be confirmed. Refresh offer status before retrying.');
      throw err;
    } finally {clearTimeout(timeout);controllers.delete(controller);}
  }
  function apply(data:any) {
    available=data.available;
    if(available){settings=data.settings;revision=data.revision;referral=data.referral;}
  }
  async function load() {
    if(busy)return;
    loading=true;status='';error=false;
    try {const data=await request('/admin/api/platform-promotions');if(!disposed)apply(data);}
    catch {if(!disposed){error=true;status='Could not load platform offer status. Refresh to try again.';}}
    finally {if(!disposed)loading=false;}
  }
  async function toggle(key:'setup_enabled'|'highstreet_enabled') {
    if(!canManage||busy||loading||available!==true)return;
    const enabled=!settings[key];busy=key;status='';error=false;
    try {
      const data=await request('/admin/api/platform-promotions','PUT',{settings:{...settings,[key]:enabled},revision});
      if(!disposed){apply(data);status=`${key==='setup_enabled'?'SETUP':'MHIGHSTREET'} ${enabled?'enabled':'paused'} for new claims.`;}
    } catch(err) {if(!disposed){error=true;status=err instanceof Error?err.message:'Could not update the offer.';}}
    finally {if(!disposed)busy='';}
  }
  async function toggleReferral() {
    if(!canManage||busy||loading||available!==true)return;
    const enabled=!referral.enabled;busy='referral';status='';error=false;
    try {
      const data=await request('/billing/referrals/program','POST',{enabled});
      if(!disposed){referral=data;status=`Referrals ${enabled?'enabled':'paused'} for new claims.`;}
    } catch(err) {if(!disposed){error=true;status=err instanceof Error?err.message:'Could not update referrals.';}}
    finally {if(!disposed)busy='';}
  }
  onMount(load);
  onDestroy(()=>{disposed=true;for(const controller of controllers)controller.abort();});
</script>

{#if available!==false}
<section class="platform-offers" aria-labelledby="platform-offers-heading">
  <div class="heading"><div><p class="eyebrow">Platform promotions</p><h2 id="platform-offers-heading">Vertex Seven subscription offers</h2></div><button type="button" disabled={loading||Boolean(busy)} on:click={load}>Refresh offer status</button></div>
  <p>Control which offers new businesses can claim. Pausing updates code acceptance, website promotion and the assistant’s current offer information. Already accepted discounts and earned referral rewards keep their agreed terms.</p>
  {#if loading}<p role="status">Loading platform offers…</p>{/if}
  {#if status}<p class:error role={error?'alert':'status'}>{status}</p>{/if}
  {#if available}
    <div class="offer-grid">{#each offers as offer}<article>
      <div class="row"><code>{offer.code}</code><span class:active={settings[offer.key]}>{settings[offer.key]?'Active':'Paused'}</span></div>
      <h3>{offer.title}</h3><p>{offer.details}</p>
      <button type="button" disabled={!canManage||Boolean(busy)} on:click={()=>toggle(offer.key)}>{busy===offer.key?'Updating…':`${settings[offer.key]?'Disable':'Enable'} ${offer.code}`}</button>
    </article>{/each}
    <article><div class="row"><strong>Referrals</strong><span class:active={referral.enabled}>{referral.enabled?'Active':'Paused'}</span></div>
      <h3>Refer a business</h3><p>{referral.percent}% off the joining business’s first subscription month, with {referral.joining_setup_percent}% off its unpaid setup. The referrer earns its reward after verified payment.</p>
      <button type="button" disabled={!canManage||Boolean(busy)} on:click={toggleReferral}>{busy==='referral'?'Updating…':`${referral.enabled?'Disable':'Enable'} referrals`}</button>
    </article></div>
    <p class="hint">Switches save immediately. These billing offers exclude AI credit and provider charges. Catalogue promotions below are managed separately.</p>
  {/if}
</section>
{/if}

<style>
  .platform-offers{padding:24px;background:var(--v7-surface,#fff);border:1px solid var(--v7-line,var(--v7-line));border-radius:var(--v7-radius-panel);margin-bottom:24px}.heading,.row{display:flex;justify-content:space-between;align-items:center;gap:16px}.eyebrow{font-size:var(--v7-text-xs);font-weight:700;text-transform:uppercase;color:var(--v7-muted,var(--v7-muted))}h2{margin:0;font-size:var(--v7-text-xl)}h3{font-size:var(--v7-text-lg);margin:16px 0 10px}p{line-height:1.6}.offer-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,240px),1fr));gap:16px;margin:20px 0}article{border:1px solid var(--v7-line,var(--v7-line));border-radius:var(--v7-radius-panel);padding:20px;display:flex;flex-direction:column}article p{flex:1}.row span{padding:5px 9px;border-radius:var(--v7-radius-panel);background:#f2f2ec;font-size:var(--v7-text-xs)}.row span.active{background:#e5f3e9;color:var(--v7-accent-hover)}code{font-weight:700;overflow-wrap:anywhere}button{font:inherit;min-height:44px;padding:10px 14px;border:1px solid var(--v7-control-line);border-radius:var(--v7-radius-control);background:var(--v7-canvas);color:var(--v7-accent-hover);cursor:pointer}button:disabled{opacity:.55;cursor:not-allowed}.hint{font-size:var(--v7-text-xs);color:var(--v7-muted,var(--v7-muted))}.error{color:var(--v7-danger)}@media(max-width:600px){.heading{align-items:start;flex-direction:column}}
</style>
