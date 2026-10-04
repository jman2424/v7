<script lang="ts">
  import TrendChart from './TrendChart.svelte';
  import type {ReplyReport} from './statisticsTypes';
  export let replies:ReplyReport;
  export let previous:ReplyReport;
  export let daily:{day:string;inbound:number;outbound:number;errors:number;fallbacks:number}[];
  export let hours:{hour:string;inbound:number;outbound:number}[];
  export let topics:{day:string;topic:string;count:number}[];
  export let pipeline:Record<string,number>;
  let topic='';
  $: topicNames=[...new Set(topics.map(row=>row.topic))].sort();
  $: labels=daily.map(row=>row.day);
  $: rates=labels.map(day=>replies.daily.find(row=>row.day===day));
  const ratio=(n:number,d:number)=>d?100*n/d:null;
  const fmt=(value:number|null,unit='%')=>value===null?'No data':value.toLocaleString('en-GB',{maximumFractionDigits:1})+unit;
  $: timedReplies=replies.total.timed_replies??replies.total.replied;
  $: cards=[
    {name:'Reply rate',value:ratio(replies.total.replied,replies.total.eligible),prior:ratio(previous.total.replied,previous.total.eligible),hint:'Matched replies ÷ customer messages with a tracking ID.'},
    {name:'Answer success rate',value:ratio(replies.total.answered,replies.total.eligible),prior:ratio(previous.total.answered,previous.total.eligible),hint:'Matched replies without fallback, clarification or system failure ÷ tracked customer messages. A technical measure, not verified customer satisfaction.'}
  ];
</script>
<div class="performance">
  <div class="section-heading"><span>Response performance</span><h3>How your assistant is responding</h3><p>Tracked messages, generated replies and recorded outcomes for this report.</p></div>
  <div class="cards">{#each cards as card}<article><h3>{card.name}</h3><strong>{fmt(card.value)}</strong><p>{card.value!==null&&card.prior!==null?fmt(card.value-card.prior,' percentage points vs previous period'):'No comparable previous rate'}</p><p>{card.hint}</p></article>{/each}
    <article><h3>Average reply generation time</h3><strong>{fmt(timedReplies?replies.total.response_seconds/timedReplies:null,'s')}</strong><p>Matched replies with valid timestamps; timestamps have one-second precision. This does not measure provider delivery or read receipts.</p></article>
    <article><h3>Messages without a recorded reply</h3><strong>{replies.total.eligible-replies.total.replied}</strong><p>Of {replies.total.eligible} tracked inbound messages, as of the report end. {replies.total.inbound-replies.total.eligible} older messages without IDs are excluded from rates.</p></article>
    <article><h3>Current lead win rate</h3><strong>{fmt(ratio(pipeline.Won||0,(pipeline.Won||0)+(pipeline.Lost||0)))}</strong><p>Won ÷ (Won + Lost), using current owner-managed statuses across all time and channels. This is not a product purchase rate.</p></article>
  </div>
  <TrendChart title="Reply and answer success rates" {labels} ceiling={100} unit="%" series={[
    {name:'Reply rate',color:'#007d70',values:rates.map(row=>row?ratio(row.replied,row.eligible):null)},
    {name:'Answer success rate',color:'#748a35',values:rates.map(row=>row?ratio(row.answered,row.eligible):null)}]}/>
  <p class="hint">Rates follow inbound messages received on each day and replies recorded before the report end. Gaps mean no eligible messages. A generated reply is not proof of delivery or a successful sale.</p>
  <div class="chart-grid"><TrendChart title="Inbound vs outbound queries" {labels} series={[
    {name:'Inbound customer messages',color:'#007d70',values:daily.map(row=>row.inbound)},
    {name:'Outbound agent replies',color:'#748a35',values:daily.map(row=>row.outbound)}]}/>
  <TrendChart title="Fallback and error timeline" {labels} series={[
    {name:'Fallback replies',color:'#996419',values:daily.map(row=>row.fallbacks)},
    {name:'Recorded errors',color:'#ad3939',values:daily.map(row=>row.errors)}]}/></div>
  <TrendChart title="Busiest hours (UTC)" labels={Array.from({length:24},(_,i)=>String(i).padStart(2,'0')+':00')} series={[
    {name:'Inbound',color:'#007d70',values:Array.from({length:24},(_,i)=>hours.find(row=>Number(row.hour)===i)?.inbound||0)},
    {name:'Outbound',color:'#748a35',values:Array.from({length:24},(_,i)=>hours.find(row=>Number(row.hour)===i)?.outbound||0)}]}/>
  <label>Query topic<select bind:value={topic}><option value="">All query topics</option>{#each topicNames as name}<option value={name}>{name.replaceAll('_',' ')}</option>{/each}</select></label>
  <TrendChart title="Query topic timeline" {labels} series={[{name:topic?topic.replaceAll('_',' '):'All topics',color:'#007d70',values:labels.map(day=>topics.filter(row=>row.day===day&&(!topic||row.topic===topic)).reduce((sum,row)=>sum+row.count,0))}]}/>
  <p class="hint">Topics are classified from agent responses. Inbound queries without a reply may not have a topic.</p>
</div>
<style>
 .performance{display:grid;gap:20px;min-width:0}.section-heading span{font-size:10px;text-transform:uppercase;letter-spacing:.13em;font-weight:700;color:#658168}.section-heading h3{font-size:22px;letter-spacing:-.035em;color:#234c39;margin-top:8px}.section-heading p{margin-top:6px}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,250px),1fr));gap:16px}article{padding:24px;border:1px solid var(--v7-line);background:white;border-radius:18px;min-width:0;box-shadow:var(--v7-card-shadow, 0 8px 28px #203b3008);border-top:3px solid #91b883}article:first-child{background:linear-gradient(135deg,#eef5e6,#f8fbf6);border-color:#cbdcc3}h3{font-size:12px;color:#64766b;margin:0;line-height:1.5}strong{display:block;font-size:38px;margin:18px 0;letter-spacing:-.055em;font-variant-numeric:tabular-nums;color:#234c39}p{font-size:12px;line-height:1.65;color:var(--v7-muted);margin-bottom:0}.hint{margin:0}label{display:grid;gap:8px;font-size:12px;font-weight:600;padding:18px;background:#f2f7ed;border:1px solid #dbe6d4;border-radius:14px}select{font:inherit;padding:12px;border:1px solid var(--v7-control-line,#b5c5bc);border-radius:10px;max-width:100%;background:white;color:var(--v7-ink);min-height:44px}.chart-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}.performance :global(.chart){background:linear-gradient(180deg,#fff,#fcfdf9)}.performance :global(.chart h3){color:#234c39}.performance :global(.chart svg){margin-top:10px}.performance :global(.chart summary){font-size:12px;color:#46674c}select:focus-visible{outline:3px solid #8bcdc0;outline-offset:3px}@media(max-width:1000px){.chart-grid{grid-template-columns:1fr}}@media(max-width:600px){article{padding:20px}strong{font-size:34px}.section-heading h3{font-size:20px}}
</style>
