<script lang="ts">
  import { t } from './i18n';
  import { onMount, onDestroy } from 'svelte';
  import { base } from '$app/paths';
  import PerformanceStatistics from './PerformanceStatistics.svelte';
  import ProductStatistics from './ProductStatistics.svelte';
  import StatisticsOverview from './StatisticsOverview.svelte';
  import type {Stats} from './statisticsTypes';
  export let tenant: string;
  export let csrf = '';
  export let canRecordSales = false;
  export let apiPrefix = '';
  const views = [{id:'overview',label:'Overview'},{id:'performance',label:'Reply rates & trends'},{id:'products',label:'Products, sales & stock'},{id:'offers',label:'Offer overview'},{id:'sales',label:'Lead activity'},{id:'quality',label:'Response quality'}];
  const stages = ['Open','Contacted','Qualified','Won','Lost','Other'];
  let view = 'overview';
  let productView = 'interest';
  let selectedProduct = '';
  let days = 30;
  let channel = 'all';
  let data:Stats|null = null;
  let busy = false;
  let error = '';
  let updatedAt = '';
  let mounted = false;
  let controller:AbortController|undefined;
  const number = (value:number) => value.toLocaleString('en-GB');
  const percent = (part:number,total:number) => total ? (100*part/total).toFixed(1)+'%' : 'No data';
  const date = (value:string) => new Date(value).toLocaleString('en-GB',{timeZone:'UTC',dateStyle:'medium',timeStyle:'short'});
  const change = (current:number,previous:number) => !previous ? current ? 'No activity in previous period' : 'No change' : `${current>=previous?'+':''}${((current-previous)/previous*100).toFixed(1)}% vs previous period`;
  $: if (mounted) refresh(tenant,days,channel);
  onMount(()=>{mounted=true;});
  onDestroy(()=>{controller?.abort();controller=undefined;});
  async function refresh(company:string,period:number,source:string) {
    controller?.abort();
    const request = new AbortController(); controller=request;
    busy=true;error='';data=null;updatedAt='';
    const timeout=setTimeout(()=>request.abort(),20000);
    try {
      const query=new URLSearchParams({tenant:company,days:String(period),channel:source});
      const response=await fetch(apiPrefix+'/admin/api/statistics?'+query,{credentials:'same-origin',signal:request.signal});
      if (!response.ok) throw new Error(response.status===401?'Your session expired. Sign in again.':'Statistics could not be loaded. Try refreshing.');
      const result:Stats=await response.json();
      if(controller===request&&!request.signal.aborted) {
        data=result;
        updatedAt=new Date().toLocaleTimeString('en-GB',{timeZone:'UTC',hour:'2-digit',minute:'2-digit'});
      }
    } catch(failure) {
      if(controller===request)error=request.signal.aborted?'Loading timed out. Try refreshing.':failure instanceof Error?failure.message:'Statistics are unavailable.';
    } finally {clearTimeout(timeout);if(controller===request)busy=false;}
  }
</script>

<section class="statistics" aria-label="Company statistics" aria-busy={busy}>
    <div class="toolbar"><div class="report-identity"><span class="eyebrow">Company report</span><h2>{tenant}</h2>{#if updatedAt}<p class="refreshed">Refreshed {updatedAt} UTC</p>{/if}</div><div class="filters"><label>Period<select bind:value={days}><option value={1}>Last 24 hours</option><option value={7}>Last 7 days</option><option value={30}>Last 30 days</option><option value={90}>Last 90 days</option><option value={180}>Last 180 days</option><option value={365}>Last 365 days</option></select></label><label>Channel<select bind:value={channel}><option value="all">All channels</option><option value="web">Web chat</option><option value="whatsapp">WhatsApp</option></select></label><button disabled={busy} on:click={()=>refresh(tenant,days,channel)}>{$t("Refresh")}</button></div></div>
  <nav aria-label="Statistics views">{#each views as item}<button class:active={view===item.id} aria-pressed={view===item.id} on:click={()=>view=item.id}>{item.label}</button>{/each}</nav>
    {#if busy}
      <p class="loading" role="status"><span class="loading-dot" aria-hidden="true"></span>Loading statistics for {tenant}…</p>
      <div class="statistics-skeleton" aria-hidden="true"><div class="metrics">{#each [1,2,3] as _}<div class="skeleton-card"><span></span><strong></strong><span></span></div>{/each}</div><div class="skeleton-chart"><span></span><div></div></div></div>
    {/if}
    {#if error}<p class="error" role="alert">{error}</p>{/if}
    {#if data}
      <div class="report-range"><p>{date(data.start)} – {date(data.end)} UTC</p><span>Compared with the previous {days} days · Private test chats excluded</span></div>
      {#if view!=='overview' && !data.current.inbound && !data.current.outbound && !data.current.errors}<div class="empty"><span class="empty-icon" aria-hidden="true">—</span><div><strong>No activity in this view</strong><p>No recorded customer activity for this period and channel. Try a longer period or another channel.</p></div></div>{/if}
      {#if view==='performance'}
        <PerformanceStatistics replies={data.replies} previous={data.previous_replies} daily={data.daily} hours={data.hours} topics={data.topics_daily} pipeline={data.pipeline}/>
      {:else if view==='products'}
        <ProductStatistics data={data.commerce} days={data.daily.map(row=>row.day)} {tenant} {csrf} {apiPrefix} canRecord={canRecordSales} bind:view={productView} bind:selected={selectedProduct} on:refresh={()=>refresh(tenant,days,channel)}/>
      {:else if view==='offers'}
        <div class="metrics"><article class="panel metric"><h3>Offer-related replies</h3><strong>{number(data.offers.offer_replies)}</strong></article><article class="panel metric"><h3>Conversations about offers</h3><strong>{number(data.offers.conversations)}</strong></article><article class="panel metric"><h3>Active offers now</h3><strong>{number(data.offers.items.filter(item=>item.status==='active').length)}</strong><p>Current configuration, independent of the activity period.</p></article></div>
        <article class="panel"><h3>Offer overview</h3><p>Per-offer figures count replies displaying the offer and distinct conversations in the selected period and channel. Tracking starts with this update; older replies are not attributed to individual offers.</p><!-- svelte-ignore a11y_no_noninteractive_tabindex (Keyboard users need to scroll the table horizontally on small screens.) -->
          <div class="table-wrap" role="region" aria-label="Current and previous offers" tabindex="0"><table class="offer-table"><caption>Current and previous offers</caption><thead><tr><th scope="col">Offer</th><th scope="col">Status now</th><th scope="col">Deal</th><th scope="col">Replies showing offer</th><th scope="col">{$t("Conversations")}</th></tr></thead><tbody>{#each data.offers.items as item}<tr><th scope="row">{item.title}<small> · {item.id}</small></th><td>{item.status}</td><td>{item.terms || 'Custom promotion'}</td><td>{number(item.replies)}</td><td>{number(item.conversations)}</td></tr>{:else}<tr><td colspan="5">No offers or tracked offer activity yet.</td></tr>{/each}</tbody></table></div><p class="hint">One reply may show several offers. Overall offer-related replies also include enquiries with no current offer. Redemptions, offer revenue and checkout eligibility are not tracked.</p><a href={base+'/offers'}>Manage offers</a></article>
      {:else if view==='overview'}
        <StatisticsOverview {data} {tenant} on:view={(event)=>view=event.detail}/>
      {:else if view==='sales'}
        <div class="metrics"><article class="panel metric"><h3>Conversations requesting a person</h3><strong>{number(data.current.handoffs)}</strong><p>{change(data.current.handoffs,data.previous.handoffs)}</p></article><article class="panel metric"><h3>Leads sharing contact details</h3><strong>{number(data.current.contacts)}</strong><p>{change(data.current.contacts,data.previous.contacts)}</p></article></div>
        <article class="panel"><h3>Current lead pipeline</h3><p>This is the company’s current lead status across all dates and channels. It is independent of the activity filters above.</p><div class="stage-list">{#each stages as stage}<div><span>{stage}</span><strong>{number(data.pipeline[stage] || 0)}</strong></div>{/each}</div><a href={base+'/pipeline'}>Manage sales pipeline</a><p class="hint">“Won” is an owner-managed status, not a verified payment. Revenue and historical lead conversion are not recorded here. Handoff and contact counts are separate measures, not sequential funnel stages.</p></article>
      {:else if view==='quality'}
        <div class="metrics"><article class="panel metric"><h3>Fallback replies</h3><strong>{number(data.current.fallbacks)}</strong><p>{percent(data.current.fallbacks,data.current.outbound)} of recorded agent replies</p></article><article class="panel metric"><h3>Recorded errors</h3><strong>{number(data.current.errors)}</strong><p>{change(data.current.errors,data.previous.errors)}</p></article><article class="panel metric"><h3>Customer messages per conversation</h3><strong>{data.current.sessions?(data.current.inbound/data.current.sessions).toFixed(1):'No data'}</strong><p>Activity measure; it does not measure customer satisfaction.</p></article></div>
        {#each [{title:'Topics handled',rows:data.intents,empty:'No reply topics recorded.'},{title:'Fallback topics',rows:data.fallbacks,empty:'No fallback replies recorded.'},{title:'Error breakdown',rows:data.errors,empty:'No errors recorded.'}] as group}
          <article class="panel"><h3>{group.title}</h3><!-- svelte-ignore a11y_no_noninteractive_tabindex (Keyboard users need to scroll the table horizontally on small screens.) -->
          <div class="table-wrap" role="region" aria-label="Top 20 by count in the selected period" tabindex="0"><table><caption>Top 20 by count in the selected period</caption><thead><tr><th scope="col">Category</th><th scope="col">Count</th></tr></thead><tbody>{#each group.rows as row}<tr><th scope="row">{row.label.replaceAll('_',' ')}</th><td>{number(row.count)}</td></tr>{:else}<tr><td colspan="2">{group.empty}</td></tr>{/each}</tbody></table></div></article>
        {/each}
        <article class="panel"><h3>Improve the answers</h3><p>Review fallback topics alongside Conversations, then update missing answers, prices or policies and try them in Test agent. Error counts show recorded events, not a live uptime check or a guarantee that every reply succeeded.</p><div class="links"><a href={base+'/conversations'}>Review conversations</a><a href={base+'/faqs'}>{$t("Questions & answers")}</a><a href={base+'/test'} data-sveltekit-reload>Test agent</a><a href={base+'/errors'}>{$t("Errors & health")}</a></div></article>
      {/if}
      <details class="report-notes"><summary>About these figures</summary><p>Activity uses the selected period and channel, with an equal-length previous period for comparison. Times are UTC and the first and last calendar days may be partial. Private Test agent chats are excluded.</p><p>Conversations are distinct channel and session pairs, not unique people. Daily conversation counts can include the same session on several days. Reply rates use messages with tracking IDs; generated replies do not prove delivery or a sale.</p><p>Figures include only retained records. Missing logging or replaced temporary storage can leave gaps. Fallbacks reflect response-engine flags, not an independent accuracy score. QR scans and customer satisfaction are not tracked.</p></details>
    {/if}
</section>

<style>
.statistics { display:grid; gap:18px; min-width:0; color:var(--v7-ink, #172b26); overflow-wrap:anywhere; }
  .toolbar, .filters, nav, .links { display:flex; flex-wrap:wrap; align-items:center; }
  .toolbar { justify-content:space-between; gap:20px; padding:18px 20px; background:var(--v7-surface, #fff); border:1px solid var(--v7-line, #e1e7e4); border-radius:12px; }
  .toolbar h2 { font-size:19px; letter-spacing:-.025em; line-height:1.3; }
  .toolbar p { margin:6px 0 0; font-size:11px; }
  .eyebrow { display:block; margin-bottom:7px; color:var(--v7-muted, #64716d); font-size:10px; font-weight:700; line-height:1.5; letter-spacing:.1em; text-transform:uppercase; }
  .toolbar .eyebrow { color:var(--v7-accent, #087f5b); }
  .filters { align-items:end; gap:10px; }
  .filters label { font-size:11px; }
  .filters select, .filters button { font-size:13px; }
  .filters button { background:var(--v7-accent, #087f5b); border-color:var(--v7-accent, #087f5b); color:#fff; }
  h2, h3 { margin:0; }
  h3 { font-size:16px; line-height:1.45; letter-spacing:-.015em; }
  p { color:var(--v7-muted, #64716d); line-height:1.6; }
  .hint { margin:0; font-size:12px; }
  .report-range { display:flex; flex-wrap:wrap; justify-content:space-between; gap:6px 16px; padding:0 2px; color:var(--v7-muted, #64716d); font-size:11px; line-height:1.6; }
  .report-range p { margin:0; }
  nav { flex-wrap:nowrap; overflow-x:auto; gap:4px; padding:5px; border:1px solid var(--v7-line, #e1e7e4); border-radius:10px; background:var(--v7-surface, #fff); scrollbar-width:thin; }
  button, select { box-sizing:border-box; max-width:100%; min-height:44px; padding:10px 13px; border:1px solid var(--v7-control-line, #cbd6d0); border-radius:8px; background:var(--v7-surface, #fff); color:var(--v7-ink, #172b26); font:inherit; }
  button { cursor:pointer; font-weight:600; }
  button:disabled { opacity:.6; cursor:wait; }
  nav button { flex:none; white-space:nowrap; border-color:transparent; background:transparent; color:var(--v7-muted, #64716d); font-size:12px; }
  nav button:hover { background:var(--v7-soft, #edf6f1); color:var(--v7-ink, #172b26); }
  nav button.active { background:var(--v7-soft, #edf6f1); color:var(--v7-accent, #087f5b); border-color:var(--v7-line, #e1e7e4); }
  label { display:grid; gap:6px; font-size:13px; font-weight:600; }
  a { display:inline-flex; align-items:center; min-height:44px; color:var(--v7-accent, #087f5b); font-size:13px; font-weight:600; text-underline-offset:3px; }
  .panel { min-width:0; padding:22px; border:1px solid var(--v7-line, #e1e7e4); border-radius:12px; background:var(--v7-surface, #fff); box-shadow:none; }
  .metrics { display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:14px; }
  .metric h3 { font-size:12px; font-weight:500; line-height:1.5; letter-spacing:0; color:var(--v7-muted, #64716d); }
  .metric strong { display:block; margin-top:14px; font-size:34px; line-height:1.15; letter-spacing:-.045em; font-variant-numeric:tabular-nums; color:var(--v7-ink, #172b26); }
  .metric p { margin:10px 0 0; font-size:11px; }
  .metric:first-child strong { color:var(--v7-accent, #087f5b); }
  .table-wrap { overflow-x:auto; margin-top:16px; border:1px solid var(--v7-line, #e1e7e4); border-radius:8px; }
  table { width:100%; min-width:640px; border-collapse:collapse; text-align:left; font-size:12px; overflow-wrap:normal; }
  th, td { padding:13px 14px; border-bottom:1px solid var(--v7-line, #e1e7e4); vertical-align:top; font-variant-numeric:tabular-nums; }
  thead th { background:var(--v7-canvas, #f5f7f7); color:var(--v7-muted, #64716d); font-size:11px; font-weight:600; }
  tbody th { font-weight:500; }
  tbody tr:hover { background:var(--v7-soft, #edf6f1); }
  tbody tr:last-child :is(th, td) { border-bottom:0; }
  caption { padding:12px 14px; border-bottom:1px solid var(--v7-line, #e1e7e4); text-align:left; color:var(--v7-muted, #64716d); font-size:11px; }
  .offer-table { min-width:680px; }
  .offer-table th:first-child { min-width:140px; }
  .offer-table td:nth-child(3) { min-width:220px; }
  .stage-list { display:grid; grid-template-columns:repeat(auto-fit, minmax(130px, 1fr)); gap:10px; margin:18px 0; }
  .stage-list div { display:grid; gap:8px; padding:14px; border:1px solid var(--v7-line, #e1e7e4); border-radius:8px; background:var(--v7-canvas, #f5f7f7); }
  .stage-list span { font-size:12px; color:var(--v7-muted, #64716d); }
  .stage-list strong { font-size:25px; font-variant-numeric:tabular-nums; letter-spacing:-.03em; }
  details { margin-top:18px; padding-top:12px; border-top:1px solid var(--v7-line, #e1e7e4); }
  summary { min-height:44px; align-content:center; cursor:pointer; font-size:12px; font-weight:600; color:var(--v7-accent, #087f5b); }
  .links { gap:16px; }
  .loading, .error { margin:0; padding:14px 16px; border:1px solid var(--v7-line, #e1e7e4); border-radius:8px; font-size:13px; }
  .loading { display:flex; gap:10px; align-items:center; color:var(--v7-accent, #087f5b); background:var(--v7-soft, #edf6f1); }
  .error { color:#a12622; background:#fff5f3; border-color:#f1d6d1; }
  .empty { display:flex; align-items:center; gap:14px; padding:18px; border:1px solid var(--v7-line, #e1e7e4); border-radius:12px; background:var(--v7-surface, #fff); }
  .empty strong { font-size:14px; color:var(--v7-ink, #172b26); }
  .empty p { margin:5px 0 0; font-size:12px; }
  .empty-icon { display:grid; place-items:center; flex-shrink:0; width:40px; height:40px; border-radius:8px; background:var(--v7-soft, #edf6f1); color:var(--v7-accent, #087f5b); font-size:22px; }
  .loading-dot { width:12px; height:12px; border:2px solid #c5ded0; border-top-color:var(--v7-accent, #087f5b); border-radius:50%; animation:statistics-spin .8s linear infinite; }
  .statistics-skeleton { display:grid; gap:18px; }
  .report-notes { margin-top:0; padding:8px 16px; border:1px solid var(--v7-line, #e1e7e4); border-radius:10px; background:var(--v7-surface, #fff); }
  .report-notes p { margin:0 0 12px; font-size:12px; max-width:1000px; }
  .skeleton-card, .skeleton-chart { padding:22px; border:1px solid var(--v7-line, #e1e7e4); border-radius:12px; background:var(--v7-surface, #fff); }
  .skeleton-card span, .skeleton-card strong, .skeleton-chart > span { display:block; height:10px; border-radius:4px; background:var(--v7-canvas, #f5f7f7); }
  .skeleton-card span:first-child { width:65%; }
  .skeleton-card strong { height:32px; width:42%; margin:18px 0; }
  .skeleton-card span:last-child { width:85%; }
  .skeleton-chart > span { width:180px; }
  .skeleton-chart > div { height:180px; margin-top:24px; border-radius:8px; background:repeating-linear-gradient(0deg, transparent 0, transparent 43px, #e1e7e4 44px, #e1e7e4 45px); }
  :is(button, a, select, summary, .table-wrap):focus-visible { outline:3px solid var(--v7-focus, #81baa1); outline-offset:3px; }
  @keyframes statistics-spin { to { transform:rotate(360deg); } }
  @media(max-width:1000px) { .metrics { grid-template-columns:repeat(2, minmax(0, 1fr)); } .toolbar { align-items:flex-start; } }
  @media(max-width:600px) { .panel, .toolbar { padding:16px; } .toolbar { gap:18px; } .toolbar h2 { font-size:19px; } nav button { flex:none; } .filters { width:100%; } .filters label { flex:1 1 140px; } .filters select, .filters button { width:100%; } .metrics { grid-template-columns:1fr; } .metric strong { font-size:32px; } .empty { align-items:flex-start; } }
  @media(prefers-reduced-motion:reduce) { .loading-dot { animation:none; } }
</style>
