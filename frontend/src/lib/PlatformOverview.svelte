<script lang="ts">
  import { t } from './i18n';
  import { onMount, onDestroy, createEventDispatcher } from 'svelte';
  import { base } from '$app/paths';
  export let apiPrefix = '';
  type Company = {tenant:string;name:string;mode:string;status:string;knowledge_files:number;knowledge_files_expected:number;issues:string[];analytics_available:boolean;kpis:{inbound:number;outbound:number;sessions:number;errors:number}|null;errors:{error_code?:string;error_type?:string;count:number}[]};
  type Report = {company_count:number;page:number;page_size:number;has_next:boolean;generated_at:string;companies:Company[]};
  const dispatch = createEventDispatcher<{open:{tenant:string;section:string}}>();
  let report: Report | null = null;
  let page = 1;
  let minutes = 1440;
  let search = '';
  let attentionOnly = false;
  let busy = false;
  let error = '';
  let mounted = false;
  let controller: AbortController | undefined;
  const count = (value:number|null|undefined) => value == null ? 'Unavailable' : value.toLocaleString('en-GB');
  $: if (mounted) load(page, minutes);
  $: companies = report?.companies.filter(company => (company.name + ' ' + company.tenant).toLowerCase().includes(search.toLowerCase()) && (!attentionOnly || company.status === 'needs_attention')) || [];
  $: summary = report?.companies.reduce((total, company) => ({
    inbound: total.inbound + (company.kpis?.inbound || 0),
    sessions: total.sessions + (company.kpis?.sessions || 0),
    attention: total.attention + Number(company.status === 'needs_attention'),
    available: total.available + Number(company.analytics_available)
  }), {inbound:0,sessions:0,attention:0,available:0});
  $: totals = [
    {label:'Businesses',value:report?.company_count,detail:'Across your platform',icon:'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',featured:true},
    {label:'Customer messages',value:summary?.available ? summary.inbound : null,detail:'Recorded activity · this page',icon:'M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9H13a8.5 8.5 0 0 1 8 8v.5Z',featured:false},
    {label:'Conversations',value:summary?.available ? summary.sessions : null,detail:'Recorded sessions · this page',icon:'M4 4h16v12H9l-5 4V4Z M8 8h8 M8 12h5',featured:false},
    {label:'Need attention',value:summary?.attention,detail:'Configuration checks · this page',icon:'M12 8v5 M12 16h.01 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0Z',featured:false}
  ];
  onMount(() => { mounted = true; });
  onDestroy(() => { controller?.abort(); controller = undefined; });
  async function load(selectedPage:number, period:number) {
    controller?.abort();
    const request = new AbortController();
    controller = request; busy = true; error = '';
    const timer = setTimeout(() => request.abort(), 20000);
    try {
      const response = await fetch(apiPrefix + '/admin/api/platform?' + new URLSearchParams({page:String(selectedPage),minutes:String(period)}), {credentials:'same-origin',signal:request.signal});
      if (!response.ok) throw new Error(response.status === 403 ? 'Platform administrator access is required.' : 'Could not load the company overview. Refresh and try again.');
      const result: Report = await response.json();
      if (controller === request && !request.signal.aborted) report = result;
    } catch (failure) {
      if (controller === request) error = request.signal.aborted ? 'Loading timed out. Try again.' : failure instanceof Error ? failure.message : 'Overview unavailable.';
    } finally { clearTimeout(timer); if (controller === request) busy = false; }
  }
</script>

<section class="platform" aria-label="Platform management overview" aria-busy={busy}>
  <article class="intro">
    <svg class="hero-pattern" viewBox="0 0 280 220" aria-hidden="true"><circle cx="190" cy="110" r="94"/><circle cx="190" cy="110" r="66"/><circle cx="190" cy="110" r="38"/><path d="M30 110h250 M190 0v220"/></svg>
    <div class="intro-copy"><p class="eyebrow">Your business network</p><h2>Every business.<br/>One clear view.</h2><p>See customer activity, spot what needs attention and move straight into each workspace.</p></div>
    <div class="intro-action"><span class="access-label"><span></span>Platform administrator</span><a href={base + '/companies'}><span>Add a company</span><span aria-hidden="true">↗</span></a></div>
  </article>

  {#if report && !error}
    <div class="totals">{#each totals as metric}<article class="metric" class:featured={metric.featured}><div class="metric-top"><span>{metric.label}</span><svg viewBox="0 0 24 24" aria-hidden="true"><path d={metric.icon}/></svg></div><strong>{count(metric.value)}</strong><p>{metric.detail}</p></article>{/each}</div>
  {:else if !error}
    <div class="totals skeletons" aria-hidden="true">{#each [1,2,3,4] as card}<article class="metric"><span class="skeleton-line"></span><span class="skeleton-value"></span><span class="skeleton-line short"></span></article>{/each}</div>
  {/if}

  <div class="directory-heading"><div><p class="eyebrow">Workspace directory</p><h3>Your companies</h3></div>{#if report}<span class="checked">Checked {new Date(report.generated_at).toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit'})}</span>{/if}</div>
  <div class="controls">
    <label class="search">Find a business<span class="search-field"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></svg><input bind:value={search} placeholder="Search company name or key"/></span></label>
    <label>Activity period<select bind:value={minutes}><option value={1440}>Last 24 hours</option><option value={10080}>Last 7 days</option><option value={43200}>Last 30 days</option></select></label>
    <label class="toggle"><input type="checkbox" bind:checked={attentionOnly}/>Needs attention only</label>
    <button class="refresh" disabled={busy} on:click={() => load(page,minutes)}><span aria-hidden="true">↻</span>{$t("Refresh")}</button>
  </div>
  {#if busy}<p class="loading" role="status"><span class="loading-dot" aria-hidden="true"></span>{report ? 'Updating the overview. Displayed figures are from the previous check.' : 'Loading your businesses and recorded activity…'}</p>{/if}
  {#if error}<p class="error" role="alert">{error}</p>{/if}

  {#if report && !error}
    <div class="results-heading"><p>{companies.length} of {report.companies.length} businesses shown on this page</p>{#if search || attentionOnly}<button type="button" on:click={() => {search = ''; attentionOnly = false;}}>Clear filters</button>{/if}</div>
    {#if summary && summary.available < report.companies.length}<p class="data-note">Activity totals include businesses with available analytics on this page.</p>{/if}
    <div class="companies">{#each companies as company}
      <article class="company">
        <header><div class="company-identity"><span class="company-avatar" aria-hidden="true">{company.name.slice(0,2).toUpperCase()}</span><div><h3>{company.name}</h3><p>{company.tenant} <span aria-hidden="true">·</span> Agent {company.mode.toUpperCase()}</p></div></div><span class="status" class:attention={company.status === 'needs_attention'}><span aria-hidden="true"></span>{company.status === 'needs_attention' ? 'Needs attention' : company.status === 'activity_recorded' ? 'Activity recorded' : 'No recent activity'}</span></header>
        <dl><div><dt>Customer messages</dt><dd>{count(company.kpis?.inbound)}</dd></div><div><dt>Agent replies</dt><dd>{count(company.kpis?.outbound)}</dd></div><div><dt>{$t("Conversations")}</dt><dd>{count(company.kpis?.sessions)}</dd></div><div><dt>Recorded errors</dt><dd>{count(company.kpis?.errors)}</dd></div></dl>
        <div class="knowledge"><div><span>Readable knowledge files</span><strong>{company.knowledge_files}<span> / {company.knowledge_files_expected}</span></strong></div><div class="knowledge-track" aria-hidden="true"><span style:width={(company.knowledge_files_expected ? Math.min(100,company.knowledge_files/company.knowledge_files_expected*100) : 0) + '%'}></span></div></div>
        {#if company.issues.length}<ul class="issues">{#each company.issues as issue}<li>{issue}</li>{/each}</ul>{/if}
        <div class="actions"><button class="open-workspace" on:click={() => dispatch('open',{tenant:company.tenant,section:'pipeline'})}>Open workspace <span aria-hidden="true">↗</span></button><button on:click={() => dispatch('open',{tenant:company.tenant,section:'team'})}>Owner &amp; staff accounts</button><button on:click={() => dispatch('open',{tenant:company.tenant,section:'statistics'})}>{$t("Statistics")}</button><button on:click={() => dispatch('open',{tenant:company.tenant,section:'errors'})}>{$t("Errors & health")}</button></div>
      </article>
    {:else}<article class="empty"><span class="empty-symbol" aria-hidden="true">⌕</span><h3>{report.company_count ? 'No businesses match these filters' : 'Your first workspace starts here'}</h3><p>{report.company_count ? 'Clear the filters or check another page to find a business.' : 'Add a company to start building its knowledge and reviewing customer activity.'}</p></article>{/each}</div>
    <footer><nav class="pagination" aria-label="Business pages"><button disabled={busy || page === 1} on:click={() => page -= 1}>Previous</button><span>Page {report.page} of {Math.max(1,Math.ceil(report.company_count/report.page_size))}</span><button disabled={busy || !report.has_next} on:click={() => page += 1}>Next</button></nav><p>Recorded activity and configuration checks. Last checked <time datetime={report.generated_at}>{new Date(report.generated_at).toLocaleString()}</time></p></footer>
  {/if}
</section>

<style>
  .platform{display:grid;gap:20px;min-width:0;overflow-wrap:anywhere}
  article{min-width:0;border:1px solid var(--v7-line);border-radius:20px;background:var(--v7-surface,#fff);box-shadow:0 4px 20px #203b3005}
  h2,h3,p{margin:0}p{font-size:13px;line-height:1.6;color:var(--v7-muted)}h3{font-size:17px;letter-spacing:-.02em}
  .eyebrow{font-size:10px;font-weight:750;letter-spacing:.14em;text-transform:uppercase}
  .intro{position:relative;display:flex;justify-content:space-between;align-items:center;gap:24px;overflow:hidden;padding:30px 34px;border:0;background:linear-gradient(110deg,#173e30,var(--v7-brand,#203b30) 60%,#365f45);color:#fff}
  .intro-copy,.intro-action{position:relative;z-index:1}.intro-copy{max-width:610px}.intro .eyebrow{color:#ceec99;margin-bottom:12px}.intro h2{font-size:clamp(27px,3vw,40px);line-height:1.08;letter-spacing:-.045em;font-weight:650}.intro-copy>p:last-child{max-width:460px;color:#d1e4d8;margin-top:15px;line-height:1.7}
  .intro-action{display:grid;gap:18px;justify-items:end;flex:none}.access-label{display:flex;align-items:center;gap:8px;font-size:11px;letter-spacing:.025em;color:#d1e4d8}.access-label>span{height:6px;width:6px;border-radius:50%;background:#d6f58a}
  .intro a{display:flex;align-items:center;gap:25px;min-height:44px;padding:13px 18px;border-radius:12px;background:var(--v7-lime,#d6f58a);color:#173e30;font-size:13px;font-weight:750;text-decoration:none}.intro a>span:last-child{font-size:20px}
  .hero-pattern{position:absolute;right:-40px;top:-22px;width:300px;height:240px;fill:none;stroke:#ddf0b5;stroke-width:1;opacity:.13}
  .totals{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}.metric{padding:20px 22px;position:relative;overflow:hidden}.metric.featured{background:#edf5dd;border-color:#d7e5bf}.metric-top{display:flex;justify-content:space-between;align-items:center;gap:12px;font-size:12px;font-weight:600;color:var(--v7-muted)}.metric-top svg{width:20px;height:20px;fill:none;stroke:var(--v7-accent,#007d70);stroke-width:1.5;stroke-linejoin:round;stroke-linecap:round;flex:none}.metric strong{display:block;margin:13px 0 8px;font-size:clamp(26px,3vw,39px);font-weight:650;letter-spacing:-.05em;font-variant-numeric:tabular-nums;color:var(--v7-ink)}.metric p{font-size:11px}
  .directory-heading{display:flex;justify-content:space-between;align-items:end;gap:15px;margin-top:6px}.directory-heading .eyebrow{margin-bottom:6px;color:var(--v7-accent)}.directory-heading h3{font-size:21px}.checked{font-size:11px;color:var(--v7-muted)}
  .controls{display:flex;align-items:end;gap:16px;flex-wrap:wrap;padding:16px 18px;border:1px solid var(--v7-line);border-radius:16px;background:var(--v7-surface,#fff)}label{display:grid;gap:7px;font-size:11px;font-weight:650;min-width:0;color:var(--v7-muted)}.search{flex:1 1 220px}.search-field{display:flex;align-items:center;gap:10px;border:1px solid var(--v7-control-line,#b5c5bc);border-radius:10px;padding-inline:12px;min-height:44px}.search-field svg{width:17px;height:17px;fill:none;stroke:var(--v7-muted);stroke-width:1.5;flex:none}.search-field input{border:0;padding-inline:0;min-height:42px;width:100%;background:transparent}.toggle{display:flex;align-items:center;align-self:center;font-size:12px;gap:8px;margin-top:18px}
  input,select,button,a{font:inherit}input,select{max-width:100%;min-width:0;padding:10px 12px;border:1px solid var(--v7-control-line,#b5c5bc);border-radius:10px;background:var(--v7-surface,#fff);color:var(--v7-ink);min-height:44px;font-size:13px}input[type="checkbox"]{width:17px;height:17px;min-height:17px;padding:0;accent-color:var(--v7-accent)}
  button{min-height:44px;border:1px solid var(--v7-control-line,#b5c5bc);border-radius:10px;background:var(--v7-surface,#fff);color:var(--v7-brand,#203b30);padding:10px 14px;font-size:12px;font-weight:650;cursor:pointer;transition:background .15s,border-color .15s}button:hover:not(:disabled){background:var(--v7-soft,#f0f6f2);border-color:#91b49e}button:disabled{opacity:.5;cursor:default}.refresh{display:flex;align-items:center;gap:8px}.refresh>span{font-size:21px}
  .loading,.error{display:flex;align-items:center;gap:10px;padding:13px 16px;border-radius:12px;font-size:12px;margin:0}.loading{color:var(--v7-accent);background:var(--v7-soft,#f0f6f2)}.loading-dot{width:7px;height:7px;border-radius:50%;background:currentColor;animation:pulse 1.2s ease-in-out infinite;flex:none}.error{color:#a12622;background:#fff2f0}
  .results-heading{display:flex;justify-content:space-between;align-items:center;gap:12px}.results-heading p,.data-note{font-size:11px}.results-heading button{min-height:32px;padding:6px 10px}
  .companies{display:grid;gap:18px;grid-template-columns:repeat(auto-fit,minmax(min(100%,390px),1fr))}.company{padding:24px}.company header{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:14px}.company-identity{display:flex;align-items:center;gap:13px;min-width:0}.company-avatar{display:grid;place-items:center;width:44px;height:44px;border-radius:12px;background:#edf5dd;border:1px solid #d7e5bf;color:#36583b;font-size:14px;font-weight:750;flex:none}.company h3{font-size:18px}.company header p{font-size:11px;margin-top:5px}.company header p>span{margin-inline:5px}
  .status{display:flex;align-items:center;gap:6px;padding:7px 10px;background:#f2f5f1;color:var(--v7-muted);border-radius:20px;font-size:10px;font-weight:650}.status>span{width:5px;height:5px;background:#8ba094;border-radius:50%;flex:none}.status.attention{color:#92501b;background:#fff3e7}.status.attention>span{background:#bd792b}
  dl{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;padding:20px 0;margin:20px 0;border-top:1px solid var(--v7-line);border-bottom:1px solid var(--v7-line)}dt{font-size:10px;line-height:1.5;color:var(--v7-muted)}dd{font-size:24px;font-weight:650;letter-spacing:-.035em;margin:8px 0 0;font-variant-numeric:tabular-nums}
  .knowledge{display:grid;gap:10px}.knowledge>div:first-child{display:flex;justify-content:space-between;align-items:center;gap:10px;font-size:11px;color:var(--v7-muted)}.knowledge strong{font-weight:650;color:var(--v7-ink);font-variant-numeric:tabular-nums}.knowledge strong>span{font-weight:400;color:var(--v7-muted)}.knowledge-track{height:5px;background:#edf0e8;border-radius:6px;overflow:hidden}.knowledge-track>span{display:block;height:100%;background:#79a478;border-radius:6px}
  .issues{font-size:12px;color:#92501b;background:#fff7ec;border-radius:10px;margin:16px 0 0;padding:13px 16px 13px 30px;line-height:1.65}
  .actions{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px;margin-top:22px}.actions .open-workspace{display:flex;justify-content:space-between;align-items:center;background:var(--v7-brand,#203b30);border-color:var(--v7-brand,#203b30);color:#fff}.actions .open-workspace:hover{background:#285441}.actions .open-workspace>span{font-size:19px}
  .empty{text-align:center;padding:42px 24px;border-style:dashed;background:var(--v7-soft,#f0f6f2)}.empty-symbol{display:block;color:var(--v7-accent);font-size:35px;margin-bottom:14px}.empty p{max-width:390px;margin:10px auto 0}
  footer,.pagination{display:flex;flex-wrap:wrap;align-items:center;gap:12px}footer{justify-content:space-between}footer p{font-size:10px;max-width:430px}.pagination{font-size:12px}.pagination button{min-height:38px;padding:7px 12px}
  .skeleton-line,.skeleton-value{display:block;border-radius:6px;background:#e7ede4;animation:pulse 1.5s ease-in-out infinite}.skeleton-line{height:10px;width:70%;margin:5px 0 20px}.skeleton-line.short{width:85%;margin:15px 0 0}.skeleton-value{height:35px;width:35%}
  :is(button,input,select,a):focus-visible{outline:3px solid #8bcdc0;outline-offset:3px}
  @keyframes pulse{50%{opacity:.45}}
  @media(max-width:1000px){.totals{grid-template-columns:repeat(2,minmax(0,1fr))}.intro{padding:26px}.intro-action{gap:13px}.toggle{margin-top:0}}
  @media(max-width:600px){.intro{align-items:start;flex-direction:column;padding:24px;gap:20px}.intro-action{width:100%;display:flex;align-items:center;justify-content:space-between}.access-label{font-size:10px}.intro a{gap:12px;padding:11px 13px}.hero-pattern{right:-90px}.totals{gap:10px}.metric{padding:16px}.metric-top{font-size:11px}.metric-top svg{width:17px}.metric strong{font-size:29px}.controls{padding:14px;gap:13px}.search{flex-basis:100%}.controls>label:not(.toggle){flex:1 1 150px}.toggle{flex:1 1 150px}.company{padding:20px}.company header{align-items:start}.status{margin-inline-start:57px}dl{grid-template-columns:repeat(2,minmax(0,1fr));row-gap:20px}.actions button{font-size:11px;padding:10px}.checked{font-size:10px}footer{justify-content:center}.pagination{justify-content:center}footer p{text-align:center}}
  @media(prefers-reduced-motion:reduce){.loading-dot,.skeleton-line,.skeleton-value{animation:none}button{transition:none}}
</style>
