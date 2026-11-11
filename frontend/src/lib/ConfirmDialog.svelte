<script lang="ts">
 import {onDestroy,tick} from 'svelte';
 import {t} from './i18n';
 export let title='Discard unsaved changes?';
 export let description='Your saved settings will stay unchanged. Changes you have not saved will be lost.';
 export let confirmLabel='Discard changes';
 let dialog:HTMLDialogElement;
 let resolve:((value:boolean)=>void)|undefined;
 let cancelButton:HTMLButtonElement;
 export async function ask(){
  if(resolve)return false;
  await tick();
  return new Promise<boolean>(done=>{resolve=done;dialog.showModal();cancelButton?.focus();});
 }
 function finish(value:boolean){dialog.close();const done=resolve;resolve=undefined;done?.(value);}
 onDestroy(()=>resolve?.(false));
</script>
<dialog bind:this={dialog} aria-label={$t(title)} on:cancel|preventDefault={()=>finish(false)}>
 <h2>{$t(title)}</h2><p>{$t(description)}</p><div class="buttons"><button bind:this={cancelButton} on:click={()=>finish(false)}>{$t('Keep editing')}</button><button class="danger" on:click={()=>finish(true)}>{$t(confirmLabel)}</button></div>
</dialog>
<style>
 dialog{width:min(440px,calc(100vw - 32px));padding:28px;background:var(--v7-surface);color:var(--v7-ink);border:1px solid var(--v7-line);border-radius:var(--v7-radius-panel);box-shadow:0 20px 80px #132f2529}dialog::backdrop{background:#15332766}h2{margin:0 0 12px;font-size:var(--v7-text-xl);font-weight:600;letter-spacing:-.035em}p{margin:0;color:var(--v7-muted);line-height:1.7;font-size:var(--v7-text-sm)}.buttons{display:flex;justify-content:flex-end;flex-wrap:wrap;gap:10px;margin-top:25px}button{min-height:44px;border:1px solid var(--v7-control-line);border-radius:var(--v7-radius-control);padding:11px 15px;font:inherit;font-size:var(--v7-text-xs);font-weight:600;cursor:pointer;background:var(--v7-surface);color:var(--v7-ink)}.danger{color:#fff;background:var(--v7-danger);border-color:var(--v7-danger)}button:focus-visible{outline:3px solid var(--v7-focus);outline-offset:3px}
</style>
