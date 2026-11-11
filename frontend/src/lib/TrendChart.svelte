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
  $: maximum = ceiling ?? Math.max(1,...series.flatMap(line=>line.values.filter((v):v is number=>v!==null)));
  $: value = (n:number|null) => n===null ? notRecordedLabel : n.toLocaleString(locale,{maximumFractionDigits:2})+unit;
  function path(values:(number|null)[]) {
    let gap=true;
    return values.map((v,i)=>{if(v===null){gap=true;return '';} const command=gap?'M':'L';gap=false;return `${command}${48+i*820/Math.max(1,labels.length-1)},${205-v/maximum*170}`;}).join(' ');
  }
</script>
<section class="chart" aria-label={title}>
  <h3>{title}</h3>
  <div class="legend">{#each series as line,index}<span style:color={line.color}>{index%2?'┄':'━'} {line.name}</span>{/each}</div>
  <svg viewBox="0 0 920 245" role="img" aria-label={title+'; '+exactValuesLabel}>
    {#each [0,0.5,1] as ratio}<line x1="48" x2="868" y1={205-ratio*170} y2={205-ratio*170} stroke="var(--v7-line)"/><text x="44" y={209-ratio*170} text-anchor="end">{(maximum*ratio).toLocaleString(locale,{maximumFractionDigits:1})}</text>{/each}
    {#each series as line,index}<path d={path(line.values)} fill="none" stroke={line.color} stroke-width="3" stroke-dasharray={index%2?'7 4':undefined}/>{/each}
    <text x="48" y="233">{labels[0]||''}</text><text x="868" y="233" text-anchor="end">{labels[labels.length-1]||''}</text>
  </svg>
  <details><summary>{figuresLabel}: {title}</summary><!-- svelte-ignore a11y_no_noninteractive_tabindex (Keyboard users need to scroll the table horizontally on small screens.) -->
    <div class="scroll" role="region" aria-label={figuresRegionLabel||title+' figures'} tabindex="0"><table><thead><tr><th scope="col">{periodLabel}</th>{#each series as line}<th scope="col">{line.name}{unit?' ('+unit+')':''}</th>{/each}</tr></thead><tbody>{#each labels as label,index}<tr><th scope="row">{label}</th>{#each series as line}<td>{value(line.values[index]??null)}</td>{/each}</tr>{/each}</tbody></table></div></details>
</section>
<style>
.chart { min-width:0; padding:22px; border:1px solid var(--v7-line, var(--v7-line)); border-radius:var(--v7-radius-panel); background:var(--v7-surface, #fff); color:var(--v7-ink, var(--v7-ink)); box-shadow:none; }
  h3 { margin:0; font-size:var(--v7-text-md); line-height:1.45; letter-spacing:-.015em; }
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
