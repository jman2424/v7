<script lang="ts">
  export let title: string;
  export let labels: string[] = [];
  export let series: {name:string;values:(number|null)[];color:string}[] = [];
  export let unit = '';
  export let ceiling: number | undefined = undefined;
  export let locale = 'en-GB';
  export let notRecordedLabel = 'Not recorded';
  export let periodLabel = 'Period (UTC)';
  export let figuresLabel = 'View figures';
  export let exactValuesLabel = 'Exact values in the table below';
  export let figuresRegionLabel = '';
  export let yAxis='Count';
  export let reportRange:string[]=[];
  let width=640;
  $: plotWidth=Math.max(260,width);
  $: values=series.flatMap(line=>line.values.filter((v):v is number=>v!==null && Number.isFinite(v)));
  $: maximum=ceiling ?? Math.max(2,2*Math.ceil(Math.max(0,...values)/2));
  $: value=(n:number|null)=>n===null||!Number.isFinite(n)?notRecordedLabel:unit.trim()==='GBP'
    ? new Intl.NumberFormat(locale,{style:'currency',currency:'GBP'}).format(n)
    : n.toLocaleString(locale,{maximumFractionDigits:2})+unit;
  $: dateFormat=new Intl.DateTimeFormat(locale,{day:'numeric',month:'short',year:'numeric',timeZone:'UTC'});
  $: labelText=(s:string)=>/^\d{4}-\d{2}-\d{2}$/.test(s)?dateFormat.format(new Date(s+'T00:00:00Z')):s;
  $: range=reportRange.length?reportRange:labels;
  const x=(i:number,count:number,w:number)=>64+i*(w-80)/Math.max(1,count-1);
  const y=(v:number,max:number)=>152-v/max*132;
  function path(points:(number|null)[],count:number,w:number,max:number) {
    let gap=true;
    return points.map((v,i)=>{if(v===null||!Number.isFinite(v)){gap=true;return '';}const command=gap?'M':'L';gap=false;return command+x(i,count,w)+','+y(v,max);}).join(' ');
  }
</script>
<section class="chart" aria-label={title}>
  <h3>{title}</h3>
  {#if range.length}<p class="range">{labelText(range[0])}{range.length>1?' – '+labelText(range[range.length-1]):''}</p>{/if}
  <div class="legend">{#each series as line,index}<span style:color={line.color}>{index%2?'┄':'━'} {line.name}</span>{/each}</div>
  {#if values.length && labels.length}
    <p class="axis">{yAxis}</p>
    <div bind:clientWidth={width}><svg viewBox={'0 0 '+plotWidth+' 184'} role="img" aria-label={title+' · '+periodLabel+' · '+yAxis+' · '+exactValuesLabel}>
      {#each [0,0.5,1] as ratio}<line x1="64" x2={plotWidth-16} y1={y(maximum*ratio,maximum)} y2={y(maximum*ratio,maximum)} stroke="var(--v7-line)"/><text x="60" y={4+y(maximum*ratio,maximum)} text-anchor="end">{value(maximum*ratio)}</text>{/each}
      {#each series as line,index}
        <path d={path(line.values,labels.length,plotWidth,maximum)} fill="none" stroke={line.color} stroke-width="2" stroke-dasharray={index%2?'7 4':undefined}/>
        {#each line.values as v,i}{#if v!==null && Number.isFinite(v)}<circle cx={x(i,labels.length,plotWidth)} cy={y(v,maximum)} r={labels.length>50?1.5:3} fill={line.color}><title>{labelText(labels[i])} · {line.name} · {value(v)}</title></circle>{/if}{/each}
      {/each}
      <text x="64" y="177">{labelText(labels[0])}</text>{#if labels.length>1}<text x={plotWidth-16} y="177" text-anchor="end">{labelText(labels[labels.length-1])}</text>{/if}
    </svg></div>
    <p class="axis horizontal">{periodLabel}</p>
  {:else}<p>No figures recorded for this period.</p>{/if}
  <details><summary>{figuresLabel}: {title}</summary><!-- svelte-ignore a11y_no_noninteractive_tabindex (Keyboard users need to scroll the table horizontally on small screens.) -->
    <div class="scroll" role="region" aria-label={figuresRegionLabel||title+' figures'} tabindex="0"><table><thead><tr><th scope="col">{periodLabel}</th>{#each series as line}<th scope="col">{line.name}{unit?' ('+unit+')':''}</th>{/each}</tr></thead><tbody>{#each labels as label,index}<tr><th scope="row">{labelText(label)}</th>{#each series as line}<td>{value(line.values[index]??null)}</td>{/each}</tr>{/each}</tbody></table></div></details>
</section>
<style>
.chart { min-width:0; padding:22px; border:1px solid var(--v7-line, var(--v7-line)); border-radius:var(--v7-radius-panel); background:var(--v7-surface, #fff); color:var(--v7-ink, var(--v7-ink)); box-shadow:none; }
  h3 { margin:0; font-size:var(--v7-text-md); line-height:1.45; letter-spacing:-.015em; }
  .axis,.range{font-size:var(--v7-text-xs);color:var(--v7-muted);margin:.4rem 0}.horizontal{text-align:center}
  .legend { display:flex; flex-wrap:wrap; gap:16px; margin:12px 0 16px; font-size:var(--v7-text-xs); line-height:1.5; }
  svg { display:block; width:100%; height:auto; min-height:150px; }
  text { font:11px system-ui; fill:var(--v7-muted, var(--v7-muted)); }
  details { margin-top:14px; padding-top:8px; border-top:1px solid var(--v7-line, var(--v7-line)); }
  summary { min-height:44px; align-content:center; color:var(--v7-accent, var(--v7-accent)); cursor:pointer; font-size:var(--v7-text-xs); font-weight:600; line-height:1.6; }
  .scroll { overflow:auto; max-height:400px; margin-top:8px; border:1px solid var(--v7-line, var(--v7-line)); border-radius:var(--v7-radius-control); }
  table { width:100%; min-width:420px; border-collapse:collapse; text-align:start; font-size:var(--v7-text-xs); }
  th, td { padding:12px 14px; border-bottom:1px solid var(--v7-line, var(--v7-line)); font-variant-numeric:tabular-nums; }
  thead th { background:var(--v7-canvas, var(--v7-canvas)); color:var(--v7-muted, var(--v7-muted)); font-size:var(--v7-text-xs); font-weight:600; }
  tbody th { font-weight:500; }
  tbody tr:hover { background:var(--v7-soft, var(--v7-tint)); }
  tbody tr:last-child :is(th, td) { border-bottom:0; }
  :is(summary, .scroll):focus-visible { outline:3px solid var(--v7-focus, #81baa1); outline-offset:3px; }
  @media(max-width:600px) { .chart { padding:16px; } h3 { font-size:var(--v7-text-md); } }
</style>
