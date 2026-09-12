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
  $: cards=[
    {name:'Reply rate',value:ratio(replies.total.replied,replies.total.eligible),prior:ratio(previous.total.replied,previous.total.eligible),hint:'Matched replies ÷ customer messages with a tracking ID.'},
    {name:'Answer success rate',value:ratio(replies.total.answered,replies.total.eligible),prior:ratio(previous.total.answered,previous.total.eligible),hint:'Matched replies without fallback, clarification or system failure ÷ tracked customer messages. A technical measure, not verified customer satisfaction.'}
  ];
</script>
<div class="performance">
  <div class="cards">{#each cards as card}<article><h3>{card.name}</h3><strong>{fmt(card.value)}</strong><p>{card.value!==null&&card.prior!==null?fmt(card.value-card.prior,' percentage points vs previous period'):'No comparable previous rate'}</p><p>{card.hint}</p></article>{/each}
    <article><h3>Average reply generation time</h3><strong>{fmt(replies.total.replied?replies.total.response_seconds/replies.total.replied:null,'s')}</strong><p>Matched replies; timestamps have one-second precision. This does not measure provider delivery or read receipts.</p></article>
    <article><h3>Messages without a recorded reply</h3><strong>{replies.total.eligible-replies.total.replied}</strong><p>Of {replies.total.eligible} tracked inbound messages, as of the report end. {replies.total.inbound-replies.total.eligible} older messages without IDs are excluded from rates.</p></article>
    <article><h3>Current lead win rate</h3><strong>{fmt(ratio(pipeline.Won||0,(pipeline.Won||0)+(pipeline.Lost||0)))}</strong><p>Won ÷ (Won + Lost), using current owner-managed statuses across all time and channels. This is not a product purchase rate.</p></article>
  </div>
  <TrendChart title="Reply and answer success rates" {labels} ceiling={100} unit="%" series={[
    {name:'Reply rate',color:'#007d70',values:rates.map(row=>row?ratio(row.replied,row.eligible):null)},
    {name:'Answer success rate',color:'#596f9c',values:rates.map(row=>row?ratio(row.answered,row.eligible):null)}]}/>
  <p class="hint">Rates follow inbound messages received on each day and replies recorded before the report end. Gaps mean no eligible messages. A generated reply is not proof of delivery or a successful sale.</p>
  <TrendChart title="Inbound vs outbound queries" {labels} series={[
    {name:'Inbound customer messages',color:'#007d70',values:daily.map(row=>row.inbound)},
    {name:'Outbound agent replies',color:'#596f9c',values:daily.map(row=>row.outbound)}]}/>
  <TrendChart title="Fallback and error timeline" {labels} series={[
    {name:'Fallback replies',color:'#996419',values:daily.map(row=>row.fallbacks)},
    {name:'Recorded errors',color:'#ad3939',values:daily.map(row=>row.errors)}]}/>
  <TrendChart title="Busiest hours (UTC)" labels={Array.from({length:24},(_,i)=>String(i).padStart(2,'0')+':00')} series={[
    {name:'Inbound',color:'#007d70',values:Array.from({length:24},(_,i)=>hours.find(row=>Number(row.hour)===i)?.inbound||0)},
    {name:'Outbound',color:'#596f9c',values:Array.from({length:24},(_,i)=>hours.find(row=>Number(row.hour)===i)?.outbound||0)}]}/>
  <label>Query topic<select bind:value={topic}><option value="">All query topics</option>{#each topicNames as name}<option value={name}>{name.replaceAll('_',' ')}</option>{/each}</select></label>
  <TrendChart title="Query topic timeline" {labels} series={[{name:topic?topic.replaceAll('_',' '):'All topics',color:'#007d70',values:labels.map(day=>topics.filter(row=>row.day===day&&(!topic||row.topic===topic)).reduce((sum,row)=>sum+row.count,0))}]}/>
  <p class="hint">Topics are classified from agent responses. Inbound queries without a reply may not have a topic.</p>
</div>
<style>
 .performance{display:grid;gap:20px;min-width:0}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,250px),1fr));gap:16px}article{padding:22px;border:1px solid #d9ddd7;background:white;border-radius:8px;min-width:0}h3{font-size:15px;margin:0}strong{display:block;font-size:30px;margin:16px 0}p{font-size:13px;line-height:1.6;color:#526359;margin-bottom:0}.hint{margin:0}label{display:grid;gap:8px;font-weight:600}select{font:inherit;padding:12px;border:1px solid #bbc4bc;border-radius:6px;max-width:100%;background:white;color:#26332b}
</style>
