<script lang="ts">
  import {onMount, onDestroy, createEventDispatcher} from 'svelte';
  import {t, language} from './i18n';
  import {subscriptionLocales, subscriptionCreditAlerts} from './subscription-format';
  export let tenant: string;
  export let csrf: string;
  export let apiPrefix = '';
  export let canViewCosts = true;
  export let canManageBilling = false;
  export let canTopUp = false;
  export let isPlatform = false;
  type Pack = {id:string;credit_pence:number;subtotal_pence:number;tax_pence:number;total_pence:number;currency:string;vat_percent:number};
  type ModelRates = {input?:number;cached?:number;cache_write?:number;output?:number;audio_second?:number};
  type ModelUsage = {model?:string;purpose?:string;channel?:string;input_tokens?:number;cached_tokens?:number;cache_write_tokens?:number;output_tokens?:number;audio_seconds?:number;price_version?:string;provider_cost_usd?:number|string;fx_rate?:number|string;fx_date?:string;markup_percent?:number|string;rate_snapshot?:ModelRates;model_rate?:ModelRates};
  type Transaction = {id:string;kind:string;created_utc:number|string;amount_pence:number;balance_delta_pence:number;reserved_delta_pence?:number;debt_delta_pence?:number;payment_ref?:string;invoice_id?:string;receipt_url?:string;usage?:ModelUsage|null};
  type Wallet = {balance_pence?:number;available_pence?:number;reserved_pence?:number;debt_pence?:number;spent_pence?:number;unknown_reservations?:number;reconciliation_hold?:boolean;paused:boolean;alerts:{code:string;message:string}[];markup_percent?:number|string|null;exchange_rate?:{rate:number|string;date:string;stale?:boolean}|null;transactions?:Transaction[];total?:number;offset?:number;limit?:number;has_next?:boolean};
  type PendingCheckout = {reference:string;request_id:string;pack_id:string;status:string;expires_at?:number;credit_pence:number;total_pence:number};
  type UsageReport = {tenant:string;internal?:boolean;configured:boolean;packs:Pack[];vat_percent:number;currency:string;wallet:Wallet;pending_checkouts?:PendingCheckout[];checkout_requests?:PendingCheckout[];policy:{mode:string;included_credit_pence:number;automatic_recharge:boolean}};
  type Company = {key:string;name:string;wallet:Wallet;internal?:boolean};
  const dispatch=createEventDispatcher<{creditstatus:{tenant:string;alerts:{code:string;message:string}[]}}>();
  let data: UsageReport|null = null;
  let busy = false;
  let error = '';
  let message = '';
  let page = 1;
  let selectedPack = '';
  let controller: AbortController|undefined;
  let disposed = false;
  let companies: Company[] = [];
  let companyPage = 1;
  let companyTotal = 0;
  let companyHasNext = false;
  let companySearch = '';
  let companyBusy = false;
  let companyController: AbortController|undefined;
  const checkoutRequests = new Map<string,string>();
  let adjustmentAmount = '';
  let adjustmentReason = '';
  let adjustmentConfirmed = false;
  let adjustmentRequest = '';
  $: locale = subscriptionLocales[$language];
  $: money = (value:number|undefined) => value==null ? $t('Not available') : new Intl.NumberFormat(locale,{style:'currency',currency:'GBP',minimumFractionDigits:2,maximumFractionDigits:9}).format(value/100);
  $: count = (value:number|undefined) => value==null ? $t('Not recorded') : new Intl.NumberFormat(locale).format(value);
  $: timestamp = (value:number|string) => new Intl.DateTimeFormat(locale,{dateStyle:'medium',timeStyle:'short',timeZone:'UTC'}).format(new Date(typeof value==='number'?value*1000:value));
  $: markup = (value:number|string|null|undefined) => value==null ? $t('Not recorded') : new Intl.NumberFormat(locale,{maximumFractionDigits:4}).format(Number(value));
  $: rate = (value:number|string|undefined) => value==null ? $t('Not recorded') : new Intl.NumberFormat(locale,{maximumFractionDigits:9}).format(Number(value));
  $: fxDate = (value:string) => new Intl.DateTimeFormat(locale,{dateStyle:'medium',timeZone:'UTC'}).format(new Date(value.length===10?value+'T00:00:00Z':value));
  $: pack = data?.packs.find(row=>row.id===selectedPack);
  $: transactions = data?.wallet.transactions||[];
  $: alerts = subscriptionCreditAlerts(data?.internal?[]:data?.wallet.alerts||[]);
  $: kind = (value:string) => $t(({topup:'Credit purchase',credit:'Credit purchase',usage:'AI usage charge',usage_unknown:'Unconfirmed usage',usage_overrun:'Usage adjustment',debit:'AI usage charge',refund:'Refund',refund_restored:'Refund reversed',adjustment:'Administrator adjustment',reversal:'Charge reversal',reservation:'Reservation',reserve:'Reservation',release:'Reservation released'} as Record<string,string>)[value]||'Credit adjustment');
  $: alertText = (code:string) => $t(code==='low_credit'?'Your available AI credit is low. Top up to keep paid AI responses available.':code==='financial_review_required'||code==='reconciliation_hold'||code==='unknown_cost'?'Paid AI is paused pending a credit or usage review. Contact your platform administrator. Saved business knowledge remains available.':code==='pricing_unavailable'?'Paid AI is paused because model pricing or the exchange rate cannot be verified safely. Contact your platform administrator.':code==='debt'||code==='negative_balance'?'A balance adjustment must be covered before paid AI resumes.':'Paid AI is paused until sufficient usage credit is available. Saved business knowledge remains available.');

  function errorMessages():Record<string,string> {
    return {active_subscription_required:'Activate your subscription before buying AI usage credit.',
      business_awaiting_activation:'Activate your subscription before buying AI usage credit.',
      invalid_credit_pack:'Choose an available credit pack.',
      invalid_usage_pack:'Choose an available credit pack.',
      invalid_request_id:'Refresh the usage-credit page before trying again.',
      invalid_usage_request_id:'Refresh the usage-credit page before trying again.',
      credit_checkout_in_progress:'Your credit checkout is being prepared. Refresh usage credit shortly.',
      usage_credit_disabled:'Usage credit is not available for this workspace.',
      internal_business_has_no_customer_usage_charge:'Usage credit is not available for this workspace.',
      stripe_setup_required:'Payments are not connected. Contact your platform administrator.',
      usage_live_payments_required:'Payments are not connected. Contact your platform administrator.',
      invalid_adjustment:'Enter a valid adjustment amount and reason.',
      adjustment_reason_required:'Enter a valid adjustment amount and reason.',
      adjustment_exceeds_available_credit:'This adjustment exceeds the company’s available usage credit.',
      usage_request_mismatch:'This purchase request does not match its saved credit pack. Refresh usage credit before continuing.',
      adjustment_request_mismatch:'This adjustment request does not match its saved amount or reason. Refresh the ledger before continuing.',
      usage_checkout_requires_review:'This credit checkout needs review by your platform administrator before you retry.',
      forbidden:'You do not have permission for this billing action.'};
  }
  function safeError(code:string) {
    return errorMessages()[code]||'Usage credit could not be updated. Refresh before trying again, or contact your platform administrator.';
  }
  async function read(path:string,body?:Record<string,unknown>,signal?:AbortSignal) {
    const response=await fetch(apiPrefix+'/billing/usage-credit'+path+(path.includes('?')?'&':'?')+'tenant='+encodeURIComponent(tenant),{
      credentials:'same-origin',signal,...(body?{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(body)}:{})
    });
    const result=await response.json();
    if(!response.ok)throw new Error(safeError(String(result.error||'')));
    return result;
  }
  function failureText(failure:unknown) {
    const text=failure instanceof Error?failure.message:'';
    const approved=Object.values(errorMessages());
    return approved.includes(text)?text:safeError('');
  }
  async function refresh() {
    if(disposed||!canViewCosts)return;
    controller?.abort();const request=new AbortController();controller=request;busy=true;error='';
    const timeout=setTimeout(()=>request.abort(),25000);
    try {
      const result=await read('?page='+page,undefined,request.signal);
      if(disposed||controller!==request||request.signal.aborted)return;
      data=result;
      dispatch('creditstatus',{tenant,alerts:data?.internal?[]:data?.wallet.alerts||[]});
      if(!data?.packs.some(row=>row.id===selectedPack))selectedPack=data?.packs[0]?.id||'';
      syncCheckoutRequests(data);
    } catch(failure) {if(!disposed&&controller===request)error=request.signal.aborted?'Usage credit loading timed out. Try refreshing.':failureText(failure);}
    finally {clearTimeout(timeout);if(!disposed&&controller===request){controller=undefined;busy=false;}}
  }
  function syncCheckoutRequests(report:UsageReport|null) {
    if(!report)return;
    const checkouts=report.checkout_requests||report.pending_checkouts||[];
    for(const option of report.packs) {
      const storageKey='v7-usage-checkout:'+tenant+':'+option.id;
      let previous=checkoutRequests.get(option.id);
      try {previous=previous||sessionStorage.getItem(storageKey)||undefined;} catch { /* Storage is optional. */ }
      const pending=checkouts.find(row=>row.pack_id===option.id&&!['paid','complete','completed','expired','cancelled','canceled','failed'].includes(row.status));
      if(pending) {checkoutRequests.set(option.id,pending.request_id);try {sessionStorage.setItem(storageKey,pending.request_id);} catch { /* Storage is optional. */ }}
      else if(previous) {checkoutRequests.delete(option.id);try {sessionStorage.removeItem(storageKey);} catch { /* Storage is optional. */ }}
    }
  }
  function checkoutId(packId:string) {
    let requestId=checkoutRequests.get(packId);
    const storageKey='v7-usage-checkout:'+tenant+':'+packId;
    if(!requestId) {
      try {requestId=sessionStorage.getItem(storageKey)||undefined;} catch { /* Idempotency still holds for this open view when storage is unavailable. */ }
    }
    if(!requestId||!/^[a-f0-9-]{32,36}$/i.test(requestId))requestId=crypto.randomUUID();
    checkoutRequests.set(packId,requestId);
    try {sessionStorage.setItem(storageKey,requestId);} catch { /* Some browsers disable session storage. */ }
    return requestId;
  }
  async function topUp() {
    if(busy||disposed||!canManageBilling||!canTopUp||!pack||!data?.configured)return;
    const request=new AbortController();controller=request;busy=true;error='';message='';
    const timeout=setTimeout(()=>request.abort(),25000);
    try {
      const result=await read('/checkout',{pack_id:pack.id,request_id:checkoutId(pack.id)},request.signal);
      if(disposed||controller!==request||request.signal.aborted)return;
      if(typeof result.url==='string'&&new URL(result.url).origin==='https://checkout.stripe.com')window.location.assign(result.url);
      else if(['paid','expired','failed','complete','completed','canceled','cancelled'].includes(result.status)) {
        const storageKey='v7-usage-checkout:'+tenant+':'+pack.id;
        checkoutRequests.delete(pack.id);try {sessionStorage.removeItem(storageKey);} catch { /* Storage is optional. */ }
        message=result.status==='paid'?'This credit purchase is already paid. Refresh the balance before buying more.':'This credit checkout ended without a new payment. Refresh before starting another purchase.';
        await refresh();
      } else if(result.status==='processing')message='Stripe is confirming this credit purchase. Refresh shortly; do not start another payment for it.';
      else error='The credit checkout could not be confirmed. Refresh before trying again.';
    } catch(failure) {if(!disposed&&controller===request)error=request.signal.aborted?'The credit checkout could not be confirmed. Refresh before trying again.':failureText(failure);}
    finally {clearTimeout(timeout);if(!disposed&&controller===request){controller=undefined;busy=false;}}
  }
  async function listCompanies() {
    if(!isPlatform||disposed)return;
    companyController?.abort();const request=new AbortController();companyController=request;companyBusy=true;
    const timeout=setTimeout(()=>request.abort(),25000);
    try {
      const result=await read('/companies?page='+companyPage+'&search='+encodeURIComponent(companySearch),undefined,request.signal);
      if(disposed||companyController!==request||request.signal.aborted)return;
      companies=result.companies;companyTotal=result.matched??result.total;companyHasNext=result.has_next;
    } catch(failure) {if(!disposed&&companyController===request)error=request.signal.aborted?'Company loading timed out. Try searching again.':failureText(failure);}
    finally {clearTimeout(timeout);if(!disposed&&companyController===request){companyController=undefined;companyBusy=false;}}
  }
  async function adjust() {
    const amount=Math.round(Number(adjustmentAmount)*100);
    if(busy||disposed||!isPlatform||!adjustmentConfirmed||!Number.isSafeInteger(amount)||amount===0||!adjustmentReason.trim())return;
    const request=new AbortController();controller=request;busy=true;error='';message='';
    const timeout=setTimeout(()=>request.abort(),25000);
    if(!adjustmentRequest)adjustmentRequest=crypto.randomUUID();
    try {
      await read('/adjust',{amount_pence:amount,reason:adjustmentReason.trim(),request_id:adjustmentRequest},request.signal);
      if(disposed||controller!==request||request.signal.aborted)return;
      adjustmentAmount='';adjustmentReason='';adjustmentConfirmed=false;adjustmentRequest='';
      message='Credit adjustment recorded in the audit ledger.';
      await refresh();void listCompanies();
    } catch(failure) {if(!disposed&&controller===request)error=request.signal.aborted?'The credit adjustment could not be confirmed. Refresh the ledger before trying again.':failureText(failure);}
    finally {clearTimeout(timeout);if(!disposed&&controller===request){controller=undefined;busy=false;}}
  }
  onMount(()=>{if(canViewCosts)void refresh();if(isPlatform)void listCompanies();});
  onDestroy(()=>{disposed=true;controller?.abort();companyController?.abort();});
</script>

<section id="ai-usage-credit" class="credits" aria-label={$t('AI usage credit')}>
  <header><div><h2>{$t('Top up AI credit')}</h2><p>{$t('Subscription and setup pay for the platform. AI processing is paid separately from a prepaid GBP balance; no AI credit is included in your plan.')}</p></div><button disabled={busy||!canViewCosts} on:click={refresh}>{$t('Refresh usage credit')}</button></header>
  {#if error}<p class="notice error" role="alert">{$t(error)}</p>{/if}{#if message}<p class="notice" role="status">{$t(message)}</p>{/if}
  {#if busy}<p class="notice" role="status">{$t('Updating usage credit…')}</p>{/if}
  {#if !canViewCosts}<p>{$t('Your account can see AI availability. Detailed usage credit and costs require cost-view permission.')}</p>{/if}
  {#if data}
    {#if data.internal}<p class="notice">Internal workspace: this balance is an administrative ledger record. The internal AI exemption remains active; provider funding is separate.</p>{/if}
    {#each alerts as alert}<p class="notice error" role="alert">{alertText(alert.code)}</p>{/each}
    {#if canViewCosts}
      <div class="balances"><article><h3>{$t('Available credit')}</h3><strong><bdi>{money(data.wallet.available_pence)}</bdi></strong><p>{$t(data.internal ? 'Administrative credit record; internal AI does not spend this balance.' : 'Available for new paid AI requests.')}</p></article><article><h3>{$t('Reserved credit')}</h3><strong><bdi>{money(data.wallet.reserved_pence)}</bdi></strong><p>{$t('Held for requests awaiting a confirmed cost; not charged twice.')}</p></article><article><h3>{$t('Confirmed AI spend')}</h3><strong><bdi>{money(data.wallet.spent_pence)}</bdi></strong><p>{$t('Recorded usage charges, separate from token counts.')}</p></article></div>
      {#if data.wallet.debt_pence}<p class="notice error">{$t('Balance adjustment to cover: {price}.',{price:money(data.wallet.debt_pence)})}</p>{/if}
      {#if data.wallet.unknown_reservations}<p class="notice">{$t('{count} requests have an unconfirmed cost. Their reservations stay held while usage is reconciled.',{count:count(data.wallet.unknown_reservations)})}</p>{/if}
      {#if !data.internal}<p>{$t('Purchased credit carries forward. There is no automatic recharge, and credit is added only after Stripe confirms payment. At low credit, top up manually; when credit cannot cover a request, paid AI pauses and saved-knowledge replies remain available.')}</p>{/if}
      {#if canManageBilling && !data.internal}
        <form class="top-up" on:submit|preventDefault={topUp}><label>{$t('Credit pack')}<select bind:value={selectedPack} disabled={busy||!data.configured||!canTopUp}>{#each data.packs as option}<option value={option.id}>{$t(option.vat_percent ? '{credit} credit · pay {total} including VAT' : '{credit} credit · pay {total} — no VAT charged',{credit:money(option.credit_pence),total:money(option.total_pence)})}</option>{/each}</select></label>{#if pack}<div class="pack-total"><strong>{$t('Pay {total}',{total:money(pack.total_pence)})}</strong><small>{$t(pack.vat_percent ? '{credit} usage credit + {tax} VAT ({percent}%).' : '{credit} usage credit. No VAT charged.',{credit:money(pack.credit_pence),tax:money(pack.tax_pence),percent:count(pack.vat_percent)})}</small></div>{/if}<button disabled={busy||!data.configured||!canTopUp||!pack}>{$t('Top up securely with Stripe')}</button></form>
        {#if !canTopUp}<p>{$t('Activate your subscription before buying AI usage credit.')}</p>{/if}
        {#if !data.configured}<p class="notice">{$t('Payments are not connected. Contact your platform administrator.')}</p>{/if}
        {#if data.pending_checkouts?.length}<p class="notice">{$t('A credit checkout is pending. Retrying the same pack resumes that purchase; a browser redirect alone does not add credit.')}</p>{/if}
      {:else if data.internal}<p class="notice">{$t('This internal agent does not need a customer top-up. Fund your central OpenAI account separately; platform administrators can record an audited credit adjustment below.')}</p>{:else}<p>{$t('Your business owner can buy usage credit.')}</p>{/if}
      <details><summary>{$t('How AI charges are calculated')}</summary><p>{$t('AI usage charges use the model’s input, cached-input and output rates, recorded usage, the exchange rate and the configured markup. Tokens measure activity; the GBP credit ledger records what was charged.')}</p><p>{$t('Current markup: {percent}%.',{percent:markup(data.wallet.markup_percent)})}</p>{#if data.wallet.exchange_rate}<p>{$t('USD-to-GBP exchange rate: {rate}, dated {date}.',{rate:new Intl.NumberFormat(locale,{maximumFractionDigits:6}).format(Number(data.wallet.exchange_rate.rate)),date:fxDate(data.wallet.exchange_rate.date)})}</p>{#if data.wallet.exchange_rate.stale}<p class="notice">{$t('The exchange rate needs updating. Paid AI will not assume missing pricing is free.')}</p>{/if}{:else}<p>{$t('An exchange rate is not yet available. Paid AI will not assume missing pricing is free.')}</p>{/if}<p>{$t('Phone-number rental and Meta/provider messaging charges are separate from this AI credit balance.')}</p></details>
      <h3>{$t('Usage and credit history')}</h3><p>{$t('Each confirmed charge records its model and pricing version. Input tokens include cached input; cached tokens are shown separately, not added a second time.')}</p>
      <!-- svelte-ignore a11y_no_noninteractive_tabindex (Keyboard users need to scroll the table horizontally on small screens.) -->
      <div class="scroll" role="region" aria-label={$t('Usage and credit history')} tabindex="0"><table><thead><tr><th>{$t('Date (UTC)')}</th><th>{$t('Entry')}</th><th>{$t('Entry amount')}</th><th>{$t('GBP credit change')}</th><th>{$t('AI usage details')}</th><th>{$t('Receipt')}</th></tr></thead><tbody>{#each transactions as entry}<tr><td>{timestamp(entry.created_utc)}</td><td>{kind(entry.kind)}</td><td><bdi>{money(entry.amount_pence)}</bdi></td><td><bdi>{money(entry.balance_delta_pence)}</bdi>{#if entry.reserved_delta_pence}<small>{$t('{price} reservation change',{price:money(entry.reserved_delta_pence)})}</small>{/if}{#if entry.debt_delta_pence}<small>{$t('{price} debt change',{price:money(entry.debt_delta_pence)})}</small>{/if}</td><td>{#if entry.usage}<bdi>{entry.usage.model||$t('Not recorded')}</bdi><small>{$t('Input: {input} · cached: {cached} · output: {output}',{input:count(entry.usage.input_tokens),cached:count(entry.usage.cached_tokens),output:count(entry.usage.output_tokens)})}</small><small>{$t('Pricing version: {version}',{version:entry.usage.price_version||$t('Not recorded')})}</small><details><summary>{$t('Charge calculation')}</summary><p>{$t('Provider cost: {cost} USD.',{cost:rate(entry.usage.provider_cost_usd)})}</p><p>{$t('Recorded exchange rate: {rate} USD-to-GBP · markup: {percent}%.',{rate:rate(entry.usage.fx_rate),percent:markup(entry.usage.markup_percent)})}</p>{#if entry.usage.fx_date}<p>{$t('Exchange-rate date: {date}.',{date:fxDate(entry.usage.fx_date)})}</p>{/if}{#if entry.usage.rate_snapshot||entry.usage.model_rate}{@const rates=entry.usage.rate_snapshot||entry.usage.model_rate}<p>{$t('Model rates per million tokens (USD): input {input} · cached {cached} · output {output}.',{input:rate(rates?.input==null?undefined:rates.input/1000),cached:rate(rates?.cached==null?undefined:rates.cached/1000),output:rate(rates?.output==null?undefined:rates.output/1000)})}</p>{#if rates?.audio_second!=null}<p>{$t('Audio: {seconds} seconds · provider rate {rate} USD per second.',{seconds:rate(entry.usage.audio_seconds),rate:rate(rates.audio_second/1e9)})}</p>{/if}{/if}</details>{:else}{$t('Not applicable')}{/if}</td><td>{#if entry.receipt_url}<a href={entry.receipt_url} target="_blank" rel="noopener noreferrer">{$t('View receipt')}</a>{:else}{$t('Not available')}{/if}</td></tr>{:else}<tr><td colspan="6">{$t('No usage-credit entries recorded yet.')}</td></tr>{/each}</tbody></table></div>
      <div class="controls"><button disabled={page===1||busy} on:click={()=>{page--;refresh();}}>{$t('Previous')}</button><span>{$t('Page {page}',{page:count(page)})}</span><button disabled={!data.wallet.has_next||busy} on:click={()=>{page++;refresh();}}>{$t('Next')}</button></div>
    {:else}<p>{$t('Your account can see AI availability. Detailed usage credit and costs require cost-view permission.')}</p>{/if}
  {/if}
  {#if isPlatform}
    <details class="admin"><summary>{$t('All-company usage credit')}</summary><form class="controls" on:submit|preventDefault={()=>{companyPage=1;listCompanies();}}><label>{$t('Find a company')}<input bind:value={companySearch} placeholder={$t('Company name or key')}/></label><button disabled={companyBusy}>{$t('Search')}</button></form>
      {#if companyBusy}<p role="status">{$t('Loading companies…')}</p>{/if}
      <p>{$t('{count} companies',{count:count(companyTotal)})}</p>
      <div class="scroll"><table><thead><tr><th>{$t('Company')}</th><th>{$t('Available credit')}</th><th>{$t('Reserved credit')}</th><th>{$t('Confirmed AI spend')}</th><th>{$t('Status')}</th></tr></thead><tbody>{#each companies as company}<tr><td><bdi>{company.name} · {company.key}</bdi></td><td><bdi>{money(company.wallet.available_pence)}</bdi></td><td><bdi>{money(company.wallet.reserved_pence)}</bdi></td><td><bdi>{money(company.wallet.spent_pence)}</bdi></td><td>{$t(company.internal?'Internal workspace':company.wallet.paused?'Paid AI paused':'Paid AI available')}</td></tr>{/each}</tbody></table></div>
      <div class="controls"><button disabled={companyPage===1||companyBusy} on:click={()=>{companyPage--;listCompanies();}}>{$t('Previous')}</button><span>{$t('Page {page}',{page:count(companyPage)})}</span><button disabled={!companyHasNext||companyBusy} on:click={()=>{companyPage++;listCompanies();}}>{$t('Next')}</button></div>
    </details>
    <details class="admin"><summary>{$t('Adjust this company’s usage credit')}</summary><p>{$t('Administrator adjustments change the credit ledger, not a Stripe payment. Record a reason; a cash refund must be handled separately through Stripe.')}</p><form class="controls" on:submit|preventDefault={adjust}><label>{$t('Credit adjustment (£)')}<input type="number" step="0.01" bind:value={adjustmentAmount} required on:input={()=>{adjustmentRequest='';adjustmentConfirmed=false;}}/></label><label>{$t('Reason')}<input bind:value={adjustmentReason} maxlength="500" required on:input={()=>{adjustmentRequest='';adjustmentConfirmed=false;}}/></label><label class="confirmation"><input type="checkbox" bind:checked={adjustmentConfirmed}/>{$t('I confirm this adjustment for {company}.',{company:tenant})}</label><button disabled={busy||!adjustmentConfirmed||!Number(adjustmentAmount)||!adjustmentReason.trim()}>{$t('Record credit adjustment')}</button></form></details>
  {/if}
</section>

<style>
  .credits { display:grid; gap:16px; background:var(--v7-surface,#fff); border:1px solid var(--v7-line,#e1e7e4); border-radius:12px; padding:20px; min-width:0; }
  header,.controls,.top-up { display:flex; flex-wrap:wrap; align-items:end; gap:12px; }
  header { justify-content:space-between; }
  header>div { flex:1 1 280px; }
  h2,h3 { margin:0; font-size:20px; }
  h3 { font-size:14px; }
  p { margin:0; font-size:13px; line-height:1.65; color:var(--v7-muted,#64716d); }
  .balances { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,200px),1fr)); gap:12px; }
  .balances article { padding:16px; border-radius:8px; background:var(--v7-canvas,#f5f7f7); }
  .balances strong { display:block; margin:8px 0; font-size:26px; font-variant-numeric:tabular-nums; }
  button,input,select { font:inherit; font-size:13px; box-sizing:border-box; min-height:44px; max-width:100%; border:1px solid var(--v7-control-line,#c5d1cb); border-radius:8px; background:var(--v7-surface,#fff); color:var(--v7-ink); padding:10px 12px; }
  button { cursor:pointer; font-weight:600; }
  button:disabled { opacity:.5; cursor:default; }
  button:hover:not(:disabled) { border-color:var(--v7-accent,#087f5b); background:var(--v7-soft,#edf6f1); }
  .top-up button { background:var(--v7-accent,#087f5b); border-color:var(--v7-accent,#087f5b); color:#fff; }
  label { display:grid; gap:7px; min-width:0; font-size:12px; font-weight:600; }
  .controls label { flex:1 1 200px; }
  .confirmation { display:flex; align-items:center; flex-basis:100%; }
  .confirmation input { min-height:20px; }
  .pack-total small,td small { display:block; margin-top:5px; color:var(--v7-muted,#64716d); font-size:12px; }
  .notice { padding:12px 14px; background:var(--v7-soft,#edf6f1); border:1px solid var(--v7-line); border-radius:8px; }
  .error { background:#fff2f0; border-color:#f2d6d2; color:#9b332b; }
  summary { min-height:44px; align-content:center; cursor:pointer; color:var(--v7-accent,#087f5b); font-size:13px; }
  details p { margin-block:8px; }
  .scroll { overflow:auto; border:1px solid var(--v7-line); border-radius:8px; max-width:100%; }
  table { width:100%; border-collapse:collapse; text-align:start; font-size:12px; }
  th,td { padding:12px; border-bottom:1px solid var(--v7-line); vertical-align:top; font-variant-numeric:tabular-nums; }
  th { background:var(--v7-canvas,#f5f7f7); color:var(--v7-muted); white-space:nowrap; }
  a { color:var(--v7-accent); }
  .admin { border-top:1px solid var(--v7-line); padding-top:8px; }
  :is(button,input,select,a,summary,.scroll):focus-visible { outline:3px solid var(--v7-accent,#087f5b); outline-offset:3px; }
  @media(max-width:600px) { .credits { padding:16px; } .top-up label { width:100%; } }
</style>
