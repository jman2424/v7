<script lang="ts">
  import {onMount,onDestroy,createEventDispatcher} from 'svelte';
  import TrendChart from './TrendChart.svelte';
  export let tenant:string;
  export let csrf:string;
  export let isPlatform=false;
  export let apiPrefix='';
  type Contract={kind:string;status:string;next_due:number|null;paused:number;cancel_at_end:number;implementation_paid:number};
  type Invoice={id:string;kind:string;month:string;issued:number;due:number|null;total:number;paid:number;remaining:number;status:string;url:string|null;lines:{description:string;amount:number}[]};
  type Report={configured:boolean;vat_percent:number;contracts:Contract[];invoices:Invoice[];totals:{paid:number;due:number;approved_api_due:number};usage:{month:string;calls:number;unpriced:number;estimated_pence:number|null}[];approved_api_charges:{month:string;amount:number}[];whatsapp_enabled:boolean};
  type Company={key:string;name:string;contracts:Contract[];totals:{paid:number;due:number}};
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
  let apiMonth='';
  let apiAmount='';
  let controller:AbortController|undefined;
  const money=(pence:number|null|undefined)=>pence==null?'Not available':new Intl.NumberFormat('en-GB',{style:'currency',currency:'GBP'}).format(pence/100);
  const date=(value:number|null|undefined)=>value?new Date(value*1000).toLocaleDateString('en-GB'):'Not scheduled';
  const name=(kind:string)=>({platform:'Platform subscription',whatsapp:'WhatsApp add-on',api:'API usage',implementation:'Implementation'}[kind]||kind);
  $: baseContract=data?.contracts.find(row=>row.kind==='platform');
  $: implementationPaid=Boolean(baseContract?.implementation_paid||data?.contracts.some(row=>row.kind==='implementation'&&row.status==='paid'));
  $: waContract=data?.contracts.find(row=>row.kind==='whatsapp');
  $: invoices=data?.invoices.filter(row=>invoiceKind==='all'||row.kind===invoiceKind)||[];
  $: months=[...new Set(data?.invoices.map(row=>row.month)||[])].sort().slice(-12);
  $: paidMonths=months.map(month=>(data?.invoices.filter(row=>row.month===month).reduce((sum,row)=>sum+row.paid,0)||0)/100);
  $: dueMonths=months.map(month=>(data?.invoices.filter(row=>row.month===month&&row.status==='open').reduce((sum,row)=>sum+row.remaining,0)||0)/100);
  async function read(path:string, body?:Record<string,unknown>){
    const response=await fetch(apiPrefix+'/billing/'+path+(path.includes('?')?'&':'?')+'tenant='+encodeURIComponent(tenant),{credentials:'same-origin',signal:controller?.signal,...(body?{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(body)}:{})});
    const result=await response.json();
    if(!response.ok)throw new Error(String(result.error||'Billing request failed').replaceAll('_',' '));
    return result;
  }
  async function refresh(){busy=true;error='';controller?.abort();controller=new AbortController();const timeout=setTimeout(()=>controller?.abort(),25000);
    try{data=await read('subscription');if(isPlatform)await listCompanies();}catch(failure){error=failure instanceof Error?failure.message:'Billing unavailable';}finally{clearTimeout(timeout);busy=false;}}
  async function listCompanies(){try{const result=await read('companies?page='+page+'&search='+encodeURIComponent(search));companies=result.companies;companyCount=result.total;hasNext=result.has_next;}catch(failure){error=failure instanceof Error?failure.message:'Companies unavailable';}}
  async function action(path:string,body:Record<string,unknown>){busy=true;error='';message='';try{const result=await read(path,body);if(result.url){window.location.assign(result.url);return;}message='Saved. Payment status updates after Stripe confirms it.';await refresh();}catch(failure){error=failure instanceof Error?failure.message:'Update failed';}finally{busy=false;}}
  onMount(refresh);onDestroy(()=>controller?.abort());
</script>

<section class="billing" aria-label="Subscription and payments">
  {#if isPlatform}
  <article class="panel"><header><div><h2>All company subscriptions</h2><p>{companyCount} companies on your platform, including those without a subscription.</p></div></header>
    <form class="controls" on:submit|preventDefault={()=>{page=1;listCompanies();}}><label>Find a company<input bind:value={search} placeholder="Company name or key"/></label><button>Search</button></form>
    <div class="company-list">{#each companies as company}<button class:chosen={company.key===tenant} on:click={()=>dispatch('company',company.key)}><strong>{company.name} · {company.key}</strong><span>{company.contracts.find(row=>row.kind==='platform')?.status||'Not subscribed'}</span><span>{money(company.totals.due)} outstanding · {money(company.totals.paid)} paid</span></button>{/each}</div>
    <div class="controls"><button disabled={page===1||busy} on:click={()=>{page--;listCompanies();}}>Previous</button><span>Page {page}</span><button disabled={!hasNext||busy} on:click={()=>{page++;listCompanies();}}>Next</button></div>
  </article>
  {/if}
  <header><div><h2>{tenant} · subscription &amp; payments</h2><p>Prices in pounds. 20% VAT is added to the prices shown before VAT.</p></div><div class="controls">{#if baseContract && !['not_started','incomplete_expired'].includes(baseContract.status)}<button disabled={busy||!data?.configured} on:click={()=>action('portal',{})}>Manage payments in Stripe</button>{/if}<button disabled={busy} on:click={refresh}>Refresh payments</button></div></header>
  {#if error}<p class="notice error" role="alert">{error}</p>{/if}{#if message}<p class="notice" role="status">{message}</p>{/if}
  {#if busy}<p role="status">Updating billing…</p>{/if}
  {#if data}
    {#if !data.configured}<p class="notice">Stripe payments are not connected yet. {isPlatform?'Configure the Stripe API key, webhook signing secret and exclusive 20% VAT tax rate on the server.':'Your platform administrator needs to connect payments.'} No payment has been taken.</p>{/if}
    <div class="cards">
      <article class="panel"><h3>Platform subscription</h3><strong class="price">£400 <small>/ month before VAT</small></strong><p>£80 VAT · <b>£480/month total</b></p><p>Your website sales agent and business workspace. This checkout charges only the monthly plan. Implementation, optional WhatsApp and API usage are paid separately.</p><p>Status: {baseContract?.status||'Not subscribed'}</p><p>Next payment: {baseContract?.cancel_at_end?'Renewal cancelled':date(baseContract?.next_due)}</p>{#if !baseContract||['not_started','canceled','incomplete_expired'].includes(baseContract.status)}<button disabled={busy||!data.configured} on:click={()=>action('checkout',{kind:'platform'})}>Subscribe · £480/month inc. VAT</button>{/if}</article>
      <article class="panel"><h3>Implementation</h3><strong class="price">£200 <small>one time before VAT</small></strong><p>£40 VAT · <b>£240 total</b></p><p>Initial business and agent setup. Paid once through its own checkout and invoice; never added to your monthly renewal.</p>{#if implementationPaid}<p><b>Paid — no further implementation payment needed.</b></p>{:else}<button disabled={busy||!data.configured} on:click={()=>action('checkout',{kind:'implementation'})}>Pay implementation · £240 inc. VAT</button>{/if}</article>
      <article class="panel"><h3>WhatsApp add-on · optional</h3><strong class="price">£200 <small>/ month before VAT</small></strong><p>£40 VAT · <b>£240/month total</b></p><p>Choose this only if you want your agent on WhatsApp. It has a separate subscription and requires a configured WhatsApp provider connection. Website chat works without it.</p><p>{waContract?(waContract.paused?'Deactivated':waContract.status==='active'?'Active':'Payment pending'):'Not subscribed'}</p><p>{waContract?.cancel_at_end?'Paid-through date: ':'Next payment: '}{date(waContract?.next_due)}</p>
        {#if waContract&&['active','trialing'].includes(waContract.status)}<button disabled={busy||!data.configured} on:click={()=>action('whatsapp',{enabled:Boolean(waContract?.paused)})}>{waContract.paused?'Reactivate WhatsApp & renewals':'Deactivate WhatsApp & stop renewals'}</button>
        {:else}<button disabled={busy||!data.configured||baseContract?.status!=='active'} on:click={()=>action('checkout',{kind:'whatsapp'})}>Add WhatsApp · £240/month inc. VAT</button>{#if baseContract?.status!=='active'}<p>Available after your platform subscription is active.</p>{/if}{/if}
        <p>Deactivation stops the bot immediately and ends renewals at the paid-through date. It does not automatically refund an existing invoice.</p>
      </article>
    </div>
    <div class="cards"><article class="panel"><h3>Total paid</h3><strong class="price">{money(data.totals.paid)}</strong><p>Recorded invoice payments, before refunds.</p></article><article class="panel"><h3>Total payment due</h3><strong class="price">{money(data.totals.due+data.totals.approved_api_due)}</strong><p>Open Stripe invoices plus approved API charges awaiting checkout, including VAT. Approved API charges: {money(data.totals.approved_api_due)}.</p></article><article class="panel"><h3>Regular monthly price</h3><strong class="price">{baseContract?.status==='active'?money(48000+(waContract?.status==='active'&&!waContract.paused?24000:0)):'Not subscribed'}</strong><p>Including VAT; API charges are listed separately below.</p></article></div>
    {#if months.length}<TrendChart title="Recorded payments by invoice month" labels={months} unit="GBP" series={[{name:'Paid',values:paidMonths,color:'#008477'},{name:'Outstanding',values:dueMonths,color:'#bd5b28'}]}/>{/if}
    <article class="panel"><header><div><h2>Payment history</h2><p>Previous subscription, implementation, WhatsApp and API invoices. Older platform invoices may include implementation. Showing the latest 120 recorded invoices.</p></div><label>Show<select bind:value={invoiceKind} on:change={()=>invoicePage=1}><option value="all">All charges</option><option value="platform">Platform subscription</option><option value="implementation">Implementation</option><option value="whatsapp">WhatsApp</option><option value="api">API usage</option></select></label></header>
      <div class="scroll"><table><thead><tr><th>Month</th><th>Charge</th><th>Status</th><th>Total inc. VAT</th><th>Paid</th><th>Remaining</th><th>Invoice</th></tr></thead><tbody>{#each invoices.slice((invoicePage-1)*12,invoicePage*12) as invoice}<tr><td>{invoice.month}</td><td>{name(invoice.kind)}<details><summary>Line items before VAT</summary>{#each invoice.lines as line}<p>{line.description} · {money(line.amount)}</p>{/each}</details></td><td>{invoice.status}</td><td>{money(invoice.total)}</td><td>{money(invoice.paid)}</td><td>{money(invoice.remaining)}</td><td>{#if invoice.url}<a href={invoice.url} target="_blank" rel="noopener noreferrer">{invoice.status==='open'?'Pay invoice':'View invoice'}</a>{:else}Pending{/if}</td></tr>{:else}<tr><td colspan="7">No invoices recorded yet. A checkout redirect alone does not mark an invoice as paid.</td></tr>{/each}</tbody></table></div>
      <div class="controls"><button disabled={invoicePage===1} on:click={()=>invoicePage--}>Previous invoices</button><span>Page {invoicePage}</span><button disabled={invoicePage*12>=invoices.length} on:click={()=>invoicePage++}>Next invoices</button></div>
    </article>
    <article class="panel"><h2>API usage · billed separately</h2><p>AI API usage is not included in the £400 monthly plan, £200 implementation fee or optional WhatsApp subscription. Costs vary with your agent's model usage. Your platform administrator reviews each completed month and approves the charge before you pay it through a separate checkout and invoice, with VAT shown separately.</p><p>Usage estimates are not invoices. Estimates use recorded model usage and an exchange rate; missing usage is not treated as free.</p>
      <div class="scroll"><table><thead><tr><th>Month</th><th>Recorded calls</th><th>Estimated cost</th><th>Approved before VAT</th><th>Payment</th></tr></thead><tbody>{#each [...new Set([...data.usage.map(row=>row.month),...data.approved_api_charges.map(row=>row.month)])].sort().reverse() as month}{@const usage=data.usage.find(row=>row.month===month)}{@const charge=data.approved_api_charges.find(row=>row.month===month)}{@const invoice=data.invoices.find(row=>row.month===month&&row.kind==='api')}<tr><td>{month}</td><td>{usage?.calls??'Not recorded'}</td><td>{money(usage?.estimated_pence)}{#if usage?.unpriced}<small>{usage.unpriced} unpriced calls</small>{/if}</td><td>{charge?money(charge.amount):'Not approved'}</td><td>{#if invoice}<span>{invoice.status} · {money(invoice.paid)} paid</span>{:else if charge}<button disabled={busy||!data.configured} on:click={()=>action('checkout',{kind:'api',month})}>Pay API charge</button>{:else}Not invoiced{/if}</td></tr>{:else}<tr><td colspan="5">No API usage or approved charges recorded.</td></tr>{/each}</tbody></table></div>
      {#if isPlatform}<form class="controls" on:submit|preventDefault={()=>action('api-charge',{month:apiMonth,amount_pence:Math.round(Number(apiAmount)*100)})}><label>Completed usage month<input type="month" bind:value={apiMonth} required/></label><label>Approve charge before VAT (£)<input type="number" min="0.01" max="100000" step="0.01" bind:value={apiAmount} required/></label><button disabled={busy}>Approve monthly API charge</button><p>Review the provider bill first. Each month can be approved once.</p></form>{/if}
    </article>
  {/if}
</section>
<style>
 .billing{display:grid;gap:22px;min-width:0;overflow-wrap:anywhere}.panel{background:white;border:1px solid #d9ddd7;border-radius:10px;padding:24px;min-width:0}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr));gap:18px}header,.controls{display:flex;flex-wrap:wrap;align-items:end;justify-content:space-between;gap:16px}.controls{justify-content:start;margin-top:18px}h2,h3{margin:0 0 12px}h2{font-size:21px}h3{font-size:17px}p{font-size:14px;color:#526359;line-height:1.6;margin:12px 0}.price{display:block;font-size:30px;margin:18px 0}.price small{font-size:13px;font-weight:400;display:block;margin-top:8px}button,input,select{font:inherit;max-width:100%;box-sizing:border-box}button{padding:11px 15px;border:1px solid #adbbb1;border-radius:6px;background:white;color:#00796e;font-weight:600;cursor:pointer;min-height:44px}button:disabled{opacity:.5;cursor:default}label{display:grid;gap:8px;font-size:14px;min-width:0}input,select{padding:11px;border:1px solid #adbbb1;border-radius:6px;min-width:0}.notice{padding:18px;background:#eaf3ee;border-radius:8px}.error{background:#fff0ec;color:#9b332b}.scroll{overflow-x:auto;max-width:100%;margin-top:18px}table{width:100%;border-collapse:collapse;text-align:left;font-size:14px}th,td{padding:14px 12px;border-bottom:1px solid #dce3dc;vertical-align:top}th{color:#526359}td small{display:block}a{color:#00796e}details{margin-top:8px;font-size:12px}.company-list{display:grid;gap:10px;margin-top:18px}.company-list button{display:flex;flex-wrap:wrap;gap:12px;justify-content:space-between;text-align:left}.company-list span{font-size:13px}.chosen{background:#eaf3ee;border-color:#00796e}:is(button,input,select,a,summary):focus-visible{outline:3px solid #8bcdc0;outline-offset:3px}@media(max-width:600px){.panel{padding:16px}.controls label{width:100%}header{align-items:start}.price{font-size:26px}}
</style>
