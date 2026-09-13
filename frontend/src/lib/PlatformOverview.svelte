<script lang="ts">
  import {onMount,onDestroy,createEventDispatcher} from 'svelte';
  import {base} from '$app/paths';
  export let apiPrefix='';
  type Company={tenant:string;name:string;mode:string;status:string;knowledge_files:number;knowledge_files_expected:number;issues:string[];analytics_available:boolean;kpis:{inbound:number;outbound:number;sessions:number;errors:number}|null;errors:{error_code?:string;error_type?:string;count:number}[]};
  type Report={company_count:number;page:number;page_size:number;has_next:boolean;generated_at:string;companies:Company[]};
  const dispatch=createEventDispatcher<{open:{tenant:string;section:string}}>();
  let report:Report|null=null;
  let page=1;
  let minutes=1440;
  let search='';
  let attentionOnly=false;
  let busy=false;
  let error='';
  let mounted=false;
  let controller:AbortController|undefined;
  $: if(mounted)load(page,minutes);
  $: companies=report?.companies.filter(company=>(company.name+' '+company.tenant).toLowerCase().includes(search.toLowerCase())&&(!attentionOnly||company.status==='needs_attention'))||[];
  onMount(()=>{mounted=true;});
  onDestroy(()=>controller?.abort());
  async function load(selectedPage:number,period:number){
    controller?.abort();const request=new AbortController();controller=request;busy=true;error='';
    const timer=setTimeout(()=>request.abort(),20000);
    try{const response=await fetch(apiPrefix+'/admin/api/platform?'+new URLSearchParams({page:String(selectedPage),minutes:String(period)}),{credentials:'same-origin',signal:request.signal});
      if(!response.ok)throw new Error(response.status===403?'Platform administrator access is required.':'Could not load the company overview. Refresh and try again.');
      const result:Report=await response.json();if(controller===request)report=result;
    }catch(failure){if(controller===request)error=request.signal.aborted?'Loading timed out. Try again.':failure instanceof Error?failure.message:'Overview unavailable.';}
    finally{clearTimeout(timer);if(controller===request)busy=false;}
  }
</script>
<section class="platform" aria-label="Platform management overview">
  <article class="intro"><div><h2>Manage all your businesses</h2><p>Your platform account can oversee every company. Open a company below to manage its agent, owner accounts and data.</p></div><a href={base+'/companies'}>Add a company</a></article>
  <div class="controls"><label>Activity period<select bind:value={minutes}><option value={1440}>Last 24 hours</option><option value={10080}>Last 7 days</option><option value={43200}>Last 30 days</option></select></label><label>Search this page<input bind:value={search} placeholder="Company name or key"/></label><label class="toggle"><input type="checkbox" bind:checked={attentionOnly}/>Needs attention only</label><button disabled={busy} on:click={()=>load(page,minutes)}>Refresh</button></div>
  {#if busy}<p role="status">Loading businesses…</p>{/if}{#if error}<p class="error" role="alert">{error}</p>{/if}
  {#if report}
    <div class="totals"><article><h3>Businesses on the platform</h3><strong>{report.company_count}</strong></article><article><h3>Need attention · this page</h3><strong>{report.companies.filter(company=>company.status==='needs_attention').length}</strong></article><article><h3>Recorded errors · this page</h3><strong>{report.companies.reduce((sum,company)=>sum+(company.kpis?.errors||0),0)}</strong></article></div>
    <div class="companies">{#each companies as company}<article class="company"><header><div><h3>{company.name}</h3><p>{company.tenant} · Agent {company.mode.toUpperCase()}</p></div><span class:attention={company.status==='needs_attention'}>{company.status==='needs_attention'?'Needs attention':company.status==='activity_recorded'?'Activity recorded':'No recent activity'}</span></header>
      <dl><div><dt>Customer messages</dt><dd>{company.kpis?.inbound??'Unavailable'}</dd></div><div><dt>Agent replies</dt><dd>{company.kpis?.outbound??'Unavailable'}</dd></div><div><dt>Conversations</dt><dd>{company.kpis?.sessions??'Unavailable'}</dd></div><div><dt>Recorded errors</dt><dd>{company.kpis?.errors??'Unavailable'}</dd></div></dl>
      <p>Readable knowledge files: {company.knowledge_files}/{company.knowledge_files_expected}. This is a configuration check, not a live uptime guarantee.</p>
      {#if company.issues.length}<ul>{#each company.issues as issue}<li>{issue}</li>{/each}</ul>{/if}
      <div class="actions"><button on:click={()=>dispatch('open',{tenant:company.tenant,section:'pipeline'})}>Open workspace</button><button on:click={()=>dispatch('open',{tenant:company.tenant,section:'team'})}>Owner &amp; staff accounts</button><button on:click={()=>dispatch('open',{tenant:company.tenant,section:'statistics'})}>Statistics</button><button on:click={()=>dispatch('open',{tenant:company.tenant,section:'errors'})}>Errors &amp; health</button></div>
    </article>{:else}<article><p>No companies match these filters on this page.</p></article>{/each}</div>
    <div class="controls"><button disabled={busy||page===1} on:click={()=>page-=1}>Previous</button><span>Page {report.page} of {Math.max(1,Math.ceil(report.company_count/report.page_size))}</span><button disabled={busy||!report.has_next} on:click={()=>page+=1}>Next</button></div>
  {/if}
</section>
<style>
 .platform{display:grid;gap:20px;min-width:0;overflow-wrap:anywhere}article{padding:24px;border:1px solid #d9ddd7;background:white;border-radius:8px;min-width:0}.intro,header,.controls,.actions{display:flex;flex-wrap:wrap;gap:16px;align-items:center;justify-content:space-between}.intro div{flex:1 1 300px}.controls{justify-content:start;align-items:end}.totals{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr));gap:16px}.totals strong{display:block;font-size:32px;margin-top:16px}h2,h3,p{margin:0}h2{font-size:23px}h3{font-size:17px}p{font-size:13px;line-height:1.6;color:#526359;margin-top:10px}.companies{display:grid;gap:16px}.attention{color:#9c3a10;background:#fff3e7;padding:8px;border-radius:5px}dl{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:16px}dt{font-size:13px;color:#526359}dd{font-size:24px;font-weight:700;margin:8px 0}label{display:grid;gap:8px;font-size:14px;font-weight:600;min-width:0}.toggle{display:flex;align-items:center;padding-bottom:12px}input,select,button,a{font:inherit}input,select{min-width:0;max-width:100%;padding:11px;border:1px solid #bbc4bc;border-radius:6px;background:white;color:#26332b}button,.intro a{border:1px solid #bbc4bc;border-radius:6px;background:white;color:#007d70;padding:11px 14px;min-height:44px;font-weight:600;cursor:pointer;text-decoration:none}button:disabled{opacity:.5;cursor:default}.actions{justify-content:start;margin-top:20px}.error{color:#a12622}ul{font-size:13px;color:#9c3a10}:is(button,input,select,a):focus-visible{outline:3px solid #8bcdc0;outline-offset:3px}@media(max-width:600px){article{padding:16px}.controls label{width:100%}.actions button{width:100%}}
</style>
