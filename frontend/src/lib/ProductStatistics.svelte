<script lang="ts">
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
  <nav aria-label="Product statistics views">{#each [{id:'interest',name:'Product interest'},{id:'sales',name:'Product sales'},{id:'stock',name:'Stock levels'}] as tab}<button class:active={view===tab.id} aria-pressed={view===tab.id} on:click={()=>view=tab.id}>{tab.name}</button>{/each}</nav>
  <div class="cards">
    <article><h3>Matched product enquiries</h3><strong>{format(data.products.reduce((n,p)=>n+p.interest,0))}</strong><p>A product returned for a search, price, comparison or category enquiry counts once per reply. One enquiry can match several products.</p></article>
    <article><h3>Recorded product sales · GBP</h3><strong>{money(data.products.reduce((n,p)=>n+p.amount_pence,0))}</strong><p>Owner-entered line totals for the selected dates and channel. Not imported from a checkout; voided entries are excluded.</p></article>
    <article><h3>Low or out of stock now</h3><strong>{data.products.filter(p=>!p.archived&&(!p.available||(p.quantity!==null&&p.quantity<=p.threshold))).length}</strong><p>{data.products.filter(p=>!p.archived&&p.quantity===null).length} products have no quantity recorded. Stock ignores the channel filter.</p></article>
  </div>
  <div class="controls"><label>Find product<input bind:value={search} placeholder="Name or reference" /></label><label>Ranking order<select bind:value={ascending}><option value={false}>Highest to lowest</option><option value={true}>Lowest to highest</option></select></label>{#if view==='sales'}<label>Rank sales by<select bind:value={salesRank}><option value="units">Units sold</option><option value="value">Sales value (£)</option></select></label>{/if}{#if view==='stock'}<label>Stock filter<select bind:value={stockFilter}><option value="all">All stock levels</option><option value="low">Low / out of stock</option><option value="unknown">Not counted</option></select></label>{/if}</div>
  <article><h3>{view==='interest'?'Product interest ranking':view==='sales'?(salesRank==='value'?'Products ranked by sales value (£)':'Products ranked by units sold'):'Products ranked by current quantity'}</h3>
    <div class="bars">{#each top as product}<div class="bar-row"><span>{product.name}</span><div class="track"><div class="bar" style:width={(Math.max(0,rank(product))/topMax*100)+'%'}></div></div><strong>{view==='stock'&&product.quantity===null?'Not counted':view==='sales'&&salesRank==='value'?money(product.amount_pence):format(rank(product))}</strong></div>{/each}</div>
    <p class="hint">Chart shows the first 10 in the selected ranking. Compare quantities in the product’s own units; kilograms and individual items are not equivalent.</p>
    <div class="scroll"><table><caption>All matching products · {sorted.length}</caption><thead><tr><th>Product</th><th>Enquiries</th><th>Units sold</th><th>Sales GBP</th><th>Quantity now</th><th>Stock status</th></tr></thead><tbody>{#each visible as product}<tr><th><button class="link" on:click={()=>selected=product.sku}>{product.name}</button><small>{product.sku}</small></th><td>{format(product.interest)}</td><td>{format(product.units)}</td><td>{money(product.amount_pence)}</td><td>{product.quantity===null?'Not counted':format(product.quantity)+' '+product.unit}</td><td>{stock(product)}<small>Alert at {product.threshold} {product.unit}</small></td></tr>{:else}<tr><td colspan="6">No matching products.</td></tr>{/each}</tbody></table></div>
    <div class="controls"><button disabled={page===0} on:click={()=>page-=1}>Previous</button><span>Page {page+1} of {Math.max(1,Math.ceil(sorted.length/25))}</span><button disabled={(page+1)*25>=sorted.length} on:click={()=>page+=1}>Next</button></div>
  </article>
  <label>Product timeline<select bind:value={selected}><option value="">All products (interest and sales)</option>{#each data.products as product}<option value={product.sku}>{product.name} · {product.sku}</option>{/each}</select></label>
  {#if view==='interest'}
    <TrendChart title="Product interest over time" labels={days} series={[{name:'Matched enquiries',color:'#007d70',values:interest}]}/>
    <p class="hint">{data.interest_tracking_since?'First retained product-interest event: '+new Date(data.interest_tracking_since).toLocaleString('en-GB',{timeZone:'UTC'})+' UTC.':'Product-interest tracking starts with new agent conversations after this update.'} Earlier untracked searches cannot be reconstructed. Zero means no recorded matches, not proof that nobody wanted the product.</p>
  {:else if view==='sales'}
    <TrendChart title="Product units sold over time" labels={days} series={[{name:'Owner-recorded units',color:'#007d70',values:units}]}/>
    <TrendChart title="Product sales value over time (GBP)" labels={days} unit=" GBP" series={[{name:'Owner-recorded sales',color:'#596f9c',values:revenue}]}/>
    {#if canRecord}<article><h3>Record a completed product sale</h3><p>Record one product line at a time. Use the actual line total in pounds. This records reporting data only; it does not take payment, deduct inventory or link a sale to a specific chat.</p>
      <form on:submit|preventDefault={recordSale}><label>Product<select bind:value={saleSku} required disabled={busy}><option value="">Choose product</option>{#each data.products.filter(p=>!p.archived) as p}<option value={p.sku}>{p.name}</option>{/each}</select></label><label>Quantity (catalogue units)<input type="number" min="0.001" max="1000000" step="0.001" bind:value={quantity} required disabled={busy}/></label><label>Line total (£)<input type="number" min="0" max="10000000" step="0.01" bind:value={amount} required disabled={busy}/></label><label>Sale date and time (UTC)<input type="datetime-local" bind:value={occurred} required disabled={busy}/></label><label>Sales channel<select bind:value={channel} disabled={busy}><option value="offline">Offline / other</option><option value="web">Website</option><option value="whatsapp">WhatsApp</option></select></label><button disabled={busy} type="submit">{busy?'Saving…':'Record sale'}</button></form>
      {#if status}<p class:error={failed} role="status">{status}</p>{/if}
    </article>{/if}
    <article><h3>Latest recorded sales</h3><p>Up to 30 entries in the selected period and channel. Void an incorrect entry and record its replacement; the original stays in the audit history.</p><div class="scroll"><table><thead><tr><th>Date (UTC)</th><th>Product</th><th>Quantity</th><th>GBP</th><th>Channel</th>{#if canRecord}<th>Correction</th>{/if}</tr></thead><tbody>{#each data.recent_sales as sale}<tr><td>{new Date(sale.occurred_utc).toLocaleString('en-GB',{timeZone:'UTC'})}</td><td>{sale.name}</td><td>{format(sale.quantity)}</td><td>{money(sale.amount_pence)}</td><td>{sale.channel}</td>{#if canRecord}<td>{#if confirmVoid===sale.id}<button disabled={busy} on:click={()=>voidSale(sale.id)}>Confirm void</button><button on:click={()=>confirmVoid=''}>Cancel</button>{:else}<button on:click={()=>confirmVoid=sale.id}>Void entry</button>{/if}</td>{/if}</tr>{:else}<tr><td colspan="6">No sales recorded for this period and channel.</td></tr>{/each}</tbody></table></div></article>
  {:else}
    {#if selected}<TrendChart title={'Stock history · '+matching[0]?.name} labels={days} series={[{name:'Last recorded daily quantity',color:'#007d70',values:inventory}]}/>{:else}<article><h3>Choose a product to see its stock history</h3><p>Separate product timelines avoid adding incompatible units together.</p></article>{/if}
    <p class="hint">Stock history starts when catalogue quantities are saved. Gaps mean unknown stock; known values carry forward until the next recorded update. Current levels include changes after the report period. Sales entries do not automatically deduct stock.</p><a href={base+'/catalog'}>Update quantities and low-stock thresholds in Catalogue</a>
  {/if}
</div>
<style>
 .products{display:grid;gap:20px;min-width:0;overflow-wrap:anywhere}nav,.controls{display:flex;flex-wrap:wrap;gap:12px;align-items:end}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,240px),1fr));gap:16px}article{padding:22px;border:1px solid #d9ddd7;border-radius:8px;background:white;min-width:0}h3{margin:0;font-size:17px}.cards strong{display:block;font-size:30px;margin-top:16px}p,.hint{font-size:13px;color:#526359;line-height:1.6}label{display:grid;gap:8px;font-size:14px;font-weight:600;min-width:0}input,select{min-width:0;width:100%}input,select,button{box-sizing:border-box;max-width:100%;min-height:44px;border:1px solid #bbc4bc;border-radius:6px;padding:10px 12px;background:white;color:#26332b;font:inherit}button{cursor:pointer;font-weight:600}button.active,form button{background:#007d70;color:white;border-color:#007d70}button:disabled{opacity:.5;cursor:default}form{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,230px),1fr));gap:16px;align-items:end}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;text-align:left;font-size:14px}th,td{padding:12px;border-bottom:1px solid #dce3dc}small{display:block;font-size:12px;color:#526359;margin-top:5px}caption{text-align:left;padding:16px 0}.controls{margin:12px 0}.link{padding:0;border:0;min-height:30px;color:#007d70;text-align:left}.bars{display:grid;gap:14px;margin-top:24px}.bar-row{display:grid;grid-template-columns:minmax(90px,1fr) 2fr minmax(55px,auto);align-items:center;gap:12px;font-size:13px}.track{background:#edf2ed;border-radius:4px;height:16px}.bar{height:16px;background:#007d70;border-radius:4px}.error{color:#ad3939}a{color:#007d70}:is(button,a,input,select):focus-visible{outline:3px solid #8bcdc0;outline-offset:3px}@media(max-width:600px){article{padding:16px}.controls label{width:100%}}
</style>
