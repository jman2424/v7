<script lang="ts">
  import {focusSearchDestination,loadSearchRecords} from './workspaceSearch';
  import {pushState} from '$app/navigation';
  import {page} from '$app/state';
  import {onMount,onDestroy} from 'svelte';
  import {findSections, type SectionResult} from './sectionSearch';
  export let items:SectionResult[]=[];
  export let label='Find account sections';
  export let placeholder='Search sections…';
  export let empty='No matching sections available to your account.';
  export let tenant:string;
  export let apiPrefix='';
  export let allowCustomers=false;
  let records:SectionResult[]=[];
  let controls:SectionResult[]=[];
  const targets=new Map<string,HTMLElement>();
  function indexControls(){
    controls=[];targets.clear();
    const nodes=document.querySelectorAll<HTMLElement>('#workspace section label, #workspace section summary, #workspace section h2, #workspace section h3');
    const found:SectionResult[]=[];
    for(const node of nodes){
      if(node.closest('[hidden], [aria-hidden="true"]') || !node.getClientRects().length)continue;
      const target=node instanceof HTMLLabelElement?node.control:node;
      if(!(target instanceof HTMLElement)||target.matches(':disabled'))continue;
      const label=Array.from(node.childNodes).filter(child=>child.nodeType===Node.TEXT_NODE).map(child=>child.textContent).join(' ').trim()
        || target.getAttribute('aria-label') || (node.querySelector('input,textarea,select')?'':node.textContent?.trim());
      if(!label || label.length>150)continue;
      const key='control-'+found.length;
      targets.set(key,target);
      found.push({key,label,description:'On this page',keywords:'',href:'#workspace',reload:false});
    }
    controls=found;
  }
  function choose(event:MouseEvent,item:SectionResult){
    if(event.button!==0||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;
    let target=targets.get(item.key);
    if(!target){
      const destination=new URL(item.href,location.href);
      const current=new URL(location.href);
      // "focus" identifies a search result; the remaining parameters select the business and view.
      current.searchParams.delete('focus');
      destination.searchParams.delete('focus');
      if(destination.pathname===current.pathname && destination.search===current.search && destination.hash){
        const node=document.getElementById(destination.hash.slice(1).replace(/^jump-/,''));
        if(node && node.getClientRects().length){
          if(new URL(item.href,location.href).href!==location.href)pushState(item.href,page.state);
          target=node;
        }
      }
    }
    if(target?.isConnected){
      event.preventDefault();
      focusSearchDestination(target);
    }
    close();
  }
  let controller:AbortController|undefined;
  let searching=false;
  let partial=false;
  let remote:SectionResult[]=[];
  let remoteRequest:AbortController|undefined;
  let timer:ReturnType<typeof setTimeout>;
  let remoteBusy=false,remotePartial=false;
  function refreshRemote(text:string){
    clearTimeout(timer);remoteRequest?.abort();remote=[];remotePartial=false;
    remoteBusy=text.length>=2;
    if(!remoteBusy)return;
    const request=new AbortController();
    remoteRequest=request;
    timer=setTimeout(async()=>{
      const failed=await loadSearchRecords(items,tenant,apiPrefix,request.signal,found=>{
        if(!request.signal.aborted)remote=[...remote,...found];
      },allowCustomers,text);
      if(!request.signal.aborted){remotePartial=failed;remoteBusy=false;}
    },250);
  }
  function reset(){
    refreshRemote('');
    controller?.abort();controller=undefined;
    records=[];searching=false;partial=false;
  }
  function start(){
    if(controller)return;
    const request=new AbortController();
    controller=request;searching=true;
    loadSearchRecords(items,tenant,apiPrefix,request.signal,found=>{
      if(controller===request)records=[...records,...found];
    },allowCustomers).then(failed=>{
      if(controller===request){searching=false;partial=failed;}
    });
  }
  onDestroy(reset);
  let query='';
  let open=false;
  let input:HTMLInputElement;
  function close(){open=false;query='';reset();controls=[];targets.clear();}
  let resultsElement:HTMLUListElement;
  let searchElement:HTMLDivElement;
  onMount(()=>{
    const outside=(event:PointerEvent)=>{if(event.target instanceof Node&&!searchElement.contains(event.target))close();};
    document.addEventListener('pointerdown',outside);return()=>document.removeEventListener('pointerdown',outside);
  });
  function keyboard(event:KeyboardEvent){
    if(event.key==='Escape'){event.preventDefault();input.focus();close();}
    if(event.key==='ArrowDown'&&open){event.preventDefault();resultsElement?.querySelector('a')?.focus();}
  }
  $: if(open&&query.trim().length>=2)start();
  $: refreshRemote(open?query.trim():'');
  $: results=findSections([...items,...records,...remote,...controls],query);
  let visible=20;
  $: {query;visible=20;}
</script>

<div class="section-search" bind:this={searchElement} on:focusout={(event)=>{if(!searchElement.contains(event.relatedTarget as Node|null))close();}}>
  <form role="search" aria-label={label} on:submit|preventDefault={()=>resultsElement?.querySelector('a')?.click()}>
    <label class="search-field">
      <svg class="search-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4.5 4.5"/></svg>
      <input aria-label={label} type="search" bind:value={query} bind:this={input} on:focus={()=>{open=true;indexControls();}} on:input={()=>open=true} on:click={()=>open=true} {placeholder} autocomplete="off" on:keydown={keyboard} /></label>
  </form>
  {#if open && (results.length || query.trim())}
    <div class="section-results" aria-label={label}>
      <ul bind:this={resultsElement}>
        {#each results.slice(0,visible) as item (item.key)}
          <li><a href={item.href} data-sveltekit-reload={item.reload?true:undefined} on:keydown={(event)=>{if(event.key==='Escape')keyboard(event);}} on:click={(event)=>choose(event,item)}><strong>{item.label}</strong>{#if item.description}<span>{item.description}</span>{/if}<i aria-hidden="true"></i></a></li>
        {/each}
      </ul>
      {#if results.length>visible}<button type="button" on:click={()=>visible+=20}>Show more results</button>{/if}
      {#if searching||remoteBusy}<p role="status">Searching workspace records…</p>{:else if !results.length}<p role="status">{empty}</p>{/if}
      {#if partial||remotePartial}<p role="status">Some record lists could not be loaded.</p>{/if}
    </div>
  {/if}
</div>

<style>
  .section-search {
    position:relative; flex:1 1 280px; min-width:230px; max-width:380px;
  }
  .search-field {
    display:flex; align-items:center; gap:var(--v7-space-2); box-sizing:border-box;
    min-height:44px; padding-inline:var(--v7-space-3); cursor:text;
    background:var(--v7-surface); border:1px solid var(--v7-control-line); border-radius:var(--v7-radius-control);
  }
  .search-icon { flex:none; color:var(--v7-accent); }
  .search-field:focus-within {
    border-color:var(--v7-accent); outline:3px solid var(--v7-mint-line); outline-offset:1px;
  }
  .search-field input {
    flex:1; min-width:0; width:100%; height:42px; padding:0; border:0; outline:0;
    background:transparent; color:var(--v7-ink); font:inherit; font-size:var(--v7-text-sm);
  }
  input::placeholder { color:var(--v7-muted); opacity:1; }
  .section-results {
    position:absolute; z-index:40; inset-inline:0; top:calc(100% + var(--v7-space-2));
    max-height:min(380px,55dvh); overflow:auto; overscroll-behavior:contain;
    background:var(--v7-surface); border:1px solid var(--v7-line);
    border-radius:var(--v7-radius-panel); box-shadow:var(--v7-shadow-float);
  }
  ul { list-style:none; margin:0; padding:var(--v7-space-1); }
  li a {
    display:grid; grid-template-columns:minmax(0,1fr) auto; align-content:center; column-gap:var(--v7-space-3);
    min-height:44px; box-sizing:border-box; padding:var(--v7-space-2) var(--v7-space-3);
    color:var(--v7-ink); border-radius:var(--v7-radius-control); text-decoration:none;
  }
  a strong { font-size:var(--v7-text-sm); font-weight:600; line-height:1.4; overflow-wrap:anywhere; }
  a span { grid-column:1; font-size:var(--v7-text-xs); color:var(--v7-muted); line-height:1.4; }
  a i {
    grid-column:2; grid-row:1 / span 2; align-self:center; width:6px; height:6px; margin-inline-end:3px;
    border-block-start:1.5px solid currentColor; border-inline-end:1.5px solid currentColor;
    transform:rotate(45deg); color:var(--v7-muted);
  }
  :global([dir=rtl]) a i { transform:rotate(-45deg); }
  li a:hover, li a:focus-visible { color:var(--v7-on-mint); background:var(--v7-mint-soft); }
  li a:focus-visible, button:focus-visible { outline:2px solid var(--v7-accent); outline-offset:-2px; }
  p, button { margin:0; padding:var(--v7-space-3) var(--v7-space-4); font-size:var(--v7-text-xs); }
  p { color:var(--v7-muted); }
  button {
    width:100%; min-height:44px; border:0; border-top:1px solid var(--v7-line);
    background:var(--v7-canvas); color:var(--v7-accent); font-family:inherit; font-weight:600; cursor:pointer;
  }
  @media(prefers-reduced-motion:no-preference){
    .section-results{animation:search-appear 110ms var(--v7-ease-out)}
    li a,.search-field{transition:background-color 90ms ease-out,border-color 90ms ease-out}
  }
  @keyframes search-appear{from{opacity:0;transform:translateY(-3px)}to{opacity:1;transform:translateY(0)}}
  @media(max-width:700px){.section-search{min-width:0;max-width:none}}
</style>
