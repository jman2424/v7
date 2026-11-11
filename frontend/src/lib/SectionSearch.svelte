<script lang="ts">
  import {onMount} from 'svelte';
  import {findSections, type SectionResult} from './sectionSearch';
  export let items:SectionResult[]=[];
  export let label='Find account sections';
  export let placeholder='Search sections…';
  export let empty='No matching sections available to your account.';
  let query='';
  let resultsElement:HTMLUListElement;
  let searchElement:HTMLDivElement;
  onMount(()=>{
    const outside=(event:PointerEvent)=>{if(event.target instanceof Node&&!searchElement.contains(event.target))query='';};
    document.addEventListener('pointerdown',outside);return()=>document.removeEventListener('pointerdown',outside);
  });
  function keyboard(event:KeyboardEvent){
    if(event.key==='Escape')query='';
    if(event.key==='ArrowDown'&&query.trim()){event.preventDefault();resultsElement?.querySelector('a')?.focus();}
  }
  $: results=findSections(items,query);
</script>

<div class="section-search" bind:this={searchElement}>
  <form role="search" aria-label={label} on:submit|preventDefault={()=>resultsElement?.querySelector('a')?.click()}>
    <label><span class="search-label">{label}</span><input type="search" bind:value={query} {placeholder} autocomplete="off" on:keydown={keyboard} /></label>
  </form>
  {#if query.trim()}
    <div class="section-results" aria-label={label}>
      <ul bind:this={resultsElement}>
        {#each results as item (item.key)}
          <li><a href={item.href} data-sveltekit-reload={item.reload?true:undefined} on:click={()=>query=''}><strong>{item.label}</strong><span>{item.description}</span></a></li>
        {/each}
      </ul>
      {#if !results.length}<p role="status">{empty}</p>{/if}
    </div>
  {/if}
</div>

<style>
  .section-search{position:relative;min-width:230px;max-width:380px;flex:1}
  .search-label{display:block;font-size:.75rem;color:var(--v7-muted);margin-bottom:4px}
  input{width:100%;min-height:44px;padding:10px 12px;border:1px solid var(--v7-control-line);border-radius:var(--v7-radius-control);background:var(--v7-surface);color:var(--v7-ink);font:inherit;font-size:var(--v7-text-xs)}input:focus-visible{outline:3px solid var(--v7-focus);outline-offset:3px}
  .section-results{position:absolute;z-index:40;top:100%;inset-inline:0;background:var(--v7-surface,#fff);border:1px solid var(--v7-line,#dce2df);border-radius:var(--v7-radius-panel);box-shadow:0 12px 30px #0002;max-height:360px;overflow:auto}
  ul{list-style:none;margin:0;padding:6px}a{display:block;padding:10px;text-decoration:none;border-radius:var(--v7-radius-control)}a:hover,a:focus-visible{background:var(--v7-canvas,#f3f6f4)}strong,span{display:block}span,p{font-size:.8rem;color:var(--v7-muted)}p{padding:8px 12px}
  @media(max-width:700px){.section-search{min-width:0;flex-basis:100%;max-width:none}}
</style>
