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
 dialog{width:min(440px,calc(100vw - 32px));padding:28px;background:white;color:var(--v7-ink);border:1px solid var(--v7-line);border-radius:16px;box-shadow:0 20px 80px #132f2529}dialog::backdrop{background:#15332766}h2{margin:0 0 12px;font-size:21px;font-weight:600;letter-spacing:-.035em}p{margin:0;color:var(--v7-muted);line-height:1.7;font-size:13px}.buttons{display:flex;justify-content:flex-end;flex-wrap:wrap;gap:10px;margin-top:25px}button{min-height:44px;border:1px solid var(--v7-control-line);border-radius:8px;padding:11px 15px;font:inherit;font-size:12px;font-weight:600;cursor:pointer;background:white;color:var(--v7-ink)}.danger{color:#fff;background:#883b31;border-color:#883b31}button:focus-visible{outline:3px solid var(--v7-focus);outline-offset:3px}
</style>
