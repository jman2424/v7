<script lang="ts">
 import {beforeNavigate,goto} from '$app/navigation';
 import {onMount} from 'svelte';
 import {registerDraft,navigationApproved,beginDraftPrompt,approveDraftNavigation,finishDraftPrompt} from './draftNavigation';
 import ConfirmDialog from './ConfirmDialog.svelte';
 export let dirty=false;
 export let preserveOnSoftNavigation=false;
 let confirmation:ConfirmDialog;
 onMount(()=>registerDraft(()=>dirty));
 beforeNavigate(navigation=>{
  if(!dirty||navigationApproved(navigation.to?.url.href||'')||(!navigation.willUnload&&preserveOnSoftNavigation))return;
  navigation.cancel();
  // SvelteKit uses the browser's native leave confirmation for document unloads.
  if(navigation.willUnload||!navigation.to?.url||!beginDraftPrompt())return;
  const url=navigation.to.url;
  void confirmation.ask().then(async leave=>{
   if(leave){approveDraftNavigation(url.href);await goto(url.href);}
  }).finally(finishDraftPrompt);
 });
</script>
<ConfirmDialog bind:this={confirmation}/>
