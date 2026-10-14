<script lang="ts">
  import {onMount,createEventDispatcher} from 'svelte';
  import {t} from './i18n';
  export let tenant:string;
  export let csrf:string;
  export let apiPrefix='';
  export let isPlatform=false;
  export let configured=false;
  type Reward={id:string;kind:string;percent:number;status:string};
  type Report={program:{enabled:number;percent:number;joining_setup_percent:number;sponsor_setup_percent:number};payments_configured:boolean;code:string;link:string;claim:{percent:number;joining_setup_percent:number;status:string}|null;rewards:Reward[]};
  let data:Report|null=null;
  let code='';
  let busy=false;
  let error='';
  let message='';
  const dispatch=createEventDispatcher<{changed:void}>();
  const errors:Record<string,string>={invalid_referral_code:'Enter a valid referral code.',invalid_or_self_referral:'This code is invalid or belongs to your own business.',referral_already_accepted:'This business or owner has already accepted a referral.',referral_program_disabled:'New referrals are currently disabled.',referral_requires_new_business_before_checkout:'Accept a referral before your first checkout. Existing or complimentary businesses cannot claim a welcome discount.',referral_does_not_stack_with_existing_discount:'Your existing discount stays in place. This reward remains available.',active_paid_subscription_required:'An active paid subscription is needed to apply a renewal reward.',no_available_referral_reward:'No subscription reward is available.'};
  async function read(action='',body?:Record<string,unknown>){
    const response=await fetch(apiPrefix+'/billing/referrals'+(action?'/'+action:'')+'?tenant='+encodeURIComponent(tenant),{credentials:'same-origin',...(body?{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(body)}:{})});
    const result=await response.json();
    if(!response.ok)throw new Error(errors[result.error]||'Could not update referrals. Please refresh and try again.');
    return result;
  }
  async function action(name:string,body:Record<string,unknown>){
    busy=true;error='';message='';
    try{await read(name,body);data=await read();message=name==='claim'?'Referral accepted. Your discounts are saved.':name==='apply'?'Your discount is applied to the next subscription invoice.':'Referral settings saved.';dispatch('changed');}
    catch(err){error=err instanceof Error?err.message:'Could not update referrals. Please refresh and try again.';}
    finally{busy=false;}
  }
  onMount(async()=>{
    try{code=sessionStorage.getItem('v7-referral')||'';}catch{/* Optional convenience only. */}
    try{data=await read();}catch(err){error=err instanceof Error?err.message:'Could not update referrals. Please refresh and try again.';}
  });
</script>
<section id="business-referrals" class="referrals" aria-labelledby="referral-heading">
  <header><h3 id="referral-heading">{$t('Refer a business')}</h3>{#if data}<span>{$t(data.program.enabled?'Open to new referrals':'New referrals paused')}</span>{/if}</header>
  {#if error}<p role="alert">{$t(error)}</p>{/if}{#if message}<p role="status">{$t(message)}</p>{/if}
  {#if data}
    <p>{$t('Both businesses receive {percent}% off one subscription month.',{percent:data.program.percent})}</p>
    {#if data.program.joining_setup_percent===100}<p>{$t('The new business gets its first subscription month discounted and pays no setup fee.')}</p>
    {:else}<p>{$t('The new business gets {percent}% off its unpaid setup fee.',{percent:data.program.joining_setup_percent})}</p>{/if}
    <p class="hint">{$t('You earn your subscription reward and {percent}% off unpaid setup only after the new business makes its first successful subscription payment.',{percent:data.program.sponsor_setup_percent})}</p>
    <p class="hint">{$t('Already-paid setup fees are not refunded. Discounts do not stack or apply to AI credit.')}</p>
    <label for="referral-link">{$t('Your referral link')}</label><input id="referral-link" readonly value={data.link} dir="ltr" on:focus={(event)=>event.currentTarget.select()}/>
    {#if data.claim}<p>{$t('Your accepted offer is saved: {percent}% off your first subscription month and {setup_percent}% off unpaid setup.',{percent:data.claim.percent,setup_percent:data.claim.joining_setup_percent})}</p>
    {:else if data.program.enabled}<form on:submit|preventDefault={()=>action('claim',{code})}><label for="referral-code">{$t('Have a referral code?')}</label><div><input id="referral-code" bind:value={code} maxlength="35" dir="ltr" required/><button disabled={busy}>{$t('Accept referral')}</button></div></form>{/if}
    {#if data.rewards.length}<ul>{#each data.rewards as reward}<li>{$t(reward.kind==='platform'?'Subscription month':'Unpaid setup fee')} · {reward.percent}% · {$t(({available:'Available',reserved:'Checkout pending',applied:'Applied to next invoice',used:'Used',review:'Under review'} as Record<string,string>)[reward.status]||'Under review')}</li>{/each}</ul>
      <button disabled={busy||!(configured||data.payments_configured)||data.rewards.some(reward=>reward.kind==='platform'&&['reserved','applied'].includes(reward.status))||!data.rewards.some(reward=>reward.kind==='platform'&&reward.status==='available')} on:click={()=>action('apply',{})}>{$t('Apply reward to next subscription month')}</button>
      <p class="hint">{$t('Welcome and unpaid setup discounts are applied at checkout. Only one subscription reward can be applied at a time.')}</p>
    {/if}
    {#if isPlatform}<div class="settings"><button disabled={busy} on:click={()=>action('program',{enabled:!data?.program.enabled})}>{$t(data.program.enabled?'Pause new referrals':'Enable new referrals')}</button><p class="hint">{$t('Pausing stops new claims. Accepted offers and earned rewards stay saved.')}</p></div>{/if}
  {/if}
</section>
<style>
  .referrals{border:1px solid #d7e1db;border-radius:16px;padding:1.5rem;background:#fff;margin:1.5rem 0}header{display:flex;align-items:center;justify-content:space-between;gap:1rem;flex-wrap:wrap}h3{margin:0}header span,.hint{font-size:.9rem;color:#53625b}input{width:100%;min-width:0;padding:.75rem;border:1px solid #b6c5bc;border-radius:8px;margin:.4rem 0;box-sizing:border-box}form div{display:flex;align-items:center;gap:.6rem}button{padding:.75rem 1rem;border:0;border-radius:8px;background:#087d59;color:white;cursor:pointer}button:disabled{opacity:.55;cursor:default}.settings{border-top:1px solid #e0e6e2;margin-top:1.2rem;padding-top:1.2rem}li{margin:.4rem 0}@media(max-width:550px){form div{flex-wrap:wrap}.referrals{padding:1rem}}
</style>
