<script lang="ts">
  import { t } from './i18n';
  import { onMount, onDestroy } from 'svelte';
  import { base } from '$app/paths';
  import PerformanceStatistics from './PerformanceStatistics.svelte';
  import ProductStatistics from './ProductStatistics.svelte';
  import type {ReplyReport,Commerce} from './statisticsTypes';
  export let tenant: string;
  export let csrf = '';
  export let canRecordSales = false;
  export let apiPrefix = '';
  type Metrics = {inbound:number;outbound:number;sessions:number;fallbacks:number;errors:number;handoffs:number;contacts:number};
  type Breakdown = {label:string;count:number};
  type Stats = {tenant:string;start:string;end:string;previous_start:string;current:Metrics;previous:Metrics;
    daily:(Metrics & {day:string})[];channels:(Metrics & {channel:string})[];
    intents:Breakdown[];errors:Breakdown[];fallbacks:Breakdown[];pipeline:Record<string,number>;
    replies:ReplyReport;previous_replies:ReplyReport;hours:{hour:string;inbound:number;outbound:number}[];
    topics_daily:{day:string;topic:string;count:number}[];commerce:Commerce;offers:{offer_replies:number;conversations:number;items:{id:string;title:string;status:string;terms:string;replies:number;conversations:number}[]}};
  const metrics: {key:keyof Metrics;label:string}[] = [{key:'sessions',label:'Active conversations'},{key:'inbound',label:'Customer messages'},
    {key:'outbound',label:'Agent replies'},{key:'handoffs',label:'Conversations requesting a person'},{key:'contacts',label:'Leads sharing contact details'},{key:'errors',label:'Recorded errors'}];
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
  let mounted = false;
  let controller:AbortController|undefined;
  const number = (value:number) => value.toLocaleString('en-GB');
  const percent = (part:number,total:number) => total ? (100*part/total).toFixed(1)+'%' : 'No data';
  const date = (value:string) => new Date(value).toLocaleString('en-GB',{timeZone:'UTC',dateStyle:'medium',timeStyle:'short'});
  const change = (current:number,previous:number) => !previous ? current ? 'No activity in previous period' : 'No change' : `${current>=previous?'+':''}${((current-previous)/previous*100).toFixed(1)}% vs previous period`;
  $: if (mounted) refresh(tenant,days,channel);
  $: chartMax = data ? Math.max(1,...data.daily.flatMap(row=>[row.inbound,row.outbound])) : 1;
  function points(key:'inbound'|'outbound') { return data?.daily.map((row,index)=>`${20+index*860/Math.max(1,data!.daily.length-1)},${180-row[key]*160/chartMax}`).join(' ') || ''; }
  onMount(()=>{mounted=true;});
  onDestroy(()=>{controller?.abort();controller=undefined;});
  async function refresh(company:string,period:number,source:string) {
    controller?.abort();
    const request = new AbortController(); controller=request;
    busy=true;error='';data=null;
    const timeout=setTimeout(()=>request.abort(),20000);
    try {
      const query=new URLSearchParams({tenant:company,days:String(period),channel:source});
      const response=await fetch(apiPrefix+'/admin/api/statistics?'+query,{credentials:'same-origin',signal:request.signal});
      if (!response.ok) throw new Error(response.status===401?'Your session expired. Sign in again.':'Statistics could not be loaded. Try refreshing.');
      const result:Stats=await response.json();
      if(controller===request&&!request.signal.aborted)data=result;
    } catch(failure) {
      if(controller===request)error=request.signal.aborted?'Loading timed out. Try refreshing.':failure instanceof Error?failure.message:'Statistics are unavailable.';
    } finally {clearTimeout(timeout);if(controller===request)busy=false;}
  }
</script>

<section class="statistics" aria-label="Company statistics" aria-busy={busy}>
  <nav aria-label="Statistics views">{#each views as item}<button class:active={view===item.id} aria-pressed={view===item.id} on:click={()=>view=item.id}>{item.label}</button>{/each}</nav>
    <div class="toolbar"><div><span class="eyebrow">Company analytics</span><h2>{tenant} · recorded activity</h2><p>Compare customer activity and find areas that need attention.</p></div><div class="filters"><label>Period<select bind:value={days}><option value={1}>Last 24 hours</option><option value={7}>Last 7 days</option><option value={30}>Last 30 days</option><option value={90}>Last 90 days</option><option value={180}>Last 180 days</option><option value={365}>Last 365 days</option></select></label><label>Channel<select bind:value={channel}><option value="all">All channels</option><option value="web">Web chat</option><option value="whatsapp">WhatsApp</option></select></label><button disabled={busy} on:click={()=>refresh(tenant,days,channel)}>{$t("Refresh")}</button></div></div>
    {#if busy}
      <p class="loading" role="status"><span class="loading-dot" aria-hidden="true"></span>Loading statistics for {tenant}…</p>
      <div class="statistics-skeleton" aria-hidden="true"><div class="metrics">{#each [1,2,3] as _}<div class="skeleton-card"><span></span><strong></strong><span></span></div>{/each}</div><div class="skeleton-chart"><span></span><div></div></div></div>
    {/if}
    {#if error}<p class="error" role="alert">{error}</p>{/if}
    {#if data}
      <p class="hint">{date(data.start)} – {date(data.end)} UTC. Compared with the preceding {days} days. Private Test agent chats are excluded.</p>
      {#if !data.current.inbound && !data.current.outbound && !data.current.errors}<div class="empty"><span class="empty-icon" aria-hidden="true">↗</span><div><strong>No activity in this view</strong><p>No recorded customer activity for this period and channel. Try a longer period or another channel.</p></div></div>{/if}
      {#if view==='performance'}
        <PerformanceStatistics replies={data.replies} previous={data.previous_replies} daily={data.daily} hours={data.hours} topics={data.topics_daily} pipeline={data.pipeline}/>
      {:else if view==='products'}
        <ProductStatistics data={data.commerce} days={data.daily.map(row=>row.day)} {tenant} {csrf} {apiPrefix} canRecord={canRecordSales} bind:view={productView} bind:selected={selectedProduct} on:refresh={()=>refresh(tenant,days,channel)}/>
      {:else if view==='offers'}
        <div class="metrics"><article class="panel metric"><h3>Offer-related replies</h3><strong>{number(data.offers.offer_replies)}</strong></article><article class="panel metric"><h3>Conversations about offers</h3><strong>{number(data.offers.conversations)}</strong></article><article class="panel metric"><h3>Active offers now</h3><strong>{number(data.offers.items.filter(item=>item.status==='active').length)}</strong><p>Current configuration, independent of the activity period.</p></article></div>
        <article class="panel"><h3>Offer overview</h3><p>Per-offer figures count replies displaying the offer and distinct conversations in the selected period and channel. Tracking starts with this update; older replies are not attributed to individual offers.</p><!-- svelte-ignore a11y_no_noninteractive_tabindex (Keyboard users need to scroll the table horizontally on small screens.) -->
          <div class="table-wrap" role="region" aria-label="Current and previous offers" tabindex="0"><table class="offer-table"><caption>Current and previous offers</caption><thead><tr><th scope="col">Offer</th><th scope="col">Status now</th><th scope="col">Deal</th><th scope="col">Replies showing offer</th><th scope="col">{$t("Conversations")}</th></tr></thead><tbody>{#each data.offers.items as item}<tr><th scope="row">{item.title}<small> · {item.id}</small></th><td>{item.status}</td><td>{item.terms || 'Custom promotion'}</td><td>{number(item.replies)}</td><td>{number(item.conversations)}</td></tr>{:else}<tr><td colspan="5">No offers or tracked offer activity yet.</td></tr>{/each}</tbody></table></div><p class="hint">One reply may show several offers. Overall offer-related replies also include enquiries with no current offer. Redemptions, offer revenue and checkout eligibility are not tracked.</p><a href={base+'/offers'}>Manage offers</a></article>
      {:else if view==='overview'}
        <div class="metrics">{#each metrics as metric}<article class="panel metric"><h3>{metric.label}</h3><strong>{number(data.current[metric.key])}</strong><p>{change(data.current[metric.key],data.previous[metric.key])}</p></article>{/each}</div>
        <article class="panel activity-chart"><div class="chart-heading"><div><span class="eyebrow">Conversation rhythm</span><h3>Daily message activity</h3></div><p class="legend"><span>━ Customer messages</span><span>┄ Agent replies</span></p></div>
          <svg viewBox="0 0 900 210" role="img" aria-label="Daily customer messages and agent replies. Exact values are in the daily table below.">{#each [0,0.5,1] as ratio}<line x1="20" y1={180-ratio*160} x2="880" y2={180-ratio*160} stroke="#e2eade" stroke-dasharray={ratio?'4 5':undefined}/>{/each}<text x="20" y="14">{number(chartMax)}</text><polygon points={'20,180 '+points('inbound')+' 880,180'} fill="#007d7010"/><polyline points={points('inbound')} fill="none" stroke="#007d70" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/><polyline points={points('outbound')} fill="none" stroke="#748a35" stroke-width="3" stroke-dasharray="6 4" stroke-linecap="round"/><text x="20" y="205">{data.daily[0]?.day}</text><text x="880" y="205" text-anchor="end">{data.daily[data.daily.length-1]?.day}</text></svg>
          <p class="hint">UTC calendar days; the first and last day may be partial. Days with no recorded activity appear as zero.</p>
          <details><summary>View daily figures</summary><!-- svelte-ignore a11y_no_noninteractive_tabindex (Keyboard users need to scroll the table horizontally on small screens.) -->
          <div class="table-wrap" role="region" aria-label="Recorded daily totals" tabindex="0"><table><caption>Recorded daily totals</caption><thead><tr><th scope="col">Date (UTC)</th><th scope="col">Customer messages</th><th scope="col">Agent replies</th><th scope="col">{$t("Conversations")}</th><th scope="col">Fallbacks</th><th scope="col">Errors</th></tr></thead><tbody>{#each data.daily as row}<tr><th scope="row">{row.day}</th><td>{number(row.inbound)}</td><td>{number(row.outbound)}</td><td>{number(row.sessions)}</td><td>{number(row.fallbacks)}</td><td>{number(row.errors)}</td></tr>{/each}</tbody></table></div></details>
        </article>
        <article class="panel"><span class="eyebrow">Where conversations happen</span><h3>Channel comparison</h3><div class="channel-cards">{#each data.channels as row}<div class="channel-card"><div><span>{row.channel==='whatsapp'?'WhatsApp':'Web chat'}</span><strong>{number(row.inbound)} <small>customer messages</small></strong></div><div class="channel-track" aria-hidden="true"><span style:width={Math.min(100,row.inbound/Math.max(1,data.current.inbound)*100)+'%'}></span></div><p>{number(row.sessions)} active conversations · {number(row.outbound)} agent replies</p></div>{/each}</div><!-- svelte-ignore a11y_no_noninteractive_tabindex (Keyboard users need to scroll the table horizontally on small screens.) -->
          <div class="table-wrap" role="region" aria-label="Activity in the selected period" tabindex="0"><table><caption>Activity in the selected period</caption><thead><tr><th scope="col">Channel</th><th scope="col">{$t("Conversations")}</th><th scope="col">Customer messages</th><th scope="col">Agent replies</th><th scope="col">Fallback rate</th><th scope="col">Errors</th></tr></thead><tbody>{#each data.channels as row}<tr><th scope="row">{row.channel==='whatsapp'?'WhatsApp':'Web chat'}</th><td>{number(row.sessions)}</td><td>{number(row.inbound)}</td><td>{number(row.outbound)}</td><td>{percent(row.fallbacks,row.outbound)}</td><td>{number(row.errors)}</td></tr>{:else}<tr><td colspan="6">No channel activity recorded.</td></tr>{/each}</tbody></table></div><p class="hint">Conversations are distinct channel/session pairs active in the period, not unique people. Daily conversation counts can include the same conversation on several days.</p></article>
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
      <p class="hint">Figures include only retained records. Missing logging or replaced ephemeral storage can leave gaps. A fallback is a reply flagged as a fallback by the response engine; it is not an independent accuracy score. QR scans are not tracked.</p>
    {/if}
</section>

<style>
  .offer-table{min-width:680px}.offer-table th:first-child{min-width:140px}.offer-table td:nth-child(3){min-width:220px}
  .statistics{display:grid;gap:20px;min-width:0;overflow-wrap:anywhere}nav,.toolbar,.filters,.links,.legend{display:flex;flex-wrap:wrap;gap:12px;align-items:center}.toolbar{justify-content:space-between;gap:24px;padding:28px;background:radial-gradient(ellipse at 95% 0,#3b664a,#203b30 70%);border:1px solid #31553e;border-radius:22px;color:#fff;box-shadow:0 12px 35px #203b3014}.toolbar h2{font-size:clamp(22px,2.5vw,30px);letter-spacing:-.04em;line-height:1.25}.toolbar p{color:#cadace;font-size:13px;max-width:420px;margin:10px 0 0}.eyebrow{display:block;font-size:10px;line-height:1.5;text-transform:uppercase;letter-spacing:.13em;font-weight:700;margin-bottom:8px;color:#658168}.toolbar .eyebrow{color:#d6f58a}.filters{align-items:end}.filters label{font-size:11px;color:#d9e7dc}.filters select{font-size:13px}.filters button{background:#d6f58a;border-color:#d6f58a;color:#203b30;font-size:13px}h2,h3{margin:0}h2{font-size:21px}h3{font-size:17px}p{color:var(--v7-muted);line-height:1.6}.hint{font-size:12px;margin:0}
  button,select{box-sizing:border-box;border:1px solid var(--v7-control-line, #b5c5bc);background:white;border-radius:10px;padding:11px 13px;color:var(--v7-ink);font:inherit;min-height:44px;max-width:100%}button{font-weight:600;cursor:pointer}button:disabled{opacity:.6;cursor:wait}button.active{background:var(--v7-accent);border-color:var(--v7-accent);color:white}label{display:grid;gap:6px;font-size:14px;font-weight:600}a{color:var(--v7-accent)}.panel{padding:24px;border:1px solid var(--v7-line);border-radius:var(--v7-radius, 18px);background:white;min-width:0;box-shadow:var(--v7-card-shadow, 0 8px 28px #203b3008);}
  .metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}.metric strong{display:block;font-size:40px;margin-top:18px;letter-spacing:-.055em;font-variant-numeric:tabular-nums;color:#234c39}.metric p{margin-bottom:0;font-size:12px}.metric h3{font-size:12px;line-height:1.5;color:#64766b}.metric:first-child{background:linear-gradient(135deg,#eef5e6,#f8fbf6);border-color:#cbdcc3}.metric:first-child strong{color:#203b30}.legend{font-size:12px;margin:0}.legend span:first-child{color:var(--v7-accent)}.legend span:last-child{color:#748a35}svg{display:block;width:100%;height:auto;min-height:140px;margin-top:20px}svg text{font:11px system-ui;fill:var(--v7-muted)}.table-wrap{overflow-x:auto;margin-top:16px;border:1px solid var(--v7-line);border-radius:12px;}table{border-collapse:collapse;width:100%;min-width:640px;text-align:left;font-size:13px;overflow-wrap:normal}th,td{padding:14px 12px;border-bottom:1px solid #e2e7df;vertical-align:top;font-variant-numeric:tabular-nums;}thead th{background:var(--v7-soft, #f0f6f2);font-size:11px;color:#5d7264}tbody th{font-weight:500}tbody tr:hover{background:#f8fbf7}tbody tr:last-child :is(th,td){border-bottom:0}caption{text-align:left;color:var(--v7-muted);font-size:12px;padding:12px;border-bottom:1px solid var(--v7-line)}.stage-list{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;margin:20px 0}.stage-list div{display:grid;gap:8px;padding:16px;background:var(--v7-soft, #f0f6f2);border-radius:12px}.stage-list strong{font-size:26px}details{margin-top:18px}summary{cursor:pointer;font-weight:600}.error{color:#a12622}.empty{display:flex;align-items:center;gap:16px;padding:20px;background:#edf4ef;border-radius:16px;margin:0;border:1px solid #d5e4d6}.empty strong{font-size:14px;color:#365743}.empty p{margin:4px 0 0;font-size:13px}.empty-icon{display:grid;place-items:center;flex-shrink:0;width:42px;height:42px;background:#dceace;color:#446d36;border-radius:12px;font-size:22px}:is(button,a,select,summary):focus-visible{outline:3px solid #8bcdc0;outline-offset:3px}
  @media(max-width:600px){.panel{padding:16px}nav button{flex:1 1 130px}.filters{width:100%}.filters label{flex:1 1 140px}}
  nav { padding:6px; background:var(--v7-surface); border:1px solid var(--v7-line); border-radius:14px; gap:6px; }
    nav button:not(.active) { border-color:transparent; }
    .metric { border-top:3px solid #91b883; }
  .loading,.error { margin:0; padding:16px 18px; border-radius:12px; font-size:14px; }
  .loading { color:var(--v7-accent); background:var(--v7-soft, #f0f6f2); }
  .error { background:#fff2f0; }
  .table-wrap:focus-visible { outline:3px solid #8bcdc0; outline-offset:3px; }
  .chart-heading{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:16px}.activity-chart{background:linear-gradient(180deg,#fff,#fcfdf9)}.channel-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,230px),1fr));gap:12px;margin-top:20px}.channel-card{padding:18px;background:#f7faf5;border:1px solid #e0e8dc;border-radius:14px}.channel-card>div:first-child{display:grid;gap:8px}.channel-card>div>span{font-size:12px;color:#5c7563;font-weight:600}.channel-card strong{font-size:22px;letter-spacing:-.04em;color:#234c39;font-variant-numeric:tabular-nums}.channel-card small{font-size:11px;font-weight:400;color:var(--v7-muted);letter-spacing:0}.channel-track{height:6px;border-radius:6px;background:#e4ecd9;margin-top:14px;overflow:hidden}.channel-track span{display:block;height:100%;border-radius:6px;background:linear-gradient(90deg,#3f7652,#93b55c)}.channel-card p{font-size:11px;margin:10px 0 0}
  .loading{display:flex;gap:10px;align-items:center}.loading-dot{width:12px;height:12px;border:2px solid #c7ddce;border-top-color:#007d70;border-radius:50%;animation:statistics-spin .8s linear infinite}.statistics-skeleton{display:grid;gap:20px}.skeleton-card,.skeleton-chart{padding:24px;background:#fff;border:1px solid var(--v7-line);border-radius:18px}.skeleton-card span,.skeleton-card strong,.skeleton-chart>span{display:block;height:10px;border-radius:8px;background:#edf2e9}.skeleton-card span:first-child{width:65%}.skeleton-card strong{height:36px;width:42%;margin:20px 0}.skeleton-card span:last-child{width:85%}.skeleton-chart>span{width:180px}.skeleton-chart>div{height:180px;margin-top:24px;border-radius:12px;background:repeating-linear-gradient(0deg,transparent 0,transparent 43px,#edf2e9 44px,#edf2e9 45px)}
  @keyframes statistics-spin{to{transform:rotate(360deg)}}
  @media(max-width:1000px){.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.toolbar{padding:24px}}
  @media(max-width:600px){.filters select{width:100%}.metrics{grid-template-columns:1fr}.toolbar{padding:20px}.toolbar h2{font-size:24px}.filters button{width:100%}.empty{align-items:flex-start}.metric strong{font-size:36px}.channel-cards{grid-template-columns:1fr}}
  @media(prefers-reduced-motion:reduce){.loading-dot{animation:none}}
</style>
