<script lang="ts">
  import { t } from './i18n';
  import {onMount,onDestroy,createEventDispatcher} from 'svelte';
  import TrendChart from './TrendChart.svelte';
  export let tenant:string;
  export let csrf:string;
  export let isPlatform=false;
  export let canManageBilling=true;
  export let canViewCosts=true;
  export let apiPrefix='';
  type Contract={kind:string;status:string;next_due:number|null;paused:number;cancel_at_end:number;implementation_paid:number};
  type Invoice={id:string;kind:string;month:string;issued:number;due:number|null;total:number;paid:number;remaining:number;status:string;url:string|null;lines:{description:string;amount:number}[]};
  type Plan={id:string;name:string;audience:string;monthly_pence:number;setup_pence:number;website_conversations:number;whatsapp_messages:number;ai_budget_pence:number;locations:number;staff:number;analytics:string;api_access:string;onboarding:string};
  type UsageAlert={resource:string;message:string};
  type ChannelAllowance={used:number;limit:number;paused:boolean};
  type Allowance={month:string;mode:string;website_conversations:ChannelAllowance;whatsapp_messages:ChannelAllowance;ai_budget?:{used_pence:number|null;reserved_pence?:number;unknown_calls?:number;limit_pence:number;paused:boolean};alerts:UsageAlert[]};
  type PlanState={selected_plan:string|null;active_plan:string|null;setup_plan:string|null;whatsapp_paused:boolean;checkout_pending:boolean;checkout_expires:number|null};
  type Report={discount_percent:number;configured:boolean;vat_percent:number;contracts:Contract[];invoices:Invoice[];totals:{paid:number;due:number;approved_api_due:number};usage:{month:string;calls:number;unpriced:number;estimated_pence:number|null}[];approved_api_charges:{month:string;amount:number}[];whatsapp_enabled:boolean;plans?:Plan[];pricing_version?:string;internal?:boolean;plan_state?:PlanState|null;allowance?:Allowance|null};
  type Company={key:string;name:string;contracts:Contract[];totals:{paid:number;due:number};plan_state?:PlanState|null;allowance?:Allowance|null};
  const dispatch=createEventDispatcher<{company:string}>();
  let data:Report|null=null;
  let companies:Company[]=[];
  let companyCount=0;
  let page=1;
  let hasNext=false;
  let search='';
  let busy=false;
  let error='';
  let message='';
  let invoiceKind='all';
  let invoicePage=1;
  let discountCode='';
  let apiMonth='';
  let apiAmount='';
  let controller:AbortController|undefined;
  let companyController:AbortController|undefined;
  let companyBusy=false;
  let disposed=false;
  const money=(pence:number|null|undefined)=>pence==null?'Not available':new Intl.NumberFormat('en-GB',{style:'currency',currency:'GBP'}).format(pence/100);
  const date=(value:number|null|undefined)=>value?new Date(value*1000).toLocaleDateString('en-GB'):'Not scheduled';
  const name=(kind:string)=>({platform:'Platform subscription',whatsapp:'WhatsApp add-on',api:'API usage',implementation:'Implementation'}[kind]||kind);
  const count=(value:number)=>new Intl.NumberFormat('en-GB').format(value);
  const ratio=(used:number,limit:number)=>Math.min(100,limit>0?used/limit*100:0);
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
  $: monthlyPrice=activePlan?activePlan.monthly_pence:40000;
  $: discounted=(pence:number)=>pence*(1-(data?.discount_percent||0)/100);
  $: totalWithVat=(pence:number)=>discounted(pence)*(1+(data?.vat_percent||0)/100);
  $: invoices=data?.invoices.filter(row=>invoiceKind==='all'||row.kind===invoiceKind)||[];
  $: months=[...new Set(data?.invoices.map(row=>row.month)||[])].sort().slice(-12);
  $: paidMonths=months.map(month=>(data?.invoices.filter(row=>row.month===month).reduce((sum,row)=>sum+row.paid,0)||0)/100);
  $: dueMonths=months.map(month=>(data?.invoices.filter(row=>row.month===month&&row.status==='open').reduce((sum,row)=>sum+row.remaining,0)||0)/100);
  async function read(path:string, body?:Record<string,unknown>, signal?:AbortSignal){
    const response=await fetch(apiPrefix+'/billing/'+path+(path.includes('?')?'&':'?')+'tenant='+encodeURIComponent(tenant),{credentials:'same-origin',signal,...(body?{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(body)}:{})});
    const result=await response.json();
    if(!response.ok)throw new Error(String(result.error||'Billing request failed').replaceAll('_',' '));
    return result;
  }
  async function refresh(){
    controller?.abort();const request=new AbortController();controller=request;busy=true;error='';
    const timeout=setTimeout(()=>request.abort(),25000);
    try{
      const result=await read('subscription',undefined,request.signal);
      if(disposed||controller!==request||request.signal.aborted)return;
      data=result;if(isPlatform)void listCompanies();
    }catch(failure){if(!disposed&&controller===request)error=request.signal.aborted?'Billing loading timed out. Try refreshing.':failure instanceof Error?failure.message:'Billing unavailable';}
    finally{clearTimeout(timeout);if(!disposed&&controller===request){busy=false;controller=undefined;}}
  }
  async function listCompanies(){
    companyController?.abort();const request=new AbortController();companyController=request;companyBusy=true;
    const timeout=setTimeout(()=>request.abort(),25000);
    try{
      const result=await read('companies?page='+page+'&search='+encodeURIComponent(search),undefined,request.signal);
      if(disposed||companyController!==request||request.signal.aborted)return;
      companies=result.companies;companyCount=result.total;hasNext=result.has_next;
    }catch(failure){if(!disposed&&companyController===request)error=request.signal.aborted?'Company loading timed out. Try searching again.':failure instanceof Error?failure.message:'Companies unavailable';}
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
    }catch(failure){if(!disposed&&controller===request)error=request.signal.aborted?'The billing update could not be confirmed. Refresh payments before trying again.':failure instanceof Error?failure.message:'Update failed';}
    finally{clearTimeout(timeout);if(!disposed&&controller===request){busy=false;controller=undefined;}}
  }
  onMount(refresh);onDestroy(()=>{disposed=true;controller?.abort();companyController?.abort();});
</script>

<section class="billing" aria-label="Subscription and payments">
  {#if isPlatform}
  <article class="panel"><header><div><h2>All company subscriptions</h2><p>{companyCount} companies on your platform, including those without a subscription.</p></div></header>
    <form class="controls" on:submit|preventDefault={()=>{page=1;listCompanies();}}><label>Find a company<input bind:value={search} placeholder="Company name or key"/></label><button disabled={busy||companyBusy}>{$t("Search")}</button></form>
    <div class="company-list">{#each companies as company}{@const alerts=company.allowance?.alerts||[]}{@const companyPlan=data?.plans?.find(plan=>plan.id===company.plan_state?.active_plan)}<button class:chosen={company.key===tenant} on:click={()=>dispatch('company',company.key)}><strong>{company.name} · {company.key}{#if companyPlan}<small class="company-plan">{companyPlan.name} plan</small>{/if}{#if alerts.length}<small class="company-alert">{alerts.length} usage alert{alerts.length===1?'':'s'} · {alerts[0].message}</small>{/if}</strong><span>{company.contracts.find(row=>row.kind==='platform')?.status||'Not subscribed'}</span><span>{money(company.totals.due)} outstanding · {money(company.totals.paid)} paid</span></button>{/each}</div>
    {#if companyBusy}<p role="status">Loading companies…</p>{/if}
    <div class="controls"><button disabled={page===1||busy||companyBusy} on:click={()=>{page--;listCompanies();}}>Previous</button><span>Page {page}</span><button disabled={!hasNext||busy||companyBusy} on:click={()=>{page++;listCompanies();}}>Next</button></div>
  </article>
  {/if}
  <header><div><h2>{tenant} · subscription &amp; payments</h2><p>Monthly billing in pounds, with a separate one-time setup. VAT is shown before payment.</p></div><div class="controls">{#if canManageBilling && baseContract && !['not_started','incomplete_expired'].includes(baseContract.status)}<button disabled={busy||!data?.configured} on:click={()=>action('portal',{})}>Manage payments in Stripe</button>{/if}<button disabled={busy} on:click={refresh}>Refresh payments</button></div></header>
  {#if error}<p class="notice error" role="alert">{error}</p>{/if}{#if message}<p class="notice" role="status">{message}</p>{/if}
  {#if busy}<p class="notice loading" role="status">Updating billing…</p>{/if}
  {#if data}
    {#if !canManageBilling}<p class="notice">Read-only access. Your business owner manages payments and subscriptions.</p>{/if}
    {#if !data.configured && !data.internal}<p class="notice">Stripe payments are not connected yet. {isPlatform?'Configure the Stripe API key, webhook signing secret and exclusive 20% VAT tax rate on the server.':'Your platform administrator needs to connect payments.'} No payment has been taken.</p>{/if}
    {#if data.internal}<p class="notice">Internal website agent. This platform-owned workspace does not need a customer subscription.</p>{/if}
    {#if canManageBilling && !data.internal}
      {#if data.discount_percent}<p class="notice">{data.discount_percent}% discount saved. Platform renewals keep this discount automatically; it also applies to your implementation checkout. No need to enter the code again.</p>
      {:else}<details class="panel"><summary>Have a discount code?</summary><form on:submit|preventDefault={()=>action('discount',{code:discountCode})}><label>Discount code<input bind:value={discountCode} maxlength="100" autocomplete="off" spellcheck="false" required /></label><button disabled={busy||!discountCode.trim()}>Apply to this business</button></form></details>{/if}
    {/if}
    {#if !legacyBilling && !data.internal}
      <div class="cards plans tiered-plans">
        {#each data.plans||[] as plan}
          <article class="panel" class:selected={selectedPlan?.id===plan.id}>
            <p class="plan-audience">{plan.audience}</p><div class="plan-title"><h3>{plan.name}</h3>{#if activePlan?.id===plan.id}<span class="plan-badge">Current plan</span>{:else if selectedPlan?.id===plan.id}<span class="plan-badge">Selected</span>{/if}</div>
            <strong class="price">{money(discounted(plan.monthly_pence))}<small>per month before VAT</small></strong>
            <p class="setup-price">{money(discounted(plan.setup_pence))} one-time setup</p>
            <ul class="plan-features"><li>Website and WhatsApp agents</li><li>{count(plan.website_conversations)} website conversations / month</li><li>{count(plan.whatsapp_messages)} WhatsApp messages / month</li><li>{money(plan.ai_budget_pence)} AI API-cost budget / month</li><li>{plan.locations} location{plan.locations===1?'':'s'} / service area{plan.locations===1?'':'s'}</li><li>{plan.staff} staff accounts, plus the owner</li><li>{plan.analytics} analytics · {plan.api_access} API access</li><li>{plan.onboarding} onboarding support</li></ul>
            <button disabled={!canManageBilling||busy||planLocked||checkoutPending||selectedPlan?.id===plan.id} on:click={()=>action('select-plan',{plan_id:plan.id})}>{activePlan?.id===plan.id?'Current subscription':selectedPlan?.id===plan.id?'Selected':'Choose '+plan.name}</button>
          </article>
        {/each}
      </div>
      <p>Analytics and API labels describe plan service levels. Access to business data and tools still follows your account permissions.</p>
      {#if planLocked}<p class="notice">Your plan is linked to its subscription or paid setup. Contact the platform administrator to arrange a plan change.</p>{/if}
      {#if checkoutPending}
        <div class="notice"><p>An unpaid checkout is open for {selectedPlan?.name||'your selected plan'}. Continue with this plan below{#if !planLocked}, or cancel the pending checkout before choosing another plan{/if}.{#if data.plan_state?.checkout_expires} It expires {new Date(data.plan_state.checkout_expires*1000).toLocaleString('en-GB')}.{/if}</p>{#if canManageBilling}<button disabled={busy||!data.configured} on:click={()=>action('cancel-checkout',{})}>Cancel pending checkout</button>{/if}</div>
      {/if}
      {#if selectedPlan}
        <div class="cards">
          <article class="panel"><h3>{selectedPlan.name} subscription</h3><p>{money(totalWithVat(selectedPlan.monthly_pence))}/month including {data.vat_percent}% VAT.</p><p>Status: <b>{baseContract?.status||'Not subscribed'}</b></p><p>Next payment: {baseContract?.cancel_at_end?'Renewal cancelled':date(baseContract?.next_due)}</p>{#if !baseContract||['not_started','canceled','incomplete_expired'].includes(baseContract.status)}<button disabled={!canManageBilling||busy||!data.configured} on:click={()=>action('checkout',{kind:'platform',plan_id:selectedPlan?.id})}>Subscribe to {selectedPlan.name}</button>{/if}</article>
          <article class="panel"><h3>One-time setup</h3><p>{money(totalWithVat(setupPlan?.setup_pence||selectedPlan.setup_pence))} including {data.vat_percent}% VAT. Separate checkout and invoice; setup does not repeat with renewals.</p>{#if implementationPaid}<p><b>Setup paid.</b></p>{:else}<button disabled={!canManageBilling||busy||!data.configured} on:click={()=>action('checkout',{kind:'implementation',plan_id:setupPlan?.id||selectedPlan?.id})}>Pay {setupPlan?.name||selectedPlan.name} setup</button>{/if}</article>
          <article class="panel"><h3>WhatsApp · included</h3><p>{count((activePlan||selectedPlan).whatsapp_messages)} incoming customer messages per calendar month. Connect your provider in the WhatsApp section; provider charges, if any, are separate.</p><p>{data.plan_state?.whatsapp_paused?'Paused by your business':data.whatsapp_enabled?'Enabled':'Available after activation'}</p><button disabled={!canManageBilling||busy||!activePlan} on:click={()=>action('whatsapp',{enabled:Boolean(data?.plan_state?.whatsapp_paused)})}>{data.plan_state?.whatsapp_paused?'Enable WhatsApp':'Pause WhatsApp'}</button></article>
        </div>
      {:else}<p class="notice">Choose a plan to see its subscription and setup checkout. Selecting a plan does not take a payment.</p>{/if}
    {/if}
    {#if data.allowance}
      <article class="panel usage-panel"><header><div><h2>Monthly allowances</h2><p>{data.allowance.month} · resets at the start of the next calendar month in UTC.</p></div><span class="plan-badge">Pause at the limit</span></header>
        {#each data.allowance.alerts||[] as alert}<p class="notice error usage-alert" role="alert">{alert.message}</p>{/each}
        <div class="cards usage-cards">
          {#each [{label:'Website conversations',allowance:data.allowance.website_conversations},{label:'WhatsApp messages',allowance:data.allowance.whatsapp_messages}] as resource}
            <div><h3>{resource.label}</h3><p class="usage-total"><strong>{count(resource.allowance.used)}</strong> / {count(resource.allowance.limit)}</p><progress value={resource.allowance.used} max={Math.max(1,resource.allowance.limit)} aria-label={resource.label+' used'}></progress><p>{resource.allowance.paused?(resource.label==='Website conversations'?'New conversations paused; existing sessions can continue.':'Paused — monthly allowance reached'):Math.max(0,resource.allowance.limit-resource.allowance.used)+' remaining this month'}</p></div>
          {/each}
          {#if canViewCosts && data.allowance.ai_budget}{@const budget=data.allowance.ai_budget}<div><h3>AI API-cost budget</h3><p class="usage-total"><strong>{money(budget.used_pence)}</strong> / {money(budget.limit_pence)}</p><progress value={ratio((budget.used_pence||0)+(budget.reserved_pence||0),budget.limit_pence)} max="100" aria-label="Estimated AI budget used or reserved"></progress>{#if budget.reserved_pence}<p>{money(budget.reserved_pence)} reserved for calls awaiting a confirmed cost.</p>{/if}<p>{budget.paused?'Paid AI calls paused; see the alert above. Saved knowledge remains available.':'Estimated recorded cost. Provider availability still applies.'}</p></div>{/if}
        </div>
        <p>Website allowances count distinct chat sessions used in the month; at the limit new sessions pause while existing sessions can continue. WhatsApp allowances count incoming customer messages. Pauses create an administrator alert. No top-ups or automatic extra charges are enabled.</p>
      </article>
    {/if}
    {#if legacyBilling}
    <p class="notice">Existing subscription pricing. Your recorded contract and invoices keep their original terms; the new plans do not automatically change them.</p>
    <div class="cards plans">
      <article class="panel"><h3>Platform subscription</h3><strong class="price">{money(40000*(1-data.discount_percent/100))} <small>/ month before VAT</small></strong><p>{money(8000*(1-data.discount_percent/100))} VAT · <b>{money(48000*(1-data.discount_percent/100))}/month total</b></p><p>Your website sales agent and business workspace. This checkout charges only the monthly plan. Implementation, optional WhatsApp and API usage are paid separately.</p><p>Status: {baseContract?.status||'Not subscribed'}</p><p>Next payment: {baseContract?.cancel_at_end?'Renewal cancelled':date(baseContract?.next_due)}</p>{#if !baseContract||['not_started','canceled','incomplete_expired'].includes(baseContract.status)}<button disabled={!canManageBilling||busy||!data.configured} on:click={()=>action('checkout',{kind:'platform'})}>Subscribe · {money(48000*(1-data.discount_percent/100))}/month inc. VAT</button>{/if}</article>
      <article class="panel"><h3>{$t("Implementation")}</h3><strong class="price">{money(20000*(1-data.discount_percent/100))} <small>one time before VAT</small></strong><p>{money(4000*(1-data.discount_percent/100))} VAT · <b>{money(24000*(1-data.discount_percent/100))} total</b></p><p>Initial business and agent setup. Paid once through its own checkout and invoice; never added to your monthly renewal.</p>{#if implementationPaid}<p><b>Paid — no further implementation payment needed.</b></p>{:else}<button disabled={!canManageBilling||busy||!data.configured} on:click={()=>action('checkout',{kind:'implementation'})}>Pay implementation · {money(24000*(1-data.discount_percent/100))} inc. VAT</button>{/if}</article>
      <article class="panel"><h3>WhatsApp add-on · optional</h3><strong class="price">£200 <small>/ month before VAT</small></strong><p>£40 VAT · <b>£240/month total</b></p><p>Choose this only if you want your agent on WhatsApp. It has a separate subscription and requires a configured WhatsApp provider connection. Website chat works without it.</p><p>{waContract?(waContract.paused?'Deactivated':waContract.status==='active'?'Active':'Payment pending'):'Not subscribed'}</p><p>{waContract?.cancel_at_end?'Paid-through date: ':'Next payment: '}{date(waContract?.next_due)}</p>
        {#if waContract&&['active','trialing'].includes(waContract.status)}<button disabled={!canManageBilling||busy||!data.configured} on:click={()=>action('whatsapp',{enabled:Boolean(waContract?.paused)})}>{waContract.paused?'Reactivate WhatsApp & renewals':'Deactivate WhatsApp & stop renewals'}</button>
        {:else}<button disabled={!canManageBilling||busy||!data.configured||baseContract?.status!=='active'} on:click={()=>action('checkout',{kind:'whatsapp'})}>Add WhatsApp · £240/month inc. VAT</button>{#if baseContract?.status!=='active'}<p>Available after your platform subscription is active.</p>{/if}{/if}
        <p>Deactivation stops the bot immediately and ends renewals at the paid-through date. It does not automatically refund an existing invoice.</p>
      </article>
    </div>
    {/if}
    <div class="cards summaries"><article class="panel"><h3>Total paid</h3><strong class="price">{money(data.totals.paid)}</strong><p>Recorded invoice payments, before refunds.</p></article><article class="panel"><h3>Total payment due</h3><strong class="price">{money(data.totals.due+data.totals.approved_api_due)}</strong><p>Open invoices including VAT.{#if canViewCosts} Approved API charges awaiting checkout: {money(data.totals.approved_api_due)}.{/if}</p></article><article class="panel"><h3>Regular monthly price</h3><strong class="price">{data.internal?'Internal workspace':baseContract?.status==='active'?money(totalWithVat(monthlyPrice)+(legacyBilling&&waContract?.status==='active'&&!waContract.paused?24000:0)):'Not subscribed'}</strong><p>Including VAT and any saved subscription discount. Your Stripe checkout and invoices show the amount charged.</p></article></div>
    {#if months.length}<TrendChart title="Recorded payments by invoice month" labels={months} unit="GBP" series={[{name:'Paid',values:paidMonths,color:'#087f5b'},{name:'Outstanding',values:dueMonths,color:'#bd5b28'}]}/>{/if}
    <article class="panel"><header><div><h2>Payment history</h2><p>Previous subscription, implementation, WhatsApp and API invoices. Older platform invoices may include implementation. Showing the latest 120 recorded invoices.</p></div><label>Show<select bind:value={invoiceKind} on:change={()=>invoicePage=1}><option value="all">All charges</option><option value="platform">Platform subscription</option><option value="implementation">{$t("Implementation")}</option><option value="whatsapp">WhatsApp</option>{#if canViewCosts}<option value="api">API usage</option>{/if}</select></label></header>
      <!-- svelte-ignore a11y_no_noninteractive_tabindex (Keyboard users need to scroll the table horizontally on small screens.) -->
      <div class="scroll" role="region" aria-label="Payment history" tabindex="0"><table><thead><tr><th>Month</th><th>Charge</th><th>Status</th><th>Total inc. VAT</th><th>Paid</th><th>Remaining</th><th>Invoice</th></tr></thead><tbody>{#each invoices.slice((invoicePage-1)*12,invoicePage*12) as invoice}<tr><td>{invoice.month}</td><td>{name(invoice.kind)}<details><summary>Line items before VAT</summary>{#each invoice.lines as line}<p>{line.description} · {money(line.amount)}</p>{/each}</details></td><td><span class="invoice-status" class:paid={invoice.status==='paid'}>{invoice.status}</span></td><td>{money(invoice.total)}</td><td>{money(invoice.paid)}</td><td>{money(invoice.remaining)}</td><td>{#if invoice.url}<a href={invoice.url} target="_blank" rel="noopener noreferrer">{invoice.status==='open'?'Pay invoice':'View invoice'}</a>{:else}Pending{/if}</td></tr>{:else}<tr><td colspan="7">No invoices recorded yet. A checkout redirect alone does not mark an invoice as paid.</td></tr>{/each}</tbody></table></div>
      <div class="controls"><button disabled={invoicePage===1} on:click={()=>invoicePage--}>Previous invoices</button><span>Page {invoicePage}</span><button disabled={invoicePage*12>=invoices.length} on:click={()=>invoicePage++}>Next invoices</button></div>
    </article>
    {#if canViewCosts}<article class="panel"><h2>{legacyBilling?'API usage · existing billing terms':'AI usage records'}</h2>{#if legacyBilling}<p>AI API usage under the existing subscription is billed separately. Your platform administrator reviews each completed month and approves the charge before a separate checkout and invoice.</p>{:else if data.internal}<p>Recorded model usage for the internal agent. Provider funding and availability still apply.</p>{:else}<p>Your plan includes an AI API-cost budget. Paid AI calls pause when that budget is reached; no extra usage charge is created automatically. Any older approved charges remain visible below.</p>{/if}<p>Usage estimates are not invoices. Estimates use recorded model usage and an exchange rate; missing usage is not treated as free.</p>
      <!-- svelte-ignore a11y_no_noninteractive_tabindex (Keyboard users need to scroll the table horizontally on small screens.) -->
      <div class="scroll" role="region" aria-label="API usage charges" tabindex="0"><table><thead><tr><th>Month</th><th>Recorded calls</th><th>Estimated cost</th><th>Approved before VAT</th><th>Payment</th></tr></thead><tbody>{#each [...new Set([...data.usage.map(row=>row.month),...data.approved_api_charges.map(row=>row.month)])].sort().reverse() as month}{@const usage=data.usage.find(row=>row.month===month)}{@const charge=data.approved_api_charges.find(row=>row.month===month)}{@const invoice=data.invoices.find(row=>row.month===month&&row.kind==='api')}<tr><td>{month}</td><td>{usage?.calls??'Not recorded'}</td><td>{money(usage?.estimated_pence)}{#if usage?.unpriced}<small>{usage.unpriced} unpriced calls</small>{/if}</td><td>{charge?money(charge.amount):'Not approved'}</td><td>{#if invoice}<span>{invoice.status} · {money(invoice.paid)} paid</span>{:else if charge}<button disabled={!canManageBilling||busy||!data.configured} on:click={()=>action('checkout',{kind:'api',month})}>Pay API charge</button>{:else}Not invoiced{/if}</td></tr>{:else}<tr><td colspan="5">No API usage or approved charges recorded.</td></tr>{/each}</tbody></table></div>
      {#if isPlatform && legacyBilling}<form class="controls" on:submit|preventDefault={()=>action('api-charge',{month:apiMonth,amount_pence:Math.round(Number(apiAmount)*100)})}><label>Completed usage month<input type="month" bind:value={apiMonth} required/></label><label>Approve charge before VAT (£)<input type="number" min="0.01" max="100000" step="0.01" bind:value={apiAmount} required/></label><button disabled={busy}>Approve monthly API charge</button><p>Review the provider bill first. Each month can be approved once.</p></form>{/if}
    </article>{/if}
  {/if}
</section>
<style>
  .billing { display:grid; gap:20px; min-width:0; overflow-wrap:anywhere; color:var(--v7-ink,#172b26); }
  .panel { background:var(--v7-surface,#fff); border:1px solid var(--v7-line,#e1e7e4); border-radius:12px; padding:20px; min-width:0; }
  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr)); gap:16px; }
  header,.controls { display:flex; flex-wrap:wrap; align-items:end; justify-content:space-between; gap:14px; }
  header>div:first-child { flex:1 1 280px; min-width:0; }
  .controls { justify-content:start; margin-top:18px; }
  header>.controls { margin-top:0; }
  .controls label { flex:1 1 180px; }
  .controls>p { flex-basis:100%; margin:0; font-size:12px; }
  h2,h3 { margin:0 0 8px; letter-spacing:-.02em; }
  h2 { font-size:21px; }
  h3 { font-size:17px; }
  p { font-size:13px; color:var(--v7-muted,#64716d); line-height:1.65; margin:10px 0; }
  .price { display:block; font-size:30px; margin:16px 0 10px; letter-spacing:-.035em; font-variant-numeric:tabular-nums; }
  .price small { font-size:12px; font-weight:400; display:block; margin-top:6px; color:var(--v7-muted); letter-spacing:0; }
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
  table { width:100%; border-collapse:collapse; text-align:left; font-size:13px; }
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
  .company-list button { display:grid; grid-template-columns:minmax(0,1fr) auto minmax(0,1fr); align-items:center; gap:12px; padding:12px 14px; text-align:left; }
  .company-list button>span:last-child { text-align:right; }
  .company-list span { font-size:12px; color:var(--v7-muted); }
  .company-list button.chosen { background:var(--v7-soft,#edf6f1); border-color:var(--v7-accent); }
  .cards .panel { display:flex; flex-direction:column; align-items:flex-start; }
  .plans .panel:first-child { border-color:var(--v7-accent); }
  .tiered-plans .panel:first-child { border-color:var(--v7-line); }
  .tiered-plans .panel.selected { border-color:var(--v7-accent); background:var(--v7-soft,#edf6f1); }
  .plan-audience { margin:0 0 10px; font-size:12px; }
  .plan-title { display:flex; flex-wrap:wrap; align-items:center; gap:10px; }
  .plan-title h3 { font-size:21px; margin:0; }
  .plan-badge { display:inline-block; padding:5px 8px; border-radius:6px; background:var(--v7-soft,#edf6f1); color:var(--v7-accent,#087f5b); font-size:11px; font-weight:600; }
  .selected .plan-badge { background:var(--v7-surface,#fff); }
  .setup-price { margin-top:0; font-weight:600; }
  .plan-features { display:grid; gap:9px; list-style:none; padding:0; margin:15px 0 24px; font-size:12px; line-height:1.55; }
  .plan-features li::before { content:'✓'; color:var(--v7-accent,#087f5b); margin-right:7px; }
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
  @media(max-width:700px) { .company-list button { grid-template-columns:minmax(0,1fr) auto; } .company-list button>span:last-child { grid-column:1 / -1; text-align:left; } }
  @media(max-width:600px) { .panel { padding:16px; } .controls label { width:100%; } header { align-items:start; } header>.controls { width:100%; } .price { font-size:27px; } }
</style>
