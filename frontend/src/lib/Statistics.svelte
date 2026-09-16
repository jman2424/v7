<script lang="ts">
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
  $: if (mounted) refresh(days,channel);
  $: chartMax = data ? Math.max(1,...data.daily.flatMap(row=>[row.inbound,row.outbound])) : 1;
  function points(key:'inbound'|'outbound') { return data?.daily.map((row,index)=>`${20+index*860/Math.max(1,data!.daily.length-1)},${180-row[key]*160/chartMax}`).join(' ') || ''; }
  onMount(()=>{mounted=true;});
  onDestroy(()=>controller?.abort());
  async function refresh(period:number,source:string) {
    controller?.abort();
    const request = new AbortController(); controller=request;
    busy=true;error='';data=null;
    const timeout=setTimeout(()=>request.abort(),20000);
    try {
      const query=new URLSearchParams({tenant,days:String(period),channel:source});
      const response=await fetch(apiPrefix+'/admin/api/statistics?'+query,{credentials:'same-origin',signal:request.signal});
      if (!response.ok) throw new Error(response.status===401?'Your session expired. Sign in again.':'Statistics could not be loaded. Try refreshing.');
      const result:Stats=await response.json();
      if(controller===request&&!request.signal.aborted)data=result;
    } catch(failure) {
      if(controller===request)error=request.signal.aborted?'Loading timed out. Try refreshing.':failure instanceof Error?failure.message:'Statistics are unavailable.';
    } finally {clearTimeout(timeout);if(controller===request)busy=false;}
  }
</script>

<section class="statistics" aria-label="Company statistics">
  <nav aria-label="Statistics views">{#each views as item}<button class:active={view===item.id} aria-pressed={view===item.id} on:click={()=>view=item.id}>{item.label}</button>{/each}</nav>
    <div class="toolbar"><div><h2>{tenant} · recorded activity</h2><p>Compare customer activity and find areas that need attention.</p></div><div class="filters"><label>Period<select bind:value={days}><option value={1}>Last 24 hours</option><option value={7}>Last 7 days</option><option value={30}>Last 30 days</option><option value={90}>Last 90 days</option><option value={180}>Last 180 days</option><option value={365}>Last 365 days</option></select></label><label>Channel<select bind:value={channel}><option value="all">All channels</option><option value="web">Web chat</option><option value="whatsapp">WhatsApp</option></select></label><button disabled={busy} on:click={()=>refresh(days,channel)}>Refresh</button></div></div>
    {#if busy}<p role="status">Loading statistics…</p>{/if}
    {#if error}<p class="error" role="alert">{error}</p>{/if}
    {#if data}
      <p class="hint">{date(data.start)} – {date(data.end)} UTC. Compared with the preceding {days} days. Private Test agent chats are excluded.</p>
      {#if !data.current.inbound && !data.current.outbound && !data.current.errors}<p class="empty">No recorded customer activity for this period and channel. Try a longer period or another channel.</p>{/if}
      {#if view==='performance'}
        <PerformanceStatistics replies={data.replies} previous={data.previous_replies} daily={data.daily} hours={data.hours} topics={data.topics_daily} pipeline={data.pipeline}/>
      {:else if view==='products'}
        <ProductStatistics data={data.commerce} days={data.daily.map(row=>row.day)} {tenant} {csrf} {apiPrefix} canRecord={canRecordSales} bind:view={productView} bind:selected={selectedProduct} on:refresh={()=>refresh(days,channel)}/>
      {:else if view==='offers'}
        <div class="metrics"><article class="panel metric"><h3>Offer-related replies</h3><strong>{number(data.offers.offer_replies)}</strong></article><article class="panel metric"><h3>Conversations about offers</h3><strong>{number(data.offers.conversations)}</strong></article><article class="panel metric"><h3>Active offers now</h3><strong>{number(data.offers.items.filter(item=>item.status==='active').length)}</strong><p>Current configuration, independent of the activity period.</p></article></div>
        <article class="panel"><h3>Offer overview</h3><p>Per-offer figures count replies displaying the offer and distinct conversations in the selected period and channel. Tracking starts with this update; older replies are not attributed to individual offers.</p><div class="table-wrap"><table class="offer-table"><caption>Current and previous offers</caption><thead><tr><th>Offer</th><th>Status now</th><th>Deal</th><th>Replies showing offer</th><th>Conversations</th></tr></thead><tbody>{#each data.offers.items as item}<tr><th>{item.title}<small> · {item.id}</small></th><td>{item.status}</td><td>{item.terms || 'Custom promotion'}</td><td>{number(item.replies)}</td><td>{number(item.conversations)}</td></tr>{:else}<tr><td colspan="5">No offers or tracked offer activity yet.</td></tr>{/each}</tbody></table></div><p class="hint">One reply may show several offers. Overall offer-related replies also include enquiries with no current offer. Redemptions, offer revenue and checkout eligibility are not tracked.</p><a href={base+'/offers'}>Manage offers</a></article>
      {:else if view==='overview'}
        <div class="metrics">{#each metrics as metric}<article class="panel metric"><h3>{metric.label}</h3><strong>{number(data.current[metric.key])}</strong><p>{change(data.current[metric.key],data.previous[metric.key])}</p></article>{/each}</div>
        <article class="panel"><h3>Daily message activity</h3><p class="legend"><span>━ Customer messages</span><span>┄ Agent replies</span></p>
          <svg viewBox="0 0 900 210" role="img" aria-label="Daily customer messages and agent replies. Exact values are in the daily table below."><line x1="20" y1="180" x2="880" y2="180" stroke="#bbc4bc"/><text x="20" y="14">{number(chartMax)}</text><polyline points={points('inbound')} fill="none" stroke="#007d70" stroke-width="3"/><polyline points={points('outbound')} fill="none" stroke="#596f9c" stroke-width="3" stroke-dasharray="6 4"/><text x="20" y="205">{data.daily[0]?.day}</text><text x="880" y="205" text-anchor="end">{data.daily[data.daily.length-1]?.day}</text></svg>
          <p class="hint">UTC calendar days; the first and last day may be partial. Days with no recorded activity appear as zero.</p>
          <details><summary>View daily figures</summary><div class="table-wrap"><table><caption>Recorded daily totals</caption><thead><tr><th>Date (UTC)</th><th>Customer messages</th><th>Agent replies</th><th>Conversations</th><th>Fallbacks</th><th>Errors</th></tr></thead><tbody>{#each data.daily as row}<tr><th>{row.day}</th><td>{number(row.inbound)}</td><td>{number(row.outbound)}</td><td>{number(row.sessions)}</td><td>{number(row.fallbacks)}</td><td>{number(row.errors)}</td></tr>{/each}</tbody></table></div></details>
        </article>
        <article class="panel"><h3>Channel comparison</h3><div class="table-wrap"><table><caption>Activity in the selected period</caption><thead><tr><th>Channel</th><th>Conversations</th><th>Customer messages</th><th>Agent replies</th><th>Fallback rate</th><th>Errors</th></tr></thead><tbody>{#each data.channels as row}<tr><th>{row.channel==='whatsapp'?'WhatsApp':'Web chat'}</th><td>{number(row.sessions)}</td><td>{number(row.inbound)}</td><td>{number(row.outbound)}</td><td>{percent(row.fallbacks,row.outbound)}</td><td>{number(row.errors)}</td></tr>{:else}<tr><td colspan="6">No channel activity recorded.</td></tr>{/each}</tbody></table></div><p class="hint">Conversations are distinct channel/session pairs active in the period, not unique people. Daily conversation counts can include the same conversation on several days.</p></article>
      {:else if view==='sales'}
        <div class="metrics"><article class="panel metric"><h3>Conversations requesting a person</h3><strong>{number(data.current.handoffs)}</strong><p>{change(data.current.handoffs,data.previous.handoffs)}</p></article><article class="panel metric"><h3>Leads sharing contact details</h3><strong>{number(data.current.contacts)}</strong><p>{change(data.current.contacts,data.previous.contacts)}</p></article></div>
        <article class="panel"><h3>Current lead pipeline</h3><p>This is the company’s current lead status across all dates and channels. It is independent of the activity filters above.</p><div class="stage-list">{#each stages as stage}<div><span>{stage}</span><strong>{number(data.pipeline[stage] || 0)}</strong></div>{/each}</div><a href={base+'/pipeline'}>Manage sales pipeline</a><p class="hint">“Won” is an owner-managed status, not a verified payment. Revenue and historical lead conversion are not recorded here. Handoff and contact counts are separate measures, not sequential funnel stages.</p></article>
      {:else if view==='quality'}
        <div class="metrics"><article class="panel metric"><h3>Fallback replies</h3><strong>{number(data.current.fallbacks)}</strong><p>{percent(data.current.fallbacks,data.current.outbound)} of recorded agent replies</p></article><article class="panel metric"><h3>Recorded errors</h3><strong>{number(data.current.errors)}</strong><p>{change(data.current.errors,data.previous.errors)}</p></article><article class="panel metric"><h3>Customer messages per conversation</h3><strong>{data.current.sessions?(data.current.inbound/data.current.sessions).toFixed(1):'No data'}</strong><p>Activity measure; it does not measure customer satisfaction.</p></article></div>
        {#each [{title:'Topics handled',rows:data.intents,empty:'No reply topics recorded.'},{title:'Fallback topics',rows:data.fallbacks,empty:'No fallback replies recorded.'},{title:'Error breakdown',rows:data.errors,empty:'No errors recorded.'}] as group}
          <article class="panel"><h3>{group.title}</h3><div class="table-wrap"><table><caption>Top 20 by count in the selected period</caption><thead><tr><th>Category</th><th>Count</th></tr></thead><tbody>{#each group.rows as row}<tr><th>{row.label.replaceAll('_',' ')}</th><td>{number(row.count)}</td></tr>{:else}<tr><td colspan="2">{group.empty}</td></tr>{/each}</tbody></table></div></article>
        {/each}
        <article class="panel"><h3>Improve the answers</h3><p>Review fallback topics alongside Conversations, then update missing answers, prices or policies and try them in Test agent. Error counts show recorded events, not a live uptime check or a guarantee that every reply succeeded.</p><div class="links"><a href={base+'/conversations'}>Review conversations</a><a href={base+'/faqs'}>Questions &amp; answers</a><a href={base+'/test'} data-sveltekit-reload>Test agent</a><a href={base+'/errors'}>Errors &amp; health</a></div></article>
      {/if}
      <p class="hint">Figures include only retained records. Missing logging or replaced ephemeral storage can leave gaps. A fallback is a reply flagged as a fallback by the response engine; it is not an independent accuracy score. QR scans are not tracked.</p>
    {/if}
</section>

<style>
  .offer-table{min-width:680px}.offer-table th:first-child{min-width:140px}.offer-table td:nth-child(3){min-width:220px}
  .statistics{display:grid;gap:20px;min-width:0;overflow-wrap:anywhere}nav,.toolbar,.filters,.links,.legend{display:flex;flex-wrap:wrap;gap:12px;align-items:center}.toolbar{justify-content:space-between}.filters{align-items:end}h2,h3{margin:0}h2{font-size:21px}h3{font-size:17px}p{color:#526359;line-height:1.6}.hint{font-size:13px;margin:0}
  button,select{box-sizing:border-box;border:1px solid #bbc4bc;background:white;border-radius:6px;padding:11px 13px;color:#26332b;font:inherit;min-height:44px;max-width:100%}button{font-weight:600;cursor:pointer}button:disabled{opacity:.6;cursor:wait}button.active{background:#007d70;border-color:#007d70;color:white}label{display:grid;gap:6px;font-size:14px;font-weight:600}a{color:#007d70}.panel{padding:24px;border:1px solid #d9ddd7;border-radius:8px;background:white;min-width:0}
  .metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,230px),1fr));gap:16px}.metric strong{display:block;font-size:32px;margin-top:14px}.metric p{margin-bottom:0;font-size:13px}.metric h3{font-size:14px}.legend span:first-child{color:#007d70}.legend span:last-child{color:#596f9c}svg{display:block;width:100%;height:auto;min-height:120px}svg text{font:12px system-ui;fill:#526359}.table-wrap{overflow-x:auto;margin-top:16px}table{border-collapse:collapse;width:100%;text-align:left;font-size:14px}th,td{padding:12px;border-bottom:1px solid #e2e7df}thead th{background:#f0f4ef}tbody th{font-weight:500}caption{text-align:left;color:#526359;font-size:13px;padding-bottom:10px}.stage-list{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;margin:20px 0}.stage-list div{display:grid;gap:8px;padding:16px;background:#f0f4ef;border-radius:6px}.stage-list strong{font-size:26px}details{margin-top:18px}summary{cursor:pointer;font-weight:600}.error{color:#a12622}.empty{padding:16px;background:#edf4ef;border-radius:6px;margin:0}:is(button,a,select,summary):focus-visible{outline:3px solid #8bcdc0;outline-offset:3px}
  @media(max-width:600px){.panel{padding:16px}nav button{flex:1 1 130px}.filters{width:100%}.filters label{flex:1 1 140px}}
</style>
