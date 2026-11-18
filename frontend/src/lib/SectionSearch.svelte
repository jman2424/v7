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
    <label><span class="search-label">{label}</span><input type="search" bind:value={query} bind:this={input} on:focus={()=>{open=true;indexControls();}} on:input={()=>open=true} on:click={()=>open=true} {placeholder} autocomplete="off" on:keydown={keyboard} /></label>
  </form>
  {#if open && (results.length || query.trim())}
    <div class="section-results" aria-label={label}>
      <ul bind:this={resultsElement}>
        {#each results.slice(0,visible) as item (item.key)}
          <li><a href={item.href} data-sveltekit-reload={item.reload?true:undefined} on:keydown={(event)=>{if(event.key==='Escape')keyboard(event);}} on:click={(event)=>choose(event,item)}><strong>{item.label}</strong><span>{item.description}</span></a></li>
        {/each}
      </ul>
      {#if results.length>visible}<button type="button" on:click={()=>visible+=20}>Show more results</button>{/if}
      {#if searching||remoteBusy}<p role="status">Searching workspace records…</p>{:else if !results.length}<p role="status">{empty}</p>{/if}
      {#if partial||remotePartial}<p role="status">Some record lists could not be loaded.</p>{/if}
    </div>
  {/if}
</div>

<style>
  .section-search{position:relative;min-width:230px;max-width:380px;flex:1}
  .search-label{display:block;font-size:.75rem;color:var(--v7-muted);margin-bottom:4px}
  input{width:100%;min-height:44px;padding:10px 12px;border:1px solid var(--v7-control-line);border-radius:var(--v7-radius-control);background:var(--v7-surface);color:var(--v7-ink);font:inherit;font-size:var(--v7-text-xs)}input:focus-visible{outline:3px solid var(--v7-focus);outline-offset:3px}
  @media(prefers-reduced-motion:no-preference){
    .section-results{animation:search-appear 110ms ease-out}
    .section-results a{transition:background-color 90ms ease-out}
  }
  @keyframes search-appear{from{opacity:0;transform:translateY(-3px)}to{opacity:1;transform:translateY(0)}}
  .section-results{position:absolute;z-index:40;top:100%;inset-inline:0;background:var(--v7-surface,#fff);border:1px solid var(--v7-line,#dce2df);border-radius:var(--v7-radius-panel);box-shadow:0 12px 30px #0002;max-height:360px;overflow:auto}
  ul{list-style:none;margin:0;padding:6px}a{display:block;padding:10px;text-decoration:none;border-radius:var(--v7-radius-control)}a:hover,a:focus-visible{background:var(--v7-canvas,#f3f6f4)}strong,span{display:block}span,p{font-size:.8rem;color:var(--v7-muted)}p{padding:8px 12px}
  @media(max-width:700px){.section-search{min-width:0;flex-basis:100%;max-width:none}}
</style>
