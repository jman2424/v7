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
    {#each [0,0.5,1] as ratio}<line x1="48" x2="868" y1={205-ratio*170} y2={205-ratio*170} stroke="#dce3dc"/><text x="44" y={209-ratio*170} text-anchor="end">{(maximum*ratio).toLocaleString('en-GB',{maximumFractionDigits:1})}</text>{/each}
    {#each series as line,index}<path d={path(line.values)} fill="none" stroke={line.color} stroke-width="3" stroke-dasharray={index%2?'7 4':undefined}/>{/each}
    <text x="48" y="233">{labels[0]||''}</text><text x="868" y="233" text-anchor="end">{labels[labels.length-1]||''}</text>
  </svg>
  <details><summary>View figures: {title}</summary><div class="scroll"><table><thead><tr><th>Period (UTC)</th>{#each series as line}<th>{line.name}{unit?' ('+unit+')':''}</th>{/each}</tr></thead><tbody>{#each labels as label,index}<tr><th>{label}</th>{#each series as line}<td>{value(line.values[index]??null)}</td>{/each}</tr>{/each}</tbody></table></div></details>
</section>
<style>
  .chart{min-width:0;padding:22px;border:1px solid #d9ddd7;background:white;border-radius:8px}h3{margin:0;font-size:17px}.legend{display:flex;flex-wrap:wrap;gap:16px;margin:16px 0;font-size:14px}svg{width:100%;height:auto;display:block;min-height:130px}text{font:11px system-ui;fill:#526359}summary{cursor:pointer;font-size:14px;font-weight:600}.scroll{overflow:auto;max-height:400px;margin-top:16px}table{width:100%;border-collapse:collapse;text-align:left;font-size:13px}th,td{padding:10px;border-bottom:1px solid #dce3dc}summary:focus-visible{outline:3px solid #8bcdc0;outline-offset:3px}@media(max-width:600px){.chart{padding:16px}}
</style>
