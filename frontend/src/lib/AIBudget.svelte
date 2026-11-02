<script lang="ts">
  import {onMount,onDestroy,createEventDispatcher} from 'svelte';
  import {t,language} from './i18n';
  import {subscriptionLocales} from './subscription-format';
  export let tenant:string;
  export let csrf:string;
  export let canManageBilling=true;
  export let canViewCosts=true;
  export let isPlatform=false;
  export let apiPrefix='';
  export let showInitialBudgetChoice=false;
  export let presentation:'full'|'initial'|'history'='full';
  type Recharge={enabled:boolean;amount_pence:number;threshold_pence:number;cap_pence:number;cap_choices:number[];spent_this_month_pence:number;pending_this_month_pence:number;blocked_reason:string;live_available:boolean;attempts:{status:string;amount_pence:number;created:number;failure_code:string}[]};
  type Budget={initial_pack:string;processing_available:boolean;checkout_requests:{pack_id:string;request_id:string;status:string}[];available_pence:number;balance_pence:number;pending_usage_pence:number;added_pence:number;used_pence:number;monthly_spent_pence:number;month:string;paused:boolean;review_required:boolean;configured:boolean;internal:boolean;packs:{id:string;credit_pence:number;total_pence:number;tax_pence:number}[];transactions:{label:string;created:number|string;amount_pence:number;direction:string;receipt_url:string|null;less_than_penny?:boolean}[];page:number;has_next:boolean;automatic_recharge:Recharge;alerts:{enabled:boolean;email_enabled:boolean;threshold_pence:number;threshold_choices:number[]};notifications:{id:string;kind:string;created:number;seen:boolean;details:Record<string,unknown>}[];terms:{rates_url:string;month_reset:string;summary:string}};
  const dispatch=createEventDispatcher<{initialbudget:{total_pence:number};creditstatus:{tenant:string;alerts:{code:string;message:string}[]}}>();
  let data:Budget|null=null;
  let busy=false,error='',message='',page=1;
  let alertsEnabled=true,emailEnabled=false,alertThreshold=200,cap=2500;
  let reviewRecharge=false,accepted=false,initialPack='';
  let controller:AbortController|undefined;
  let disposed=false,confirmedReturn=false;
  const requestIds=new Map<string,string>();
  $: locale=subscriptionLocales[$language];
  $: money=(amount:number)=>new Intl.NumberFormat(locale,{style:'currency',currency:'GBP'}).format(amount/100);
  $: date=(value:number|string)=>new Intl.DateTimeFormat(locale,{dateStyle:'medium',timeStyle:'short',timeZone:'UTC'}).format(new Date(typeof value==='number'?value*1000:value));
  function requestId(key:string){
    const storageKey='v7-budget-request:'+tenant+':'+key;
    let id=requestIds.get(key);try{id=id||sessionStorage.getItem(storageKey)||undefined;}catch{/* Optional storage. */}
    if(!id||!/^[A-Za-z0-9_-]{8,100}$/.test(id))id=crypto.randomUUID();
    requestIds.set(key,id);try{sessionStorage.setItem(storageKey,id);}catch{/* In-view deduplication remains. */}return id;
  }
  function clearId(key:string){requestIds.delete(key);try{sessionStorage.removeItem('v7-budget-request:'+tenant+':'+key);}catch{/* Optional storage. */}}
  function syncRequests(result:Budget){
    for(const pack of result.packs){const key='funds:'+pack.id;const rows=result.checkout_requests||[];const pending=rows.find(row=>row.pack_id===pack.id&&!['paid','expired','cancelled','failed'].includes(row.status));
      let previous=requestIds.get(key);try{previous=previous||sessionStorage.getItem('v7-budget-request:'+tenant+':'+key)||undefined;}catch{/* Optional storage. */}
      if(pending){requestIds.set(key,pending.request_id);try{sessionStorage.setItem('v7-budget-request:'+tenant+':'+key,pending.request_id);}catch{/* Optional storage. */}}
      else if(rows.some(row=>row.pack_id===pack.id&&row.request_id===previous)){clearId(key);}
    }
  }
  function safeError(code:string){
    const errors:Record<string,string>={
      budget_live_recharge_not_enabled:'Automatic recharge is awaiting platform activation. You can add funds manually.',
      budget_payment_needs_review:'This authorisation needs review. Contact support before trying again.',
      budget_payment_in_progress:'A payment is already being checked. Refresh your balance before trying again.',
      budget_authorisation_required:'Review the recharge amount and monthly limit, then confirm your authorisation.',
      budget_authorisation_mismatch:'Your authorisation could not be confirmed. Refresh and try again.',
      budget_authorisation_needs_review:'This authorisation needs review. Contact support before trying again.',
      budget_active_business_required:'Activate your business subscription and setup before adding AI funds.',
      budget_checkout_unavailable:'Checkout is unavailable. Check your subscription and business approval, then try again.',
      business_approval_required:'Your business needs approval before making a payment.',
      unauthorized:'Your sign-in has expired. Sign in again.',forbidden:'You do not have permission to change billing settings.',
      invalid_budget_settings:'Check your alert and spending settings.',invalid_budget_request:'Refresh AI Budget before trying again.'};
    return errors[code]||'AI Budget could not be updated. Refresh before trying again, or contact support.';
  }
  async function read(path:string,body?:Record<string,unknown>,signal?:AbortSignal){
    const response=await fetch(apiPrefix+'/billing/ai-budget'+path+(path.includes('?')?'&':'?')+'tenant='+encodeURIComponent(tenant),{credentials:'same-origin',signal,...(body?{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(body)}:{})});
    const result=await response.json();
    if(!response.ok)throw new Error(String(result.error||''));
    return result;
  }
  function apply(result:Budget){
    if(result.automatic_recharge.enabled){for(const choice of result.automatic_recharge.cap_choices)clearId('authorise:'+choice);}
    data=result;syncRequests(result);initialPack=result.initial_pack||'';dispatch('initialbudget',{total_pence:result.packs.find(pack=>pack.id===initialPack)?.total_pence||0});alertsEnabled=result.alerts.enabled;emailEnabled=result.alerts.email_enabled;
    alertThreshold=result.alerts.threshold_pence;cap=result.automatic_recharge.cap_pence;
    const alerts=result.internal?[]:result.review_required?[{code:'financial_review_required',message:'Your AI balance needs a review.'}]:result.paused?[{code:'insufficient_credit',message:'Add AI funds to resume paid responses.'}]:[];
    dispatch('creditstatus',{tenant,alerts});
  }
  async function refresh(){
    if(disposed||!canViewCosts)return;
    controller?.abort();const request=new AbortController();controller=request;busy=true;error='';
    const timeout=setTimeout(()=>request.abort(),25000);
    try{const result=await read('?page='+page,undefined,request.signal);if(!disposed&&controller===request&&!request.signal.aborted)apply(result);}
    catch(failure){if(!disposed&&controller===request)error=request.signal.aborted?'The update could not be confirmed. Refresh your balance before trying again.':safeError(failure instanceof Error?failure.message:'');}
    finally{clearTimeout(timeout);if(!disposed&&controller===request){busy=false;controller=undefined;}}
  }
  async function action(path:string,body:Record<string,unknown>){
    if(disposed||busy||!canManageBilling)return;
    const request=new AbortController();controller=request;busy=true;error='';message='';
    const timeout=setTimeout(()=>request.abort(),25000);
    try{
      const result=await read(path,body,request.signal);
      if(disposed||controller!==request||request.signal.aborted)return;
      if(result.url){const destination=new URL(result.url);if(destination.protocol!=='https:'||destination.hostname!=='checkout.stripe.com')throw new Error('');window.location.assign(result.url);return;}
      if(path==='/checkout'&&['paid','expired','failed'].includes(result.status)&&typeof body.pack_id==='string')clearId('funds:'+body.pack_id);
      if(path==='/automatic-recharge/disable'||path==='/automatic-recharge/confirm'){for(const choice of data?.automatic_recharge.cap_choices||[])clearId('authorise:'+choice);}
      reviewRecharge=false;accepted=false;message='AI Budget settings saved.';
      const report=await read('?page='+page,undefined,request.signal);
      if(!disposed&&controller===request&&!request.signal.aborted)apply(report);
    }catch(failure){if(!disposed&&controller===request)error=request.signal.aborted?'The update could not be confirmed. Refresh your balance before trying again.':safeError(failure instanceof Error?failure.message:'');}
    finally{clearTimeout(timeout);if(!disposed&&controller===request){busy=false;controller=undefined;}}
  }
  onMount(()=>{void (async()=>{await refresh();if(!disposed&&!confirmedReturn&&new URLSearchParams(window.location.search).get('authorisation')==='processing'){confirmedReturn=true;await action('/automatic-recharge/confirm',{});}})();});
  onDestroy(()=>{disposed=true;controller?.abort();});
</script>

<section class="budget" id="ai-budget" aria-label={$t('AI Budget')} aria-busy={busy}>
  <header><div><p class="eyebrow">{$t('AI Budget')}</p><h2>{$t(presentation==='history'?'Your usage and balance history':presentation==='initial'?'Initial AI budget':'Your AI balance')}</h2><p>{$t(presentation==='history'?'Review recorded usage and purchases, with receipts where available.':presentation==='initial'?'Optional initial funding, separate from your subscription.':'Add funds, manage automatic recharge and keep control of your AI spending.')}</p></div><button class="secondary" disabled={busy} on:click={refresh}>{$t('Refresh balance')}</button></header>
  {#if error}<p class="notice error" role="alert">{$t(error)}</p>{/if}
  {#if message}<p class="notice" role="status">{$t(message)}</p>{/if}
  {#if data}
    {#if data.internal}
      <p class="notice">{$t('This internal workspace uses platform funding. It does not need a customer AI balance.')}</p>
      {#if isPlatform}<a href="/console/provider-funding">{$t('Open AI Provider Funding')}</a>{/if}
    {:else}
      <div class="balance-card"><p class="balance"><bdi>{money(data.available_pence)}</bdi><span>{$t('available')}</span></p><p>{$t('{used} used · {added} added',{used:money(data.used_pence),added:money(data.added_pence)})}</p>{#if data.pending_usage_pence}<p>{$t('{amount} is awaiting usage confirmation.',{amount:money(data.pending_usage_pence)})}</p>{/if}</div>
      {#if data.review_required}<p class="notice" role="status">{$t('Your balance needs a review. Contact support; your recorded funds and history are preserved.')}</p>{:else if !data.processing_available}<p class="notice" role="status">{$t('AI processing is temporarily unavailable. Your balance is preserved; adding funds will not resolve this.')}</p>{:else if data.paused}<p class="notice" role="status">{$t('Add funds to resume paid AI responses. Your contact details and saved business information remain available.')}</p>{/if}
      {#if showInitialBudgetChoice}<article class="panel"><h3>{$t('Initial AI budget')}</h3><form on:submit|preventDefault={()=>action('/preferences',{initial_pack:initialPack})}><label>{$t('Choose initial funding')}<select bind:value={initialPack} disabled={busy||!canManageBilling}><option value="">{$t('Choose later')}</option>{#each data.packs as pack}<option value={pack.id}>{money(pack.credit_pence)}</option>{/each}</select></label><p>{$t('Save your initial funding choice, then complete its separate checkout after business activation. This choice does not take payment or create a monthly purchase.')}</p><button disabled={busy||!canManageBilling}>{$t('Save initial budget choice')}</button></form></article>{/if}
      {#if presentation==='full'}<div class="budget-grid">
        <article class="panel"><h3>{$t('Add funds')}</h3><p>{$t('Choose a one-time amount. No automatic monthly purchase is created.')}</p><div class="fund-buttons">{#each data.packs as pack}<button disabled={busy||!canManageBilling||!data.configured} on:click={()=>action('/checkout',{pack_id:pack.id,request_id:requestId('funds:'+pack.id)})}>{money(pack.credit_pence)}{#if pack.tax_pence}<small>{$t('Pay {price} including VAT',{price:money(pack.total_pence)})}</small>{/if}</button>{/each}</div><p class="small">{$t('You receive the full advertised AI balance. Payment processing fees are not taken from it.')}</p></article>
        <article class="panel"><h3>{$t('Monthly spending')}</h3><p class="figure"><bdi>{money(data.monthly_spent_pence)}</bdi></p><p>{$t('Actual AI usage this calendar month (UTC). Adding funds is not usage spending.')}</p><p>{$t('Automatic purchases: {spent} of {cap}',{spent:money(data.automatic_recharge.spent_this_month_pence),cap:money(data.automatic_recharge.cap_pence)})}</p>{#if data.automatic_recharge.pending_this_month_pence}<p>{$t('{amount} of the limit is awaiting payment confirmation.',{amount:money(data.automatic_recharge.pending_this_month_pence)})}</p>{/if}</article>
        <article class="panel"><h3>{$t('Automatic £5 recharge')}</h3><p>{$t('Automatically add £5 when your settled AI balance falls below £2.')}</p><strong>{$t(data.automatic_recharge.enabled?(data.automatic_recharge.blocked_reason?'Paused':'Enabled'):'Disabled')}</strong><p>{$t('Monthly automatic purchase limit: {amount}',{amount:money(data.automatic_recharge.cap_pence)})}</p><p class="small">{$t('This limit covers automatic purchases only. It does not limit manual top-ups, AI usage spending or subscription payments. It resets each calendar month in UTC.')}</p>
          {#if data.automatic_recharge.blocked_reason}<p class="notice">{$t('Automatic recharge needs attention. Add funds manually or review your payment authorisation.')}</p>{/if}
          {#if data.automatic_recharge.enabled}<button class="secondary" disabled={busy||!canManageBilling} on:click={()=>action('/automatic-recharge/disable',{})}>{$t('Disable automatic recharge')}</button><button class="secondary" disabled={busy||!canManageBilling} on:click={()=>reviewRecharge=!reviewRecharge}>{$t('Change spending limit')}</button>
          {:else if data.automatic_recharge.live_available}<button disabled={busy||!canManageBilling} on:click={()=>reviewRecharge=!reviewRecharge}>{$t('Set up automatic recharge')}</button>
          {:else}<p class="small">{$t('Automatic recharge is awaiting platform activation. You can add funds manually.')}</p>{/if}
          {#if data.automatic_recharge.attempts.some(attempt=>['reserved','requires_action','unknown','processing'].includes(attempt.status))}<button class="secondary" disabled={busy||!canManageBilling} on:click={()=>action('/automatic-recharge/resolve',{})}>{$t('Review or cancel pending payment')}</button>{/if}
          {#if data.automatic_recharge.blocked_reason&&!data.automatic_recharge.attempts.some(attempt=>['reserved','dispatching','requires_action','unknown','processing'].includes(attempt.status))}<button class="secondary" disabled={busy||!canManageBilling} on:click={()=>reviewRecharge=!reviewRecharge}>{$t('Review payment authorisation')}</button>{/if}
          {#if !data.automatic_recharge.enabled&&data.automatic_recharge.blocked_reason==='authorisation_pending'}<button class="secondary" disabled={busy||!canManageBilling} on:click={()=>action('/automatic-recharge/disable',{})}>{$t('Cancel pending card setup')}</button>{/if}
          {#if reviewRecharge}<form on:submit|preventDefault={()=>action('/automatic-recharge/authorise',{cap_pence:Number(cap),accepted_terms:accepted,request_id:requestId('authorise:'+cap)})}><label>{$t('Monthly automatic purchase limit')}<select bind:value={cap}>{#each data.automatic_recharge.cap_choices as choice}<option value={choice}>{money(choice)}</option>{/each}</select></label><p>{$t('Authorise future £5 card payments when your settled balance is below £2, up to {cap} each calendar month (UTC).',{cap:money(Number(cap))})}</p><p class="small">{$t('You can disable future recharges at any time. An already-started payment may complete. Each £5 payment adds £5 of V7 AI balance and includes any applicable VAT.')}</p><label class="check"><input type="checkbox" bind:checked={accepted} required/><span>{$t('I authorise these automatic payments and accept the displayed amount and monthly limit.')}</span></label><button disabled={busy||!accepted}>{$t('Authorise securely with Stripe')}</button></form>{/if}
        </article>
        <article class="panel"><h3>{$t('Low-balance alerts')}</h3><p>{$t('Alerts work independently from automatic recharge.')}</p><form on:submit|preventDefault={()=>action('/preferences',{alerts_enabled:alertsEnabled,email_alerts:emailEnabled,alert_threshold_pence:Number(alertThreshold)})}><label class="check"><input type="checkbox" bind:checked={alertsEnabled} disabled={!canManageBilling||busy}/><span>{$t('Show low-balance alerts')}</span></label><label class="check"><input type="checkbox" bind:checked={emailEnabled} disabled={!canManageBilling||busy}/><span>{$t('Email me low-balance alerts')}</span></label><label>{$t('Notify below')}<select bind:value={alertThreshold} disabled={!canManageBilling||busy}>{#each data.alerts.threshold_choices as threshold}<option value={threshold}>{money(threshold)}</option>{/each}</select></label><p class="small">{$t('We notify you when your balance crosses the threshold and avoid repeated alerts for the same low balance.')}</p><button disabled={busy||!canManageBilling}>{$t('Save alert settings')}</button></form></article>
      </div>
      {/if}<p class="terms">{$t('Your AI balance buys V7 AI processing services, separate from your subscription. Prices depend on the selected model and the amount of text or audio processed. No AI allowance is included.')} <a href={data.terms.rates_url}>{$t('View usage prices and payment terms')}</a></p>
      {#if presentation==='full' && data.notifications.length}<article class="panel"><h3>{$t('Budget notifications')}</h3>{#each data.notifications as notice}<div class="notification"><p>{$t(notice.kind==='low_balance'?'Your AI balance is running low.':notice.kind==='recharge_succeeded'?'£5 was added by automatic recharge.':notice.kind==='recharge_cap'?'Your monthly automatic purchase limit has been reached.':notice.kind==='authentication_required'?'Your card needs confirmation. Automatic recharge is paused.':'A payment needs attention. Review your AI Budget settings.')} <small>{date(notice.created)}</small></p>{#if !notice.seen}<button class="secondary" disabled={busy||!canManageBilling} on:click={()=>action('/notifications/seen',{id:notice.id})}>{$t('Mark as read')}</button>{/if}</div>{/each}</article>{/if}
      {#if presentation!=='initial'}<article class="panel"><h3>{$t('Balance and usage history')}</h3>
      <!-- svelte-ignore a11y_no_noninteractive_tabindex (Keyboard users must be able to scroll the transaction table.) -->
      <div class="history" role="region" aria-label={$t('Balance and usage history')} tabindex="0"><table><thead><tr><th>{$t('Date (UTC)')}</th><th>{$t('Description')}</th><th>{$t('Balance change')}</th><th>{$t('Receipt')}</th></tr></thead><tbody>{#each data.transactions as entry}<tr><td>{date(entry.created)}</td><td>{$t(entry.label)}</td><td><bdi>{entry.direction==='used'?'−':'+'}{entry.less_than_penny?$t('Less than £0.01'):money(entry.amount_pence)}</bdi></td><td>{#if entry.receipt_url}<a href={entry.receipt_url} target="_blank" rel="noopener noreferrer">{$t('View receipt')}</a>{:else}{$t('Not available')}{/if}</td></tr>{:else}<tr><td colspan="4">{$t('No transactions yet.')}</td></tr>{/each}</tbody></table></div><div class="pagination"><button class="secondary" disabled={busy||page===1} on:click={()=>{page--;void refresh();}}>{$t('Previous')}</button><span>{$t('Page {page}',{page})}</span><button class="secondary" disabled={busy||!data.has_next} on:click={()=>{page++;void refresh();}}>{$t('Next')}</button></div></article>{/if}
    {/if}
  {:else if busy}<p role="status">{$t('Loading AI Budget…')}</p>{/if}
</section>

<style>
  .budget{display:grid;grid-template-columns:minmax(0,1fr);gap:1.25rem;color:#20322c;min-width:0;width:100%;box-sizing:border-box}.budget header{display:flex;align-items:start;justify-content:space-between;gap:1rem}.budget h2,.budget h3,.budget p{margin:0 0 .75rem}.eyebrow{color:#087451;font-size:.75rem;font-weight:750;letter-spacing:.1em;text-transform:uppercase}.budget-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem}.panel,.balance-card{min-width:0;max-width:100%;box-sizing:border-box;padding:1.4rem;border:1px solid #dce4df;border-radius:14px;background:#fff}.balance-card{background:#eef5f1;border-color:#bbd3c5}.balance{display:flex;align-items:baseline;gap:.75rem;flex-wrap:wrap}.balance bdi{font-size:2.8rem;font-weight:750;letter-spacing:-.05em}.balance span,.small,.terms{color:#53645c;font-size:.875rem;line-height:1.65}.figure{font-size:2rem;font-weight:700}.fund-buttons{display:flex;flex-wrap:wrap;gap:.6rem;margin:1rem 0}.budget button{min-height:44px;border:1px solid #07543b;border-radius:9px;background:#07543b;color:#fff;padding:.65rem 1rem;font:inherit;font-weight:650;cursor:pointer}.budget button.secondary{background:#fff;color:#07543b;border-color:#bdcec3}.budget button:disabled{opacity:.55;cursor:not-allowed}.budget button small{display:block;font-size:.72rem}.budget button:focus-visible,.budget a:focus-visible,.budget input:focus-visible,.budget select:focus-visible{outline:3px solid #c18d38;outline-offset:3px}.budget a{color:#086747;text-decoration:underline}.budget form{display:grid;gap:.9rem;margin-top:1rem}.budget label{display:grid;gap:.45rem}.budget .check{display:flex;align-items:start;gap:.6rem;line-height:1.5}.budget input[type=checkbox]{width:1.15rem;height:1.15rem;accent-color:#07543b;flex:none;margin:.15rem 0}.budget select{min-height:44px;border:1px solid #bfcac4;border-radius:8px;padding:.5rem;background:#fff;color:inherit;font:inherit}.notice{padding:.85rem 1rem;background:#f0f5f2;border:1px solid #d3e0d8;border-radius:9px;line-height:1.6}.notice.error{border-color:#c68c8c;background:#fff3f3;color:#812727}.notification{display:flex;justify-content:space-between;gap:1rem;border-top:1px solid #e3e9e5;padding:.8rem 0}.notification small{display:block;color:#66776d}.history{overflow:auto}.history table{width:100%;border-collapse:collapse;font-size:.875rem}.history th,.history td{padding:.8rem;text-align:start;border-bottom:1px solid #e2e8e3;white-space:nowrap}.pagination{display:flex;align-items:center;justify-content:space-between;gap:.75rem;margin-top:1rem}@media(max-width:720px){.budget-grid{grid-template-columns:1fr}.budget header{flex-direction:column}.panel,.balance-card{min-width:0;max-width:100%;box-sizing:border-box;padding:1.1rem}.balance bdi{font-size:2.4rem}.notification{flex-direction:column}.fund-buttons button{flex:1}.budget{min-width:0}}
</style>
