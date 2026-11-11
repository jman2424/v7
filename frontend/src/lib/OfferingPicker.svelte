<script lang="ts">
 import {t} from './i18n';
 export let options:{sku:string;name:string}[]=[];
 export let selected:string[]=[];
 let query='';
 $: known=new Set(options.map(option=>option.sku));
 $: unmatched=selected.filter(value=>!known.has(value));
 $: filtered=options.filter(option=>(option.name+' '+option.sku).toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
 function toggle(sku:string,checked:boolean){selected=checked?[...new Set([...selected,sku])]:selected.filter(value=>value!==sku);}
</script>
<details class="offering-picker"><summary>{selected.length?$t('{count} products or services selected',{count:selected.length}):$t('Applies to all products & services')}</summary><p>{$t('Choose specific offerings, or leave the selection empty to apply this offer to all.')}</p><label>{$t('Find offerings')}<input type="search" bind:value={query} placeholder={$t('Search products & services…')}/></label><div class="choices">{#each filtered as option}<label class="choice"><input type="checkbox" checked={selected.includes(option.sku)} on:change={(event)=>toggle(option.sku,event.currentTarget.checked)}/><span>{option.name}</span></label>{:else}<p>{$t('No matching offerings.')}</p>{/each}</div>{#if unmatched.length}<details class="unknown"><summary>{$t('Other saved references')}</summary><p>{$t('These references are preserved. Remove one only if it should no longer be eligible.')}</p>{#each unmatched as sku}<label class="choice"><input type="checkbox" checked on:change={()=>toggle(sku,false)}/><code>{sku}</code></label>{/each}</details>{/if}</details>
<style>
 .offering-picker{padding:16px;border:1px solid var(--v7-line);border-radius:var(--v7-radius-panel);background:var(--v7-canvas)}summary{cursor:pointer;min-height:28px;line-height:1.6;font-size:var(--v7-text-xs);color:var(--v7-accent);font-weight:600}p{font-size:var(--v7-text-xs);line-height:1.7;color:var(--v7-muted);margin:12px 0}label{display:grid;gap:8px;font-size:var(--v7-text-xs);color:var(--v7-muted)}input[type=search]{width:100%;min-height:44px;padding:10px 12px;font:inherit;border:1px solid var(--v7-control-line);border-radius:var(--v7-radius-control);background:var(--v7-surface);color:var(--v7-ink)}.choices{max-height:240px;overflow:auto;margin-top:12px;border-top:1px solid var(--v7-line)}.choice{display:flex;align-items:center;gap:10px;min-height:44px;padding:10px 0;color:var(--v7-ink);font-size:var(--v7-text-xs)}.choice input{width:17px;height:17px;flex:none;accent-color:var(--v7-accent)}.unknown{margin-top:15px}code{overflow-wrap:anywhere}summary:focus-visible,input:focus-visible{outline:3px solid var(--v7-focus);outline-offset:3px}
</style>
