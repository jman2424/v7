<script lang="ts">
  import { t, language } from './i18n';
  import { subscriptionLocales, subscriptionMoney, subscriptionPrice, subscriptionMonth, subscriptionError } from './subscription-format';
  import {onMount,onDestroy,createEventDispatcher} from 'svelte';
  import TrendChart from './TrendChart.svelte';
  import UsageCredits from './UsageCredits.svelte';
  import Referrals from './Referrals.svelte';
  import ModelPicker from './ModelPicker.svelte';
  import WhatsAppConnection from './WhatsAppConnection.svelte';
  export let tenant:string;
  export let csrf:string;
  export let isPlatform=false;
  export let canManageBilling=true;
  export let canViewCosts=true;
  export let canViewIntegrations=false;
  export let apiPrefix='';
  type Contract={kind:string;status:string;next_due:number|null;paused:number;cancel_at_end:number;implementation_paid:number};
  type Invoice={id:string;kind:string;month:string;issued:number;due:number|null;total:number;paid:number;remaining:number;status:string;url:string|null;lines:{description:string;amount:number}[]};
  type Plan={id:string;name:string;audience:string;monthly_pence:number;setup_pence:number;website_conversations:number;whatsapp_messages:number;message_usage_model?:string;locations:number;staff:number;analytics:string;api_access:string;onboarding:string};
  type UsageAlert={resource:string;message:string};
  type ChannelAllowance={used:number;limit:number;paused:boolean;enforced?:boolean;measured_by?:string};
  type Allowance={month:string;mode:string;website_conversations:ChannelAllowance;whatsapp_messages:ChannelAllowance;alerts:UsageAlert[]};
  type PlanState={selected_plan:string|null;active_plan:string|null;setup_plan:string|null;whatsapp_paused:boolean;checkout_pending:boolean;checkout_expires:number|null};
  type Report={discount_percent:number;configured:boolean;vat_percent:number;contracts:Contract[];invoices:Invoice[];totals:{paid:number;due:number;approved_api_due:number};usage:{month:string;calls:number;unpriced:number;estimated_pence:number|null}[];approved_api_charges:{month:string;amount:number}[];whatsapp_enabled:boolean;plans?:Plan[];pricing_version?:string;internal?:boolean;complimentary?:boolean;plan_state?:PlanState|null;allowance?:Allowance|null;management?:{can_change_plan:boolean;can_cancel:boolean}};
  type Company={key:string;name:string;contracts:Contract[];totals:{paid:number;due:number};plan_state?:PlanState|null;allowance?:Allowance|null};
  const dispatch=createEventDispatcher<{company:string;creditstatus:{tenant:string;alerts:{code:string;message:string}[]}}>();
  let data:(Report&{referral_setup_percent?:number})|null=null;
  let companies:Company[]=[];
  let companyCount=0;
  let page=1;
  let hasNext=false;
  let search='';
  let busy=false;
  let error='';
  let message='';
  let whatsappOpen=false;
  let invoiceKind='all';
  let invoicePage=1;
  let discountCode='';
  let reviewPlanId='';
  let controller:AbortController|undefined;
  let companyController:AbortController|undefined;
  let companyBusy=false;
  let disposed=false;
  $: locale=subscriptionLocales[$language];
  $: money=(pence:number|null|undefined)=>pence==null?$t('Not available'):subscriptionMoney(pence,locale);
  $: date=(value:number|null|undefined)=>value?new Intl.DateTimeFormat(locale,{timeZone:'UTC'}).format(new Date(value*1000)):$t('Not scheduled');
  $: dateTime=(value:number)=>new Intl.DateTimeFormat(locale,{dateStyle:'medium',timeStyle:'short',timeZone:'UTC'}).format(new Date(value*1000));
  $: month=(value:string)=>subscriptionMonth(value,locale);
  $: name=(kind:string)=>$t(({platform:'Platform subscription',whatsapp:'WhatsApp add-on',api:'API usage',implementation:'Implementation'} as Record<string,string>)[kind]||'Other charge');
  $: count=(value:number)=>new Intl.NumberFormat(locale).format(value);
  $: status=(value:string|undefined)=>$t(({active:'Active',trialing:'Trial',past_due:'Payment overdue',unpaid:'Unpaid',incomplete:'Payment pending',paused:'Paused',canceled:'Cancelled',not_started:'Not subscribed',incomplete_expired:'Checkout expired',paid:'Paid',open:'Open',draft:'Draft',void:'Void',uncollectible:'Uncollectible'} as Record<string,string>)[value||'not_started']||'Not available');
  $: usageAlert=(alert:UsageAlert)=>$t(alert.resource==='website_conversations'?'New website conversations are paused until the next monthly allowance. Existing conversations can continue.':alert.resource==='whatsapp_messages'?'WhatsApp is paused. Check your provider connection and usage budget.':'Paid AI requests are paused because the remaining allowance cannot safely cover the request or its cost is unknown. Saved business knowledge remains available.');
  $: baseContract=data?.contracts.find(row=>row.kind==='platform');
  $: implementationPaid=Boolean(baseContract?.implementation_paid||data?.contracts.some(row=>row.kind==='implementation'&&row.status==='paid'));
  $: waContract=data?.contracts.find(row=>row.kind==='whatsapp');
  $: tiered=data?.pricing_version==='tiered_v1'||Boolean(data?.plan_state);
  $: legacyBilling=!tiered&&Boolean(baseContract&&['active','trialing','past_due','unpaid','incomplete','paused'].includes(baseContract.status));
  $: selectedPlan=data?.plans?.find(plan=>plan.id===data?.plan_state?.selected_plan);
  $: activePlan=data?.plans?.find(plan=>plan.id===data?.plan_state?.active_plan);
  $: setupPlan=data?.plans?.find(plan=>plan.id===data?.plan_state?.setup_plan)||selectedPlan;
  $: planLocked=Boolean(activePlan||implementationPaid||legacyBilling);
  $: checkoutPending=Boolean(data?.plan_state?.checkout_pending);
  $: reviewPlan=canManageBilling&&!planLocked&&!checkoutPending
    ? data?.plans?.find(plan=>plan.id===reviewPlanId) : undefined;
  $: monthlyPrice=activePlan?activePlan.monthly_pence:40000;
  $: discounted=(pence:number)=>subscriptionPrice(pence,data?.discount_percent||0,data?.vat_percent||0).beforeVat;
  $: setupPercent=Math.max(data?.discount_percent||0,data?.referral_setup_percent||0);
  $: setupDiscounted=(pence:number)=>subscriptionPrice(pence,setupPercent,data?.vat_percent||0).beforeVat;
  $: setupTotal=(pence:number)=>subscriptionPrice(pence,setupPercent,data?.vat_percent||0).total;
  $: totalWithVat=(pence:number)=>subscriptionPrice(pence,data?.discount_percent||0,data?.vat_percent||0).total;
  $: undiscountedTotal=(pence:number)=>subscriptionPrice(pence,0,data?.vat_percent||0).total;
  $: invoices=data?.invoices.filter(row=>invoiceKind==='all'||row.kind===invoiceKind)||[];
  $: months=[...new Set(data?.invoices.map(row=>row.month)||[])].sort().slice(-12);
  $: paidMonths=months.map(month=>(data?.invoices.filter(row=>row.month===month).reduce((sum,row)=>sum+row.paid,0)||0)/100);
  $: dueMonths=months.map(month=>(data?.invoices.filter(row=>row.month===month&&row.status==='open').reduce((sum,row)=>sum+row.remaining,0)||0)/100);
  async function read(path:string, body?:Record<string,unknown>, signal?:AbortSignal){
    const response=await fetch(apiPrefix+'/billing/'+path+(path.includes('?')?'&':'?')+'tenant='+encodeURIComponent(tenant),{credentials:'same-origin',signal,...(body?{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(body)}:{})});
    const result=await response.json();
    if(!response.ok)throw new Error(subscriptionError(String(result.error||'')));
    return result;
  }
  async function refresh(){
    controller?.abort();const request=new AbortController();controller=request;busy=true;error='';
    const timeout=setTimeout(()=>request.abort(),25000);
    try{
      const result=await read('subscription',undefined,request.signal);
      if(disposed||controller!==request||request.signal.aborted)return;
      data=result;if(isPlatform)void listCompanies();
    }catch(failure){if(!disposed&&controller===request)error=request.signal.aborted?'Billing loading timed out. Try refreshing.':subscriptionError(failure instanceof Error?failure.message:'');}
    finally{clearTimeout(timeout);if(!disposed&&controller===request){busy=false;controller=undefined;}}
  }
  async function listCompanies(){
    companyController?.abort();const request=new AbortController();companyController=request;companyBusy=true;
    const timeout=setTimeout(()=>request.abort(),25000);
    try{
      const result=await read('companies?page='+page+'&search='+encodeURIComponent(search),undefined,request.signal);
      if(disposed||companyController!==request||request.signal.aborted)return;
      companies=result.companies;companyCount=result.matched??result.total;hasNext=result.has_next;
    }catch(failure){if(!disposed&&companyController===request)error=request.signal.aborted?'Company loading timed out. Try searching again.':subscriptionError(failure instanceof Error?failure.message:'');}
    finally{clearTimeout(timeout);if(!disposed&&companyController===request){companyBusy=false;companyController=undefined;}}
  }
  async function action(path:string,body:Record<string,unknown>){
    if(busy||disposed)return;
    const request=new AbortController();controller=request;busy=true;error='';message='';
    const timeout=setTimeout(()=>request.abort(),25000);
    try{
      const result=await read(path,body,request.signal);
      if(disposed||controller!==request||request.signal.aborted)return;
      if(result.url){window.location.assign(result.url);return;}
      if(path==='discount')discountCode='';
      message=path==='discount'?'Discount saved for this business. It applies automatically to the platform subscription and implementation. Existing invoices are unchanged.':path==='select-plan'?'Plan selected. Subscribe and pay its one-time setup to activate your business.':path==='cancel-checkout'?'Pending unpaid checkout cancelled. Paid setup and existing subscriptions remain unchanged.':path==='whatsapp'?'WhatsApp setting saved.':'Saved. Payment status updates after Stripe confirms it.';
      await refresh();
    }catch(failure){if(!disposed&&controller===request)error=request.signal.aborted?'The billing update could not be confirmed. Refresh payments before trying again.':subscriptionError(failure instanceof Error?failure.message:'');}
    finally{clearTimeout(timeout);if(!disposed&&controller===request){busy=false;controller=undefined;}}
  }
  onMount(()=>{
    reviewPlanId=new URLSearchParams(window.location.search).get('plan')||'';
    void refresh();
  });onDestroy(()=>{disposed=true;controller?.abort();companyController?.abort();});
</script>

<section class="billing" lang={$language} dir={$language==='ar'?'rtl':'ltr'} aria-label={$t('Subscription and payments')}>
  {#if isPlatform}
  <article class="panel"><header><div><h2>{$t('All company subscriptions')}</h2><p>{$t('{count} companies on your platform, including those without a subscription.',{count:count(companyCount)})}</p></div></header>
    <form class="controls" on:submit|preventDefault={()=>{page=1;listCompanies();}}><label>{$t('Find a company')}<input bind:value={search} placeholder={$t('Company name or key')}/></label><button disabled={busy||companyBusy}>{$t('Search')}</button></form>
    <div class="company-list">{#each companies as company}{@const alerts=company.allowance?.alerts||[]}{@const companyPlan=data?.plans?.find(plan=>plan.id===company.plan_state?.active_plan)}<button class:chosen={company.key===tenant} on:click={()=>dispatch('company',company.key)}><strong><bdi>{company.name} · {company.key}</bdi>{#if companyPlan}<small class="company-plan">{$t('{plan} plan',{plan:companyPlan.name})}</small>{/if}{#if alerts.length}<small class="company-alert">{$t('{count} usage alerts',{count:count(alerts.length)})} · {usageAlert(alerts[0])}</small>{/if}</strong><span>{status(company.contracts.find(row=>row.kind==='platform')?.status)}</span><span>{$t('{due} outstanding · {paid} paid',{due:money(company.totals.due),paid:money(company.totals.paid)})}</span></button>{/each}</div>
    {#if companyBusy}<p role="status">{$t('Loading companies…')}</p>{/if}
    <div class="controls"><button disabled={page===1||busy||companyBusy} on:click={()=>{page--;listCompanies();}}>{$t('Previous')}</button><span>{$t('Page {page}',{page:count(page)})}</span><button disabled={!hasNext||busy||companyBusy} on:click={()=>{page++;listCompanies();}}>{$t('Next')}</button></div>
  </article>
  {/if}
  <header><div><h2><bdi>{tenant}</bdi> · {$t('Subscription and payments')}</h2><p>{$t(data?.vat_percent ? 'Monthly billing in pounds, with a separate one-time setup. VAT-inclusive totals appear below each price and before payment.' : 'Monthly billing in pounds, with a separate one-time setup. No VAT charged; Vertex Seven is not VAT-registered.')}</p></div><div class="controls">{#if data}<a href="#cancel-subscription">{$t('Cancel subscription')}</a>{/if}{#if canViewCosts && (!data?.internal || isPlatform)}<a href="#ai-usage-credit">{$t('Top up AI credit')}</a>{/if}{#if canManageBilling && baseContract && !['not_started','incomplete_expired'].includes(baseContract.status)}<button disabled={busy||!data?.configured} on:click={()=>action('portal',{})}>{$t('Manage payments in Stripe')}</button>{/if}<button disabled={busy} on:click={refresh}>{$t('Refresh payments')}</button></div></header>
  {#if error}<p class="notice error" role="alert">{$t(error)}</p>{/if}{#if message}<p class="notice" role="status">{$t(message)}</p>{/if}
  {#if busy}<p class="notice loading" role="status">{$t('Updating billing…')}</p>{/if}
  {#if data}
    <article class="panel cancellation" id="cancel-subscription" aria-labelledby="cancel-subscription-heading">
      <div class="cancellation-heading"><span class="cancellation-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="12" r="9"/><path d="m9 9 6 6m0-6-6 6"/></svg></span><div><h2 id="cancel-subscription-heading">{$t('Cancel subscription')}</h2><p>{$t('Manage renewal of your platform subscription.')}</p></div></div>
      {#if data.internal}
        <p class="notice">{$t('This is an internal workspace. There is no paid platform subscription to cancel.')}</p>
      {:else if data.complimentary}
        <p class="notice">{$t('This business has complimentary access. There is no paid platform subscription to cancel.')}</p>
      {:else if baseContract?.cancel_at_end && baseContract.status!=='canceled'}
        <p class="notice" role="status"><strong>{$t('Cancellation scheduled')}</strong><br/>{baseContract.next_due ? $t('Your platform subscription ends on {date}.',{date:date(baseContract.next_due)}) : $t('Your platform subscription will end at the close of the current billing period.')}</p>
        <p>{$t('Refresh payments after returning from Stripe to see the latest status.')}</p>
      {:else if baseContract?.status==='canceled'}
        <p class="notice" role="status"><strong>{$t('Subscription cancelled')}</strong><br/>{$t('Your platform subscription is already cancelled. Existing invoices remain in Payment history.')}</p>
      {:else if data.management?.can_cancel}
        {#if activePlan}<p class="cancellation-plan">{$t('Current plan')}: <strong><bdi>{activePlan.name}</bdi></strong></p>{/if}
        <p>{$t('Cancellation stops renewal at the end of the current billing period. Review and confirm it in Stripe.')}</p>
        <p>{$t('Opening the review does not cancel your subscription. Cancellation does not automatically refund previous payments or prepaid AI credit.')}</p>
        {#if canManageBilling}<button class="cancel-button" disabled={busy||!data.configured} on:click={()=>action('cancel-subscription',{})}>{$t('Review cancellation in Stripe')} <span aria-hidden="true">↗</span></button>
        {:else}<p class="notice">{$t('Only your business owner can cancel the subscription.')}</p>{/if}
        {#if !data.configured}<p>{$t('Your platform administrator needs to connect payments.')}</p>{/if}
      {:else if !baseContract || ['not_started','incomplete_expired'].includes(baseContract.status)}
        <p class="notice">{$t('There is no active paid platform subscription to cancel.')}</p>
      {:else}
        <p class="notice">{$t('Self-service cancellation is not available for the current subscription status. Refresh payments or contact the platform administrator for help.')}</p>
      {/if}
    </article>
    {#if canManageBilling}{#key tenant}<Referrals {tenant} {csrf} {apiPrefix} {isPlatform} configured={data.configured} on:changed={refresh}/>{/key}{/if}
    {#if data.complimentary}<p class="notice">{$t('Complimentary Scale access. No subscription payment or setup invoice was created. AI credit is separate.')}</p>{/if}
    {#if isPlatform && data.complimentary}<button disabled={busy} on:click={()=>action('complimentary-plan',{plan_id:'scale',enabled:false,reason:'Platform administrator revoked complimentary Scale access'})}>{$t('Revoke complimentary Scale for {tenant}',{tenant})}</button>{/if}
    {#if isPlatform && !data.complimentary}<button disabled={busy} on:click={()=>action('complimentary-plan',{plan_id:'scale',reason:'Platform owner requested complimentary Scale for own workspace'})}>{$t('Grant complimentary Scale to {tenant}',{tenant})}</button>{/if}
    {#if !canManageBilling}<p class="notice">{$t('Read-only access. Your business owner manages payments and subscriptions.')}</p>{/if}
    {#if !data.internal && !data.complimentary}
      <article class="panel" id="change-plan"><h2>{$t('Change plan')}</h2>
        <p>{$t('Compare plans below. An active plan change opens Stripe for a final review before you confirm.')}</p>
        {#if activePlan}<p>{$t('Stripe shows any prorated charge or credit and asks you to confirm. Your billing date and paid setup are retained.')}</p>{/if}
        {#if legacyBilling}<p>{$t('Your plan is linked to its subscription or paid setup. Contact the platform administrator to arrange a plan change.')}</p><p>{$t('Separate WhatsApp subscriptions have their own cancellation controls below.')}</p>{/if}
      </article>
    {/if}
    {#if !data.configured && !data.internal && !data.complimentary}<p class="notice">{$t('Stripe payments are not connected yet.')} {$t(isPlatform?(data.vat_percent ? 'Configure the Stripe API key, webhook signing secret and exclusive 20% VAT tax rate on the server.' : 'Configure the Stripe live API key and matching webhook signing secret on the server. No VAT tax rate is required while unregistered.'):'Your platform administrator needs to connect payments.')} {$t('No payment has been taken.')}</p>{/if}
    {#if data.internal}<p class="notice">{$t('Internal website agent. This platform-owned workspace does not need a customer subscription.')}</p>{/if}
    {#if canManageBilling && !data.internal && !data.complimentary}
      {#if data.discount_percent}<p class="notice">{$t('{percent}% discount saved. Platform renewals keep this discount automatically; it also applies to your setup checkout. Existing invoices are unchanged.',{percent:count(data.discount_percent)})}</p>
      {:else}<details class="panel"><summary>{$t('Have a discount code?')}</summary><form on:submit|preventDefault={()=>action('discount',{code:discountCode})}><label>{$t('Discount code')}<input bind:value={discountCode} maxlength="100" autocomplete="off" spellcheck="false" required /></label><button disabled={busy||!discountCode.trim()}>{$t('Apply to this business')}</button></form></details>{/if}
    {/if}
    {#if !legacyBilling && !data.internal && !data.complimentary}
      {#if reviewPlan}<p class="notice" role="status"><strong>{$t('Review {plan}',{plan:reviewPlan.name})}.</strong> {$t('Opening this link does not select a plan or take payment.')}</p>{/if}
      <div class="cards plans tiered-plans">
        {#each data.plans||[] as plan}
          <article class="panel" class:selected={selectedPlan?.id===plan.id} class:reviewing={reviewPlan?.id===plan.id}>
            <p class="plan-audience">{$t(plan.audience)}</p><div class="plan-title"><h3><bdi>{plan.name}</bdi></h3>{#if activePlan?.id===plan.id}<span class="plan-badge">{$t('Current plan')}</span>{:else if selectedPlan?.id===plan.id}<span class="plan-badge">{$t('Selected')}</span>{/if}</div>
            {#if reviewPlan?.id===plan.id}<p class="plan-badge">{$t('Review {plan}',{plan:plan.name})}</p>{/if}
            <strong class="price"><bdi>{money(discounted(plan.monthly_pence))}</bdi><small>{$t(data?.vat_percent ? 'per month before VAT' : 'per month')}</small></strong>
            <p class="tax-total">{$t(data?.vat_percent ? '{price} / month including {percent}% VAT' : '{price} / month — no VAT charged',{price:money(totalWithVat(plan.monthly_pence)),percent:count(data.vat_percent)})}</p>
            {#if activePlan && implementationPaid}<p class="setup-price">{$t('Setup paid.')}</p>{:else}<p class="setup-price">{$t(data?.vat_percent ? '{price} one-time setup before VAT' : '{price} one-time setup',{price:money(setupDiscounted(plan.setup_pence))})}<small class="tax-total">{$t(data?.vat_percent ? '{price} setup including {percent}% VAT' : '{price} setup — no VAT charged',{price:money(setupTotal(plan.setup_pence)),percent:count(data.vat_percent)})}</small></p>{/if}
            <ul class="plan-features"><li>{$t('Website and WhatsApp agents')}</li><li>{$t('No fixed message or conversation cap')}</li><li>{$t('AI processing paid separately with prepaid usage credit')}</li><li>{$t('{count} locations / service areas',{count:count(plan.locations)})}</li><li>{$t('{count} staff accounts, plus the owner',{count:count(plan.staff)})}</li><li>{$t('{analytics} analytics · {access} API access',{analytics:$t(plan.analytics),access:$t(plan.api_access)})}</li><li>{$t('{support} onboarding support',{support:$t(plan.onboarding)})}</li></ul>
            <button disabled={!canManageBilling||busy||checkoutPending||selectedPlan?.id===plan.id||(activePlan?!data.management?.can_change_plan:planLocked)} on:click={()=>action(activePlan?'change-plan':'select-plan',{plan_id:plan.id})}>{activePlan?.id===plan.id?$t('Current subscription'):activePlan?$t('Review {plan}',{plan:plan.name}):selectedPlan?.id===plan.id?$t('Selected'):$t('Choose {plan}',{plan:plan.name})}</button>
          </article>
        {/each}
      </div>
      <p class="notice">{$t('WhatsApp phone numbers are not included. Bring a suitable business number or obtain one from a provider. Number rental and Meta/provider messaging charges are paid separately and are not covered by V7 usage credit.')}</p>
      <p>{$t('Analytics and API labels describe plan service levels. Access to business data and tools still follows your account permissions.')}</p>
      {#if planLocked && !data.management?.can_change_plan}<p class="notice">{$t('Your plan is linked to its subscription or paid setup. Contact the platform administrator to arrange a plan change.')}</p>{/if}
      {#if checkoutPending}
        <div class="notice"><p>{$t('An unpaid checkout is open for {plan}. Continue with this plan below.',{plan:selectedPlan?.name||$t('your selected plan')})}{#if !planLocked} {$t('Cancel the pending checkout before choosing another plan.')}{/if}{#if data.plan_state?.checkout_expires} {$t('It expires {date} (UTC).',{date:dateTime(data.plan_state.checkout_expires)})}{/if}</p>{#if canManageBilling}<button disabled={busy||!data.configured} on:click={()=>action('cancel-checkout',{})}>{$t('Cancel pending checkout')}</button>{/if}</div>
      {/if}
      {#if selectedPlan}
        <div class="cards">
          <article class="panel"><h3>{$t('{plan} subscription',{plan:selectedPlan.name})}</h3><p>{$t(data?.vat_percent ? '{price} / month including {percent}% VAT' : '{price} / month — no VAT charged',{price:money(totalWithVat(selectedPlan.monthly_pence)),percent:count(data.vat_percent)})}</p><p>{$t('Status')}: <b>{status(baseContract?.status)}</b></p><p>{$t('Next payment')}: {baseContract?.cancel_at_end?$t('Renewal cancelled'):date(baseContract?.next_due)}</p>{#if !baseContract||['not_started','canceled','incomplete_expired'].includes(baseContract.status)}<button disabled={!canManageBilling||busy||!data.configured} on:click={()=>action('checkout',{kind:'platform',plan_id:selectedPlan?.id})}>{$t('Subscribe to {plan}',{plan:selectedPlan.name})}</button>{/if}</article>
          <article class="panel"><h3>{$t('One-time setup')}</h3><p>{$t(data?.vat_percent ? '{price} setup including {percent}% VAT' : '{price} setup — no VAT charged',{price:money(setupTotal(setupPlan?.setup_pence||selectedPlan.setup_pence)),percent:count(data.vat_percent)})}</p><p>{$t('Separate checkout and invoice; setup does not repeat with renewals.')}</p>{#if implementationPaid}<p><b>{$t('Setup paid.')}</b></p>{:else}<button disabled={!canManageBilling||busy||!data.configured} on:click={()=>action('checkout',{kind:'implementation',plan_id:setupPlan?.id||selectedPlan?.id})}>{$t('Pay {plan} setup',{plan:setupPlan?.name||selectedPlan.name})}</button>{/if}</article>
          <article class="panel"><h3>{$t('WhatsApp · included')}</h3><p>{$t('Website and WhatsApp AI replies share a separate prepaid usage-credit balance. Incoming message counts are activity records, not a separate message-count allowance.')}</p><p>{$t('Phone numbers and Meta/provider charges are not included. Connect your own provider and business number in the WhatsApp section.')}</p><p>{data.plan_state?.whatsapp_paused?$t('Paused by your business'):data.whatsapp_enabled?$t('Enabled'):$t('Available after activation')}</p><button disabled={!canManageBilling||busy||!activePlan} on:click={()=>action('whatsapp',{enabled:Boolean(data?.plan_state?.whatsapp_paused)})}>{data.plan_state?.whatsapp_paused?$t('Enable WhatsApp'):$t('Pause WhatsApp')}</button></article>
        </div>
      {:else}<p class="notice">{$t('Choose a plan to see its subscription and setup checkout. Selecting a plan does not take a payment.')}</p>{/if}
    {/if}
    {#if data.allowance}
      {@const website=data.allowance.website_conversations}
      <article class="panel usage-panel"><header><div><h2>{$t(website.enforced===false?'Monthly activity':'Monthly allowances')}</h2><p>{$t('{month} · resets at the start of the next calendar month in UTC.',{month:month(data.allowance.month)})}</p></div><span class="plan-badge">{$t(website.enforced===false?'Usage based on model and tokens':'Pause at the limit')}</span></header>
        {#each data.allowance.alerts||[] as alert}<p class="notice error usage-alert" role="alert">{usageAlert(alert)}</p>{/each}
        <div class="cards usage-cards">
          <div><h3>{$t('Website conversations')}</h3><p class="usage-total"><strong><bdi>{count(website.used)}</bdi></strong>{#if website.enforced!==false} / <bdi>{count(website.limit)}</bdi>{/if}</p>{#if website.enforced===false}<p>{$t('Distinct website conversations this month. Activity only — not a conversation allowance.')}</p>{:else}<progress value={website.used} max={Math.max(1,website.limit)} aria-label={$t('Website conversations used')}></progress><p>{website.paused?$t('New conversations paused; existing sessions can continue.'):$t('{count} remaining this month',{count:count(Math.max(0,website.limit-website.used))})}</p>{/if}</div>
          <div><h3>{$t('WhatsApp activity')}</h3><p class="usage-total"><strong><bdi>{count(data.allowance.whatsapp_messages.used)}</bdi></strong></p><p>{$t('Incoming customer messages this month. Activity only — not a message-count allowance.')}</p></div>
        </div>
        <p>{$t(website.enforced===false?'Website and WhatsApp activity counts do not limit messages. Paid AI uses prepaid credit according to the model and tokens consumed. Credit carries forward; there are no automatic extra charges.':'Website allowances count distinct chat sessions; new sessions pause at the limit while existing sessions continue. Paid AI replies use separate prepaid credit. Low or insufficient credit creates an administrator alert; saved-knowledge replies remain available. There are no automatic extra charges.')}</p>
      </article>
    {/if}
    {#if canManageBilling}{#key tenant}<ModelPicker {tenant} {csrf} {apiPrefix}/>{/key}{/if}
    {#if !data.internal || isPlatform}
      {#key tenant}<UsageCredits {tenant} {csrf} {apiPrefix} {canManageBilling} {canViewCosts} {isPlatform} canTopUp={Boolean(data.complimentary)||['active','trialing'].includes(baseContract?.status||'')} on:creditstatus={(event)=>dispatch('creditstatus',event.detail)} />{/key}
    {/if}
    {#if canViewIntegrations}
      <details class="panel" bind:open={whatsappOpen}>
        <summary>{$t('WhatsApp connection and Meta billing')}</summary>
        <p>{$t('Manage your number, webhook and provider setup here. AI credit pays for model tokens; Meta or Twilio bills messaging separately. V7 cannot collect or display your Meta payment details.')}</p>
        {#if whatsappOpen}{#key tenant}<WhatsAppConnection {tenant} {apiPrefix}/>{/key}{/if}
      </details>
    {/if}
    {#if legacyBilling}
    <p class="notice">{$t('Existing subscription pricing. Your recorded contract and invoices keep their original terms; the new plans do not automatically change them.')}</p>
    <div class="cards plans">
      <article class="panel"><h3>{$t('Platform subscription')}</h3><strong class="price"><bdi>{money(discounted(40000))}</bdi><small>{$t(data?.vat_percent ? 'per month before VAT' : 'per month')}</small></strong><p class="tax-total">{$t(data?.vat_percent ? '{price} / month including {percent}% VAT' : '{price} / month — no VAT charged',{price:money(totalWithVat(40000)),percent:count(data.vat_percent)})}</p><p>{$t('Your website sales agent and business workspace. This checkout charges only the monthly plan. Setup, optional WhatsApp and API usage are paid separately.')}</p><p>{$t('Status')}: {status(baseContract?.status)}</p><p>{$t('Next payment')}: {baseContract?.cancel_at_end?$t('Renewal cancelled'):date(baseContract?.next_due)}</p>{#if !baseContract||['not_started','canceled','incomplete_expired'].includes(baseContract.status)}<button disabled={!canManageBilling||busy||!data.configured} on:click={()=>action('checkout',{kind:'platform'})}>{$t(data?.vat_percent ? 'Subscribe · {price}/month including VAT' : 'Subscribe · {price}/month',{price:money(totalWithVat(40000))})}</button>{/if}</article>
      <article class="panel"><h3>{$t('Implementation')}</h3><strong class="price"><bdi>{money(setupDiscounted(20000))}</bdi><small>{$t(data?.vat_percent ? 'one time before VAT' : 'one time')}</small></strong><p class="tax-total">{$t(data?.vat_percent ? '{price} setup including {percent}% VAT' : '{price} setup — no VAT charged',{price:money(setupTotal(20000)),percent:count(data.vat_percent)})}</p><p>{$t('Initial business and agent setup. Paid once through its own checkout and invoice; never added to your monthly renewal.')}</p>{#if implementationPaid}<p><b>{$t('Paid — no further implementation payment needed.')}</b></p>{:else}<button disabled={!canManageBilling||busy||!data.configured} on:click={()=>action('checkout',{kind:'implementation'})}>{$t(data?.vat_percent ? 'Pay implementation · {price} including VAT' : 'Pay implementation · {price}',{price:money(setupTotal(20000))})}</button>{/if}</article>
      <article class="panel"><h3>{$t('WhatsApp add-on · optional')}</h3><strong class="price"><bdi>{money(20000)}</bdi><small>{$t(data?.vat_percent ? 'per month before VAT' : 'per month')}</small></strong><p class="tax-total">{$t(data?.vat_percent ? '{price} / month including {percent}% VAT' : '{price} / month — no VAT charged',{price:money(undiscountedTotal(20000)),percent:count(data.vat_percent)})}</p><p>{$t('Choose this only if you want your agent on WhatsApp. It has a separate subscription and requires a configured WhatsApp provider connection. Website chat works without it.')}</p><p>{$t('Phone numbers and Meta/provider charges are not included. Connect your own provider and business number in the WhatsApp section.')}</p><p>{waContract?(waContract.paused?$t('Deactivated'):status(waContract.status)):status(undefined)}</p><p>{$t(waContract?.cancel_at_end?'Paid-through date':'Next payment')}: {date(waContract?.next_due)}</p>
        {#if waContract&&['active','trialing'].includes(waContract.status)}<button disabled={!canManageBilling||busy||!data.configured} on:click={()=>action('whatsapp',{enabled:Boolean(waContract?.paused)})}>{waContract.paused?$t('Reactivate WhatsApp & renewals'):$t('Deactivate WhatsApp & stop renewals')}</button>
        {:else}<button disabled={!canManageBilling||busy||!data.configured||baseContract?.status!=='active'} on:click={()=>action('checkout',{kind:'whatsapp'})}>{$t(data.vat_percent ? 'Add WhatsApp · {price}/month including VAT' : 'Add WhatsApp · {price}/month',{price:money(undiscountedTotal(20000))})}</button>{#if baseContract?.status!=='active'}<p>{$t('Available after your platform subscription is active.')}</p>{/if}{/if}
        <p>{$t('Deactivation stops the bot immediately and ends renewals at the paid-through date. It does not automatically refund an existing invoice.')}</p>
      </article>
    </div>
    {/if}
    <div class="cards summaries"><article class="panel"><h3>{$t('Total paid')}</h3><strong class="price"><bdi>{money(data.totals.paid)}</bdi></strong><p>{$t('Recorded invoice payments, before refunds.')}</p></article><article class="panel"><h3>{$t('Total payment due')}</h3><strong class="price"><bdi>{money(data.totals.due+data.totals.approved_api_due)}</bdi></strong><p>{$t('Open invoices at their recorded totals.')}{#if canViewCosts} {$t('Approved API charges awaiting checkout: {price}.',{price:money(data.totals.approved_api_due)})}{/if}</p></article><article class="panel"><h3>{$t('Regular monthly price')}</h3><strong class="price">{data.complimentary?$t('Complimentary Scale'):data.internal?$t('Internal workspace'):baseContract?.status==='active'?money(totalWithVat(monthlyPrice)+(legacyBilling&&waContract?.status==='active'&&!waContract.paused?undiscountedTotal(20000):0)):status(undefined)}</strong><p>{$t(data?.vat_percent ? 'Including VAT and any saved subscription discount. Your Stripe checkout and invoices show the amount charged.' : 'Final price after any saved subscription discount. No VAT charged; your checkout and invoices show the amount payable.')}</p></article></div>
    {#if months.length}<TrendChart title={$t('Recorded payments by invoice month')} labels={months.map(month)} unit="GBP" series={[{name:$t('Paid'),values:paidMonths,color:'#087f5b'},{name:$t('Outstanding'),values:dueMonths,color:'#bd5b28'}]} {locale} notRecordedLabel={$t('Not recorded')} periodLabel={$t('Period (UTC)')} figuresLabel={$t('View figures')} exactValuesLabel={$t('Exact values in the table below')} figuresRegionLabel={$t('Recorded payment figures')}/>{/if}
    <article class="panel"><header><div><h2>{$t('Payment history')}</h2><p>{$t('Previous subscription, setup, WhatsApp and API invoices. Older platform invoices may include setup. Showing the latest 120 recorded invoices.')}</p></div><label>{$t('Show')}<select bind:value={invoiceKind} on:change={()=>invoicePage=1}><option value="all">{$t('All charges')}</option><option value="platform">{$t('Platform subscription')}</option><option value="implementation">{$t('Implementation')}</option><option value="whatsapp">WhatsApp</option>{#if canViewCosts}<option value="api">{$t('API usage')}</option>{/if}</select></label></header>
      <!-- svelte-ignore a11y_no_noninteractive_tabindex (Keyboard users need to scroll the table horizontally on small screens.) -->
      <div class="scroll" role="region" aria-label={$t('Payment history')} tabindex="0"><table><thead><tr><th>{$t('Month')}</th><th>{$t('Charge')}</th><th>{$t('Status')}</th><th>{$t('Invoice total')}</th><th>{$t('Paid')}</th><th>{$t('Remaining')}</th><th>{$t('Invoice')}</th></tr></thead><tbody>{#each invoices.slice((invoicePage-1)*12,invoicePage*12) as invoice}<tr><td>{month(invoice.month)}</td><td>{name(invoice.kind)}<details><summary>{$t('Invoice line items')}</summary>{#each invoice.lines as line}<p><bdi>{line.description}</bdi> · <bdi>{money(line.amount)}</bdi></p>{/each}</details></td><td><span class="invoice-status" class:paid={invoice.status==='paid'}>{status(invoice.status)}</span></td><td><bdi>{money(invoice.total)}</bdi></td><td><bdi>{money(invoice.paid)}</bdi></td><td><bdi>{money(invoice.remaining)}</bdi></td><td>{#if invoice.url}<a href={invoice.url} target="_blank" rel="noopener noreferrer">{$t(invoice.status==='open'?'Pay invoice':'View invoice')}</a>{:else}{$t('Pending')}{/if}</td></tr>{:else}<tr><td colspan="7">{$t('No invoices recorded yet. A checkout redirect alone does not mark an invoice as paid.')}</td></tr>{/each}</tbody></table></div>
      <div class="controls"><button disabled={invoicePage===1} on:click={()=>invoicePage--}>{$t('Previous invoices')}</button><span>{$t('Page {page}',{page:count(invoicePage)})}</span><button disabled={invoicePage*12>=invoices.length} on:click={()=>invoicePage++}>{$t('Next invoices')}</button></div>
    </article>
    {#if canViewCosts}<article class="panel"><h2>{$t('AI usage records')}</h2>{#if data.internal}<p>{$t('Recorded model usage for the internal agent. Provider funding and availability still apply.')}</p>{:else}<p>{$t('Paid AI processing uses separate prepaid credit for website and WhatsApp replies. When credit cannot cover a request, paid AI pauses; no extra charge is created automatically. Any older approved charges remain visible below.')}</p>{/if}<p>{$t('Usage estimates are not invoices. Estimates use recorded model usage and an exchange rate; missing usage is not treated as free.')}</p>
      <!-- svelte-ignore a11y_no_noninteractive_tabindex (Keyboard users need to scroll the table horizontally on small screens.) -->
      <div class="scroll" role="region" aria-label={$t('API usage charges')} tabindex="0"><table><thead><tr><th>{$t('Month')}</th><th>{$t('Recorded calls')}</th><th>{$t('Estimated cost')}</th><th>{$t('Approved before VAT')}</th><th>{$t('Payment')}</th></tr></thead><tbody>{#each [...new Set([...data.usage.map(row=>row.month),...data.approved_api_charges.map(row=>row.month)])].sort().reverse() as usageMonth}{@const usage=data.usage.find(row=>row.month===usageMonth)}{@const charge=data.approved_api_charges.find(row=>row.month===usageMonth)}{@const invoice=data.invoices.find(row=>row.month===usageMonth&&row.kind==='api')}<tr><td>{month(usageMonth)}</td><td>{usage?count(usage.calls):$t('Not recorded')}</td><td><bdi>{money(usage?.estimated_pence)}</bdi>{#if usage?.unpriced}<small>{$t('{count} unpriced calls',{count:count(usage.unpriced)})}</small>{/if}</td><td>{charge?money(charge.amount):$t('Not approved')}</td><td>{#if invoice}<span>{$t('{status} · {price} paid',{status:status(invoice.status),price:money(invoice.paid)})}</span>{:else if charge}<button disabled={!canManageBilling||busy||!data.configured} on:click={()=>action('checkout',{kind:'api',month:usageMonth})}>{$t('Pay API charge')}</button>{:else}{$t('Not invoiced')}{/if}</td></tr>{:else}<tr><td colspan="5">{$t('No API usage or approved charges recorded.')}</td></tr>{/each}</tbody></table></div>

    </article>{/if}
  {/if}
</section>
<style>
  .billing { display:grid; gap:20px; min-width:0; overflow-wrap:anywhere; color:var(--v7-ink,#172b26); }
  .panel { background:var(--v7-surface,#fff); border:1px solid var(--v7-line,#e1e7e4); border-radius:12px; padding:20px; min-width:0; }
  .cancellation { scroll-margin-top:24px; border-color:#e8cfca; }
  .cancellation-heading { display:flex; align-items:center; gap:12px; margin-bottom:16px; }
  .cancellation-heading h2 { margin-bottom:4px; }
  .cancellation-heading p { margin:0; }
  .cancellation-icon { display:grid; place-items:center; width:42px; height:42px; flex:none; border-radius:10px; color:#9b332b; background:#fff2f0; }
  .cancellation-icon svg { width:24px; height:24px; }
  .cancellation-plan { color:var(--v7-ink); }
  .cancel-button { margin-top:8px; border-color:#c58e85; color:#9b332b; }
  .cancel-button:hover:not(:disabled) { background:#fff2f0; border-color:#9b332b; }
  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr)); gap:16px; }
  header,.controls { display:flex; flex-wrap:wrap; align-items:end; justify-content:space-between; gap:14px; }
  header>div:first-child { flex:1 1 280px; min-width:0; }
  .controls { justify-content:start; margin-top:18px; }
  header>.controls { margin-top:0; }
  .controls label { flex:1 1 180px; }
  h2,h3 { margin:0 0 8px; letter-spacing:-.02em; }
  h2 { font-size:21px; }
  h3 { font-size:17px; }
  p { font-size:13px; color:var(--v7-muted,#64716d); line-height:1.65; margin:10px 0; }
  .price { display:block; font-size:30px; margin:16px 0 10px; letter-spacing:-.035em; font-variant-numeric:tabular-nums; }
  .price small { font-size:12px; font-weight:400; display:block; margin-top:6px; color:var(--v7-muted); letter-spacing:0; }
  .tax-total { display:block; margin:0 0 12px; font-size:13px; font-weight:600; color:var(--v7-ink); }
  .setup-price .tax-total { margin:5px 0 0; font-size:12px; font-weight:500; }
  button,input,select { font:inherit; font-size:13px; max-width:100%; box-sizing:border-box; }
  button { padding:10px 14px; border:1px solid var(--v7-control-line,#c5d1cb); border-radius:8px; background:var(--v7-surface,#fff); color:var(--v7-ink); font-weight:600; cursor:pointer; min-height:44px; }
  button:hover:not(:disabled) { background:var(--v7-soft,#edf6f1); border-color:var(--v7-accent,#087f5b); }
  button:disabled { opacity:.5; cursor:default; }
  label { display:grid; gap:7px; font-size:12px; font-weight:600; color:var(--v7-muted); min-width:0; }
  input,select { padding:10px 12px; border:1px solid var(--v7-control-line,#c5d1cb); border-radius:8px; min-width:0; min-height:44px; background:var(--v7-surface,#fff); color:var(--v7-ink); }
  .notice { margin:0; padding:14px 16px; background:var(--v7-soft,#edf6f1); border-radius:8px; border:1px solid var(--v7-line); }
  .loading { color:var(--v7-accent); }
  .error { background:#fff2f0; border-color:#f2d6d2; color:#9b332b; }
  .scroll { overflow-x:auto; max-width:100%; margin-top:18px; border:1px solid var(--v7-line); border-radius:8px; }
  table { width:100%; border-collapse:collapse; text-align:start; font-size:13px; }
  th,td { padding:12px; border-bottom:1px solid var(--v7-line); vertical-align:top; line-height:1.55; font-variant-numeric:tabular-nums; }
  thead th { background:var(--v7-canvas,#f5f7f7); color:var(--v7-muted); font-size:12px; font-weight:600; white-space:nowrap; }
  tbody tr:last-child td { border-bottom:0; }
  tbody tr:hover { background:var(--v7-canvas,#f5f7f7); }
  .invoice-status { display:inline-block; padding:4px 7px; border-radius:6px; background:var(--v7-canvas,#f5f7f7); color:var(--v7-muted); font-size:12px; font-weight:600; }
  .invoice-status.paid { background:var(--v7-soft,#edf6f1); color:var(--v7-accent); }
  td small { display:block; color:var(--v7-muted); font-size:12px; }
  td:has(details) { min-width:180px; }
  a { color:var(--v7-accent); }
  details { margin-top:8px; font-size:12px; }
  summary { min-height:44px; display:list-item; align-content:center; cursor:pointer; color:var(--v7-accent); }
  details.panel { margin-top:0; padding-block:12px; }
  details.panel form { display:flex; flex-wrap:wrap; align-items:end; gap:12px; padding-top:12px; }
  details.panel form label { flex:1 1 220px; max-width:400px; }
  .company-list { display:grid; gap:8px; margin-top:18px; }
  .company-list button { display:grid; grid-template-columns:minmax(0,1fr) auto minmax(0,1fr); align-items:center; gap:12px; padding:12px 14px; text-align:start; }
  .company-list button>span:last-child { text-align:end; }
  .company-list span { font-size:12px; color:var(--v7-muted); }
  .company-list button.chosen { background:var(--v7-soft,#edf6f1); border-color:var(--v7-accent); }
  .cards .panel { display:flex; flex-direction:column; align-items:flex-start; }
  .plans .panel:first-child { border-color:var(--v7-accent); }
  .tiered-plans .panel:first-child { border-color:var(--v7-line); }
  .tiered-plans .panel.selected { border-color:var(--v7-accent); background:var(--v7-soft,#edf6f1); }
  .tiered-plans .panel.reviewing { border-color:var(--v7-accent); box-shadow:0 0 0 2px var(--v7-soft,#edf6f1); }
  .plan-audience { margin:0 0 10px; font-size:12px; }
  .plan-title { display:flex; flex-wrap:wrap; align-items:center; gap:10px; }
  .plan-title h3 { font-size:21px; margin:0; }
  .plan-badge { display:inline-block; padding:5px 8px; border-radius:6px; background:var(--v7-soft,#edf6f1); color:var(--v7-accent,#087f5b); font-size:11px; font-weight:600; }
  .selected .plan-badge { background:var(--v7-surface,#fff); }
  .setup-price { margin-top:0; font-weight:600; }
  .plan-features { display:grid; gap:9px; list-style:none; padding:0; margin:15px 0 24px; font-size:12px; line-height:1.55; }
  .plan-features li::before { content:'✓'; color:var(--v7-accent,#087f5b); margin-inline-end:7px; }
  .usage-cards { margin-top:22px; gap:24px; }
  .usage-cards>div { min-width:0; }
  .usage-cards h3 { font-size:13px; }
  .usage-total { margin:10px 0; font-variant-numeric:tabular-nums; }
  .usage-total strong { font-size:23px; color:var(--v7-ink); }
  progress { width:100%; height:8px; accent-color:var(--v7-accent,#087f5b); }
  .usage-alert { margin-top:12px; }
  .company-alert { display:block; color:#9b332b; font-size:11px; font-weight:500; margin-top:6px; }
  .company-plan { display:block; color:var(--v7-accent); font-size:11px; font-weight:500; margin-top:6px; }
  .cards button { margin-top:auto; background:var(--v7-accent,#087f5b); border-color:var(--v7-accent,#087f5b); color:#fff; }
  .cards button:hover:not(:disabled) { background:var(--v7-accent-hover); }
  .summaries h3 { font-size:12px; font-weight:600; color:var(--v7-muted); }
  .summaries .price { margin:8px 0; font-size:28px; }
  .summaries p { font-size:12px; margin:4px 0 0; }
  :is(button,input,select,a,summary,.scroll):focus-visible { outline:3px solid var(--v7-accent,#087f5b); outline-offset:3px; }
  @media(max-width:700px) { .company-list button { grid-template-columns:minmax(0,1fr) auto; } .company-list button>span:last-child { grid-column:1 / -1; text-align:start; } }
  @media(max-width:600px) { .panel { padding:16px; } .controls label { width:100%; } header { align-items:start; } header>.controls { width:100%; } .price { font-size:27px; } }
</style>
