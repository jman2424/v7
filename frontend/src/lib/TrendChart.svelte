<script lang="ts">
  export let title: string;
  export let labels: string[] = [];
  export let series: {name:string;values:(number|null)[];color:string}[] = [];
  export let unit = '';
  export let ceiling: number | undefined = undefined;
  $: maximum = ceiling ?? Math.max(1,...series.flatMap(line=>line.values.filter((v):v is number=>v!==null)));
  const value = (n:number|null) => n===null ? 'Not recorded' : n.toLocaleString('en-GB',{maximumFractionDigits:2})+unit;
  function path(values:(number|null)[]) {
    let gap=true;
    return values.map((v,i)=>{if(v===null){gap=true;return '';} const command=gap?'M':'L';gap=false;return `${command}${48+i*820/Math.max(1,labels.length-1)},${205-v/maximum*170}`;}).join(' ');
  }
</script>
<section class="chart" aria-label={title}>
  <h3>{title}</h3>
  <div class="legend">{#each series as line,index}<span style:color={line.color}>{index%2?'┄':'━'} {line.name}</span>{/each}</div>
  <svg viewBox="0 0 920 245" role="img" aria-label={title+'; exact values in the table below'}>
    {#each [0,0.5,1] as ratio}<line x1="48" x2="868" y1={205-ratio*170} y2={205-ratio*170} stroke="var(--v7-line)"/><text x="44" y={209-ratio*170} text-anchor="end">{(maximum*ratio).toLocaleString('en-GB',{maximumFractionDigits:1})}</text>{/each}
    {#each series as line,index}<path d={path(line.values)} fill="none" stroke={line.color} stroke-width="3" stroke-dasharray={index%2?'7 4':undefined}/>{/each}
    <text x="48" y="233">{labels[0]||''}</text><text x="868" y="233" text-anchor="end">{labels[labels.length-1]||''}</text>
  </svg>
  <details><summary>View figures: {title}</summary><!-- svelte-ignore a11y_no_noninteractive_tabindex (Keyboard users need to scroll the table horizontally on small screens.) -->
    <div class="scroll" role="region" aria-label={title+' figures'} tabindex="0"><table><thead><tr><th scope="col">Period (UTC)</th>{#each series as line}<th scope="col">{line.name}{unit?' ('+unit+')':''}</th>{/each}</tr></thead><tbody>{#each labels as label,index}<tr><th scope="row">{label}</th>{#each series as line}<td>{value(line.values[index]??null)}</td>{/each}</tr>{/each}</tbody></table></div></details>
</section>
<style>
.chart { min-width:0; padding:22px; border:1px solid var(--v7-line, #e1e7e4); border-radius:12px; background:var(--v7-surface, #fff); color:var(--v7-ink, #172b26); box-shadow:none; }
  h3 { margin:0; font-size:16px; line-height:1.45; letter-spacing:-.015em; }
  .legend { display:flex; flex-wrap:wrap; gap:16px; margin:12px 0 16px; font-size:12px; line-height:1.5; }
  svg { display:block; width:100%; height:auto; min-height:150px; }
  text { font:11px system-ui; fill:var(--v7-muted, #64716d); }
  details { margin-top:14px; padding-top:8px; border-top:1px solid var(--v7-line, #e1e7e4); }
  summary { min-height:44px; align-content:center; color:var(--v7-accent, #087f5b); cursor:pointer; font-size:12px; font-weight:600; line-height:1.6; }
  .scroll { overflow:auto; max-height:400px; margin-top:8px; border:1px solid var(--v7-line, #e1e7e4); border-radius:8px; }
  table { width:100%; min-width:420px; border-collapse:collapse; text-align:left; font-size:12px; }
  th, td { padding:12px 14px; border-bottom:1px solid var(--v7-line, #e1e7e4); font-variant-numeric:tabular-nums; }
  thead th { background:var(--v7-canvas, #f5f7f7); color:var(--v7-muted, #64716d); font-size:11px; font-weight:600; }
  tbody th { font-weight:500; }
  tbody tr:hover { background:var(--v7-soft, #edf6f1); }
  tbody tr:last-child :is(th, td) { border-bottom:0; }
  :is(summary, .scroll):focus-visible { outline:3px solid var(--v7-focus, #81baa1); outline-offset:3px; }
  @media(max-width:600px) { .chart { padding:16px; } h3 { font-size:15px; } }
</style>
