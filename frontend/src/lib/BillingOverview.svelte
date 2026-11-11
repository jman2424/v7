<script lang="ts">
  import {onMount,onDestroy} from 'svelte';
  import {t,language} from './i18n';
  import {subscriptionLocales} from './subscription-format';
  import {base} from './consoleBase';
  import {sectionHref} from './workspaceArchitecture';
  export let tenant:string;
  export let canViewCosts=false;
  export let canViewSubscriptions=false;
  export let compact=false;
  export let apiPrefix='';
  type Balance={available_pence:number;monthly_spent_pence:number;processing_available:boolean;paused:boolean;review_required:boolean;internal:boolean;automatic_recharge:{enabled:boolean}};
  type Subscription={internal?:boolean;complimentary?:boolean;business_purchase_allowed?:boolean;plan_state?:{active_plan:string|null;selected_plan:string|null};plans?:{id:string;name:string}[];totals?:{due:number}};
  let balance:Balance|null=null,subscription:Subscription|null=null;
  let errors:string[]=[],busy=false,disposed=false;
  let controller:AbortController|undefined;
  $: money=(value:number)=>new Intl.NumberFormat(subscriptionLocales[$language],{style:'currency',currency:'GBP'}).format(value/100);
  $: planId=subscription?.plan_state?.active_plan;
  $: planName=subscription?.plans?.find(plan=>plan.id===planId)?.name||planId;
  async function refresh(){
    controller?.abort();const request=new AbortController();controller=request;busy=true;errors=[];
    const timeout=setTimeout(()=>request.abort(),20000);
    const reads=[...(canViewCosts?['ai-budget']:[]),...(canViewSubscriptions&&!compact?['subscription']:[])];
    try{
      const results=await Promise.allSettled(reads.map(async path=>{
        const response=await fetch(apiPrefix+'/billing/'+path+'?tenant='+encodeURIComponent(tenant),{credentials:'same-origin',signal:request.signal});
        if(!response.ok)throw new Error(path);return response.json();
      }));
      if(disposed||controller!==request||request.signal.aborted)return;
      results.forEach((result,index)=>{const path=reads[index];if(result.status==='fulfilled'){if(path==='ai-budget')balance=result.value;else subscription=result.value;}else errors=[...errors,path==='ai-budget'?'Your AI balance could not be loaded.':'Your subscription could not be loaded.'];});
    }finally{clearTimeout(timeout);if(!disposed&&controller===request){busy=false;controller=undefined;}}
  }
  onMount(refresh);
  onDestroy(()=>{disposed=true;controller?.abort();});
</script>

<section class="billing-summary" class:compact aria-label={$t(compact?'AI balance':'Billing overview')} aria-busy={busy}>
  {#if errors.length}<div class="error" role="alert">{#each errors as error}<p>{$t(error)}</p>{/each}<button disabled={busy} on:click={refresh}>{$t('Try again')}</button></div>{/if}
  {#if busy&&!balance&&!subscription}<p role="status">{$t('Loading billing summary…')}</p>{/if}
  {#if balance}
    <article class="summary-card balance-card"><div class="card-top"><span>{$t('AI balance')}</span><span class="status">{$t(balance.internal?'Platform funded':balance.review_required?'Review needed':!balance.processing_available?'Processing unavailable':balance.paused?'Funds needed':'Available')}</span></div>
      {#if balance.internal}<h2>{$t('Platform funding')}</h2><p>{$t('This workspace does not use a customer AI balance.')}</p>
      {:else}<p class="amount"><bdi>{money(balance.available_pence)}</bdi></p><p>{$t('{amount} used this month',{amount:money(balance.monthly_spent_pence)})}</p>
        <p class="small">{$t(balance.review_required?'Your balance needs review; adding funds may not resolve this.':!balance.processing_available?'Processing is temporarily unavailable. Your recorded balance is preserved.':balance.paused?'Add funds to resume paid AI responses.':'AI processing is funded separately from your subscription.')}</p>
      {/if}
      <a href={sectionHref(base,'budget',tenant)}>{$t(balance.internal?'View funding details':'Manage AI Budget')} <span aria-hidden="true">→</span></a>
    </article>
  {/if}
  {#if subscription&&!compact}<article class="summary-card"><div class="card-top"><span>{$t('Subscription')}</span><span class="status">{$t(subscription.complimentary?'Complimentary':planId?'Active plan':'Not active')}</span></div><h2>{planName||$t(subscription.internal?'Internal workspace':'Choose your plan')}</h2><p>{$t(subscription.business_purchase_allowed===false?'Business approval is required before your first payment.':'Review your plan, next steps and billing documents.')}</p>{#if subscription.totals?.due}<p class="small">{$t('{amount} recorded as due',{amount:money(subscription.totals.due)})}</p>{/if}<a href={sectionHref(base,'subscription',tenant)}>{$t('Manage subscription and invoices')} <span aria-hidden="true">→</span></a></article>{/if}
  {#if !compact}<article class="summary-card explain"><h2>{$t('Two simple parts to your bill')}</h2><p>{$t('Your subscription provides platform access. Your AI Budget covers the processing your assistant actually uses.')}</p><p>{$t('Adding funds is a purchase; AI spending records usage. Existing balances and subscription terms stay separate.')}</p>{#if canViewCosts}<a href={sectionHref(base,'spending',tenant)}>{$t('Review AI spending')} <span aria-hidden="true">→</span></a>{/if}</article>{/if}
</section>

<style>
 .billing-summary{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px;min-width:0}.compact{grid-template-columns:1fr}.summary-card{display:flex;flex-direction:column;gap:15px;min-width:0;border:1px solid var(--v7-line);background:var(--v7-surface);border-radius:var(--v7-radius-panel);padding:26px}.balance-card{background:#edf4ee;border-color:#d1e2d5}.card-top{display:flex;justify-content:space-between;align-items:center;gap:10px;font-size:var(--v7-text-sm);font-weight:600}.status{border:1px solid #c8d7cb;border-radius:var(--v7-radius-panel);padding:5px 9px;font-size:var(--v7-text-xs);line-height:1.4}.summary-card p,.summary-card h2{margin:0}.summary-card h2{font-size:var(--v7-text-2xl);letter-spacing:-.035em}.summary-card p{font-size:var(--v7-text-sm);color:var(--v7-muted);line-height:1.7}.summary-card .amount{font-size:var(--v7-text-figure);font-weight:600;color:var(--v7-ink);letter-spacing:-.05em}.summary-card .small{font-size:var(--v7-text-xs)}.summary-card a{margin-top:auto;padding-top:7px;min-height:44px;display:flex;align-items:center;justify-content:space-between;gap:12px;color:var(--v7-accent);font-size:var(--v7-text-sm);font-weight:650;text-decoration:none}.explain{grid-column:1/-1;background:var(--v7-soft)}.explain h2{font-size:var(--v7-text-lg)}.error{grid-column:1/-1;padding:18px;border:1px solid #e2b3ac;border-radius:var(--v7-radius-panel);color:#822e24;background:#fff5f2}.error p{margin:0 0 10px}.error button{min-height:44px;padding:9px 14px;background:var(--v7-surface);color:inherit;border:1px solid currentColor;border-radius:var(--v7-radius-control);font:inherit}a:focus-visible,button:focus-visible{outline:3px solid var(--v7-focus);outline-offset:3px}@media(max-width:650px){.billing-summary{grid-template-columns:1fr}.summary-card{padding:21px}.summary-card .amount{font-size:var(--v7-text-figure)}}
</style>
