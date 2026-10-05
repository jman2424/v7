<script lang="ts">
  import { t } from './i18n';
  import {base} from '$app/paths';
  import {createEventDispatcher,onDestroy} from 'svelte';
  import TrendChart from './TrendChart.svelte';
  import type {Commerce,Product} from './statisticsTypes';
  export let data:Commerce;
  export let days:string[];
  export let tenant:string;
  export let csrf:string;
  export let apiPrefix='';
  export let canRecord=false;
  const dispatch=createEventDispatcher<{refresh:void}>();
  export let view='interest';
  export let selected='';
  let search='';
  let ascending=false;
  let page=0;
  let stockFilter='all';
  let salesRank='units';
  let saleSku='';
  let quantity=1;
  let amount=0;
  let occurred='';
  let channel='offline';
  let saleId='';
  let busy=false;
  let status='';
  let failed=false;
  let confirmVoid='';
  let controller:AbortController|undefined;
  onDestroy(()=>controller?.abort());
  const money=(pence:number)=>new Intl.NumberFormat('en-GB',{style:'currency',currency:'GBP'}).format(pence/100);
  const format=(n:number)=>n.toLocaleString('en-GB',{maximumFractionDigits:3});
  const stock=(p:Product)=>p.archived?'Removed from catalogue':p.quantity===null?(p.available?'Not counted':'Out of stock · not counted'):p.quantity===0?'Out of stock':p.quantity<=p.threshold?'Low stock':'Above low-stock threshold';
  const rank=(p:Product,metric=salesRank)=>view==='interest'?p.interest:view==='sales'?(metric==='value'?p.amount_pence/100:p.units):p.quantity??-1;
  $: if(view||search||ascending||stockFilter||salesRank)page=0;
  $: sorted=data.products.filter(p=>(p.name+' '+p.sku).toLowerCase().includes(search.toLowerCase())&&(view!=='stock'||(!p.archived&&(stockFilter==='all'||(stockFilter==='low'&&(!p.available||(p.quantity!==null&&p.quantity<=p.threshold)))||(stockFilter==='unknown'&&p.quantity===null)))))
    .sort((a,b)=>((ascending?1:-1)*(rank(a,salesRank)-rank(b,salesRank)))||a.name.localeCompare(b.name));
  $: visible=sorted.slice(page*25,(page+1)*25);
  $: matching=data.products.filter(p=>!selected||p.sku===selected);
  $: interest=days.map(day=>data.interest_daily.filter(row=>row.day===day&&(!selected||row.sku===selected)).reduce((n,row)=>n+row.count,0));
  $: units=days.map(day=>data.sales_daily.filter(row=>row.day===day&&(!selected||row.sku===selected)).reduce((n,row)=>n+row.units,0));
  $: revenue=days.map(day=>data.sales_daily.filter(row=>row.day===day&&(!selected||row.sku===selected)).reduce((n,row)=>n+row.amount_pence/100,0));
  $: inventory=days.map(day=>{const history=data.inventory.filter(row=>row.sku===selected&&row.ts_utc.slice(0,10)<=day);return history.length?history[history.length-1].quantity:null;});
  $: top=sorted.slice(0,10);
  $: topMax=Math.max(1,...top.map(product=>rank(product,salesRank)));
  async function mutate(path:string,payload:Record<string,unknown>) {
    if(busy)return false;
    busy=true;status='';failed=false;controller=new AbortController();
    const timer=setTimeout(()=>controller?.abort(),20000);
    try {
      const response=await fetch(apiPrefix+path+'?tenant='+encodeURIComponent(tenant),{method:'POST',credentials:'same-origin',signal:controller.signal,headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(payload)});
      const result=await response.json();
      if(!response.ok)throw new Error(result.error||'The record could not be saved. Check your session and try again.');
      return true;
    } catch(error){failed=true;status=controller.signal.aborted?'Request timed out. Retry with the same details to avoid duplicate records.':error instanceof Error?error.message:'Unable to save.';return false;}
    finally{clearTimeout(timer);busy=false;}
  }
  async function recordSale(){
    if(!saleId)saleId=crypto.randomUUID();
    if(await mutate('/admin/api/recorded-sales',{id:saleId,sku:saleSku,quantity,amount_gbp:amount,occurred_utc:new Date(occurred+'Z').toISOString(),channel})){
      saleId='';dispatch('refresh');
    }
  }
  async function voidSale(id:string){if(await mutate('/admin/api/recorded-sales/'+encodeURIComponent(id)+'/void',{})){confirmVoid='';dispatch('refresh');}}
</script>
<div class="products">
  <div class="section-heading"><span>Product intelligence</span><h3>Interest, recorded sales and stock</h3><p>Connect customer enquiries with the products and quantities you manage.</p></div>
  <nav aria-label="Product statistics views">{#each [{id:'interest',name:'Product interest'},{id:'sales',name:'Product sales'},{id:'stock',name:'Stock levels'}] as tab}<button class:active={view===tab.id} aria-pressed={view===tab.id} on:click={()=>view=tab.id}>{tab.name}</button>{/each}</nav>
  <div class="cards">
    <article><h3>Matched product enquiries</h3><strong>{format(data.products.reduce((n,p)=>n+p.interest,0))}</strong><p>A product returned for a search, price, comparison or category enquiry counts once per reply. One enquiry can match several products.</p></article>
    <article><h3>Recorded product sales · GBP</h3><strong>{money(data.products.reduce((n,p)=>n+p.amount_pence,0))}</strong><p>Owner-entered line totals for the selected dates and channel. Not imported from a checkout; voided entries are excluded.</p></article>
    <article><h3>Low or out of stock now</h3><strong>{data.products.filter(p=>!p.archived&&(!p.available||(p.quantity!==null&&p.quantity<=p.threshold))).length}</strong><p>{data.products.filter(p=>!p.archived&&p.quantity===null).length} products have no quantity recorded. Stock ignores the channel filter.</p></article>
  </div>
  <div class="controls"><label>Find product<input bind:value={search} placeholder="Name or reference" /></label><label>Ranking order<select bind:value={ascending}><option value={false}>Highest to lowest</option><option value={true}>Lowest to highest</option></select></label>{#if view==='sales'}<label>Rank sales by<select bind:value={salesRank}><option value="units">Units sold</option><option value="value">Sales value (£)</option></select></label>{/if}{#if view==='stock'}<label>Stock filter<select bind:value={stockFilter}><option value="all">All stock levels</option><option value="low">Low / out of stock</option><option value="unknown">Not counted</option></select></label>{/if}</div>
  <article><h3>{view==='interest'?'Product interest ranking':view==='sales'?(salesRank==='value'?'Products ranked by sales value (£)':'Products ranked by units sold'):'Products ranked by current quantity'}</h3>
    <div class="bars">{#each top as product}<div class="bar-row"><span>{product.name}</span><div class="track"><div class="bar" style:width={(Math.max(0,rank(product))/topMax*100)+'%'}></div></div><strong>{view==='stock'&&product.quantity===null?'Not counted':view==='sales'&&salesRank==='value'?money(product.amount_pence):format(rank(product))}</strong></div>{:else}<div class="ranking-empty"><strong>No products in this view</strong><p>Try a different search or stock filter. Product activity appears as it is recorded.</p></div>{/each}</div>
    <p class="hint">Chart shows the first 10 in the selected ranking. Compare quantities in the product’s own units; kilograms and individual items are not equivalent.</p>
    <!-- svelte-ignore a11y_no_noninteractive_tabindex (Keyboard users need to scroll the table horizontally on small screens.) -->
    <div class="scroll" role="region" aria-label="Matching product figures" tabindex="0"><table><caption>All matching products · {sorted.length}</caption><thead><tr><th scope="col">Product</th><th scope="col">Enquiries</th><th scope="col">Units sold</th><th scope="col">Sales GBP</th><th scope="col">Quantity now</th><th scope="col">Stock status</th></tr></thead><tbody>{#each visible as product}<tr><th scope="row"><button class="link" on:click={()=>selected=product.sku}>{product.name}</button><small>{product.sku}</small></th><td>{format(product.interest)}</td><td>{format(product.units)}</td><td>{money(product.amount_pence)}</td><td>{product.quantity===null?'Not counted':format(product.quantity)+' '+product.unit}</td><td>{stock(product)}<small>Alert at {product.threshold} {product.unit}</small></td></tr>{:else}<tr><td colspan="6">No matching products.</td></tr>{/each}</tbody></table></div>
    <div class="controls"><button disabled={page===0} on:click={()=>page-=1}>Previous</button><span>Page {page+1} of {Math.max(1,Math.ceil(sorted.length/25))}</span><button disabled={(page+1)*25>=sorted.length} on:click={()=>page+=1}>Next</button></div>
  </article>
  <label class="timeline-control">Product timeline<select bind:value={selected}><option value="">All products (interest and sales)</option>{#each data.products as product}<option value={product.sku}>{product.name} · {product.sku}</option>{/each}</select></label>
  {#if view==='interest'}
    <TrendChart title="Product interest over time" labels={days} series={[{name:'Matched enquiries',color:'#087f5b',values:interest}]}/>
    <p class="hint">{data.interest_tracking_since?'First retained product-interest event: '+new Date(data.interest_tracking_since).toLocaleString('en-GB',{timeZone:'UTC'})+' UTC.':'Product-interest tracking starts with new agent conversations after this update.'} Earlier untracked searches cannot be reconstructed. Zero means no recorded matches, not proof that nobody wanted the product.</p>
  {:else if view==='sales'}
    <TrendChart title="Product units sold over time" labels={days} series={[{name:'Owner-recorded units',color:'#087f5b',values:units}]}/>
    <TrendChart title="Product sales value over time (GBP)" labels={days} unit=" GBP" series={[{name:'Owner-recorded sales',color:'#64716d',values:revenue}]}/>
    {#if canRecord}<article><h3>Record a completed product sale</h3><p>Record one product line at a time. Use the actual line total in pounds. This records reporting data only; it does not take payment, deduct inventory or link a sale to a specific chat.</p>
      <form on:submit|preventDefault={recordSale}><label>Product<select bind:value={saleSku} required disabled={busy}><option value="">Choose product</option>{#each data.products.filter(p=>!p.archived) as p}<option value={p.sku}>{p.name}</option>{/each}</select></label><label>Quantity (catalogue units)<input type="number" min="0.001" max="1000000" step="0.001" bind:value={quantity} required disabled={busy}/></label><label>Line total (£)<input type="number" min="0" max="10000000" step="0.01" bind:value={amount} required disabled={busy}/></label><label>Sale date and time (UTC)<input type="datetime-local" bind:value={occurred} required disabled={busy}/></label><label>Sales channel<select bind:value={channel} disabled={busy}><option value="offline">Offline / other</option><option value="web">{$t("Website")}</option><option value="whatsapp">WhatsApp</option></select></label><button disabled={busy} type="submit">{busy?'Saving…':'Record sale'}</button></form>
      {#if status}<p class:error={failed} role="status">{status}</p>{/if}
    </article>{/if}
    <article><h3>Latest recorded sales</h3><p>Up to 30 entries in the selected period and channel. Void an incorrect entry and record its replacement; the original stays in the audit history.</p><!-- svelte-ignore a11y_no_noninteractive_tabindex (Keyboard users need to scroll the table horizontally on small screens.) -->
      <div class="scroll" role="region" aria-label="Latest recorded sales" tabindex="0"><table><thead><tr><th scope="col">Date (UTC)</th><th scope="col">Product</th><th scope="col">Quantity</th><th scope="col">GBP</th><th scope="col">Channel</th>{#if canRecord}<th scope="col">Correction</th>{/if}</tr></thead><tbody>{#each data.recent_sales as sale}<tr><td>{new Date(sale.occurred_utc).toLocaleString('en-GB',{timeZone:'UTC'})}</td><td>{sale.name}</td><td>{format(sale.quantity)}</td><td>{money(sale.amount_pence)}</td><td>{sale.channel}</td>{#if canRecord}<td>{#if confirmVoid===sale.id}<button disabled={busy} on:click={()=>voidSale(sale.id)}>Confirm void</button><button on:click={()=>confirmVoid=''}>{$t("Cancel")}</button>{:else}<button on:click={()=>confirmVoid=sale.id}>Void entry</button>{/if}</td>{/if}</tr>{:else}<tr><td colspan="6">No sales recorded for this period and channel.</td></tr>{/each}</tbody></table></div></article>
  {:else}
    {#if selected}<TrendChart title={'Stock history · '+matching[0]?.name} labels={days} series={[{name:'Last recorded daily quantity',color:'#087f5b',values:inventory}]}/>{:else}<article><h3>Choose a product to see its stock history</h3><p>Separate product timelines avoid adding incompatible units together.</p></article>{/if}
    <p class="hint">Stock history starts when catalogue quantities are saved. Gaps mean unknown stock; known values carry forward until the next recorded update. Current levels include changes after the report period. Sales entries do not automatically deduct stock.</p><a href={base+'/catalog'}>Update quantities and low-stock thresholds in Catalogue</a>
  {/if}
</div>
<style>
.products { display:grid; gap:18px; min-width:0; color:var(--v7-ink, #172b26); overflow-wrap:anywhere; }
  .section-heading span { color:var(--v7-muted, #64716d); font-size:10px; text-transform:uppercase; letter-spacing:.1em; font-weight:700; }
  .section-heading h3 { margin-top:6px; color:var(--v7-ink, #172b26); font-size:21px; line-height:1.4; letter-spacing:-.03em; }
  .section-heading p { margin:6px 0 0; }
  nav, .controls { display:flex; flex-wrap:wrap; align-items:end; }
  nav { gap:4px; padding:0 0 10px; border-bottom:1px solid var(--v7-line, #e1e7e4); }
  nav button { border-color:transparent; background:transparent; color:var(--v7-muted, #64716d); font-size:12px; }
  nav button:hover, nav button.active { background:var(--v7-soft, #edf6f1); color:var(--v7-accent, #087f5b); }
  nav button.active { border-color:var(--v7-line, #e1e7e4); }
  .cards { display:grid; grid-template-columns:repeat(auto-fit, minmax(min(100%, 230px), 1fr)); gap:14px; }
  article { min-width:0; padding:22px; border:1px solid var(--v7-line, #e1e7e4); border-radius:12px; background:var(--v7-surface, #fff); box-shadow:none; }
  h3 { margin:0; font-size:16px; line-height:1.45; letter-spacing:-.015em; }
  .cards h3 { color:var(--v7-muted, #64716d); font-size:12px; font-weight:500; line-height:1.5; letter-spacing:0; }
  .cards strong { display:block; margin-top:14px; color:var(--v7-ink, #172b26); font-size:34px; line-height:1.15; letter-spacing:-.045em; font-variant-numeric:tabular-nums; }
  .cards article:first-child strong { color:var(--v7-accent, #087f5b); }
  .cards p { margin:10px 0 0; font-size:11px; }
  p, .hint { color:var(--v7-muted, #64716d); font-size:12px; line-height:1.6; }
  .hint { margin:0; }
  label { display:grid; gap:7px; min-width:0; font-size:12px; font-weight:600; }
  .timeline-control { padding:16px; border:1px solid var(--v7-line, #e1e7e4); border-radius:8px; background:var(--v7-surface, #fff); }
  input, select { min-width:0; width:100%; }
  input, select, button { box-sizing:border-box; max-width:100%; min-height:44px; padding:10px 12px; border:1px solid var(--v7-control-line, #cbd6d0); border-radius:8px; background:var(--v7-surface, #fff); color:var(--v7-ink, #172b26); font:inherit; }
  button { cursor:pointer; font-weight:600; }
  form button { background:var(--v7-accent, #087f5b); border-color:var(--v7-accent, #087f5b); color:#fff; }
  button:disabled { opacity:.5; cursor:default; }
  form { display:grid; grid-template-columns:repeat(auto-fit, minmax(min(100%, 230px), 1fr)); gap:14px; align-items:end; margin-top:18px; }
  .controls { gap:14px; margin:0; padding:16px; border:1px solid var(--v7-line, #e1e7e4); border-radius:8px; background:var(--v7-surface, #fff); }
  .controls label { flex:1 1 180px; }
  .controls button, .controls span { font-size:12px; }
  .controls span { align-self:center; color:var(--v7-muted, #64716d); }
  article > .controls { justify-content:flex-end; margin-top:16px; padding:0; border:0; }
  .scroll { margin-top:14px; overflow:auto; border:1px solid var(--v7-line, #e1e7e4); border-radius:8px; }
  table { width:100%; min-width:660px; border-collapse:collapse; text-align:left; font-size:12px; overflow-wrap:normal; }
  th, td { padding:13px 14px; border-bottom:1px solid var(--v7-line, #e1e7e4); vertical-align:top; font-variant-numeric:tabular-nums; }
  thead th { background:var(--v7-canvas, #f5f7f7); color:var(--v7-muted, #64716d); font-size:11px; font-weight:600; }
  tbody th { font-weight:500; }
  tbody tr:hover { background:var(--v7-soft, #edf6f1); }
  tbody tr:last-child :is(th, td) { border-bottom:0; }
  small { display:block; margin-top:5px; color:var(--v7-muted, #64716d); font-size:11px; }
  caption { padding:12px 14px; border-bottom:1px solid var(--v7-line, #e1e7e4); text-align:left; color:var(--v7-muted, #64716d); font-size:11px; }
  .link { min-height:44px; padding:8px 0; border:0; background:transparent; color:var(--v7-accent, #087f5b); text-align:left; }
  .bars { display:grid; gap:6px; margin:18px 0; }
  .bar-row { display:grid; grid-template-columns:minmax(90px, 1fr) 2fr minmax(55px, auto); align-items:center; gap:14px; padding-block:8px; border-bottom:1px solid var(--v7-line, #e1e7e4); font-size:12px; }
  .bar-row:last-child { border-bottom:0; }
  .bar-row > span { font-weight:500; }
  .bar-row strong { color:var(--v7-ink, #172b26); font-variant-numeric:tabular-nums; }
  .track { height:7px; background:var(--v7-soft, #edf6f1); border-radius:4px; }
  .bar { height:7px; background:var(--v7-accent, #087f5b); border-radius:4px; }
  .ranking-empty { padding:20px; border:1px dashed var(--v7-control-line, #cbd6d0); border-radius:8px; background:var(--v7-canvas, #f5f7f7); }
  .ranking-empty strong { font-size:14px; }
  .ranking-empty p { margin:6px 0 0; }
  .error { color:#ad3939; }
  a { display:inline-flex; align-items:center; min-height:44px; color:var(--v7-accent, #087f5b); font-size:13px; font-weight:600; text-underline-offset:3px; }
  :is(button, a, input, select, .scroll):focus-visible { outline:3px solid var(--v7-focus, #81baa1); outline-offset:3px; }
  @media(max-width:600px) { article { padding:16px; } .section-heading h3 { font-size:19px; } .cards strong { font-size:32px; } .controls { padding:12px; } .controls label { width:100%; } .bar-row { grid-template-columns:minmax(70px, 1fr) 1fr minmax(45px, auto); gap:8px; } nav button { flex:1 1 120px; } }
</style>
