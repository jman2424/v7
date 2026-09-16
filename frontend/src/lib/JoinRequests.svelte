<script lang="ts">
  import {onMount} from 'svelte';
  export let tenant:string;
  export let csrf:string;
  export let apiPrefix='';
  let requests:{id:string;email:string;created:number}[]=[];
  let busy=false, error='';
  async function refresh(){
    busy=true;error='';
    try{const response=await fetch(apiPrefix+'/admin/api/join-requests?tenant='+encodeURIComponent(tenant),{credentials:'same-origin'});
      if(!response.ok)throw new Error('Join requests could not be loaded.');requests=(await response.json()).requests;
    }catch(e){error=e instanceof Error?e.message:'Could not connect.';}finally{busy=false;}
  }
  onMount(refresh);
  async function decide(id:string,decision:'approve'|'reject'){
    busy=true;error='';
    try{const response=await fetch(apiPrefix+'/admin/api/join-requests/'+encodeURIComponent(id)+'?tenant='+encodeURIComponent(tenant),{
      method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify({decision})});
      const data=await response.json();if(!response.ok)throw new Error(data.error||'Request could not be updated.');await refresh();
    }catch(e){error=e instanceof Error?e.message:'Could not connect.';}finally{busy=false;}
  }
</script>
<section aria-label="Tenant join requests">
  <h3>Requests to join {tenant}</h3><p>These applicants verified their email. Approve only people you recognise. Approval creates a staff account with no billing permissions; authenticator setup is required at sign-in.</p>
  {#if error}<p role="alert">{error}</p>{/if}
  {#each requests as item}<article><strong>{item.email}</strong><span>{new Date(item.created*1000).toLocaleDateString()}</span><button disabled={busy} on:click={()=>decide(item.id,'approve')}>Approve staff access</button><button disabled={busy} on:click={()=>decide(item.id,'reject')}>Reject</button></article>
  {:else}<p>{busy?'Loading requests…':'No pending requests.'}</p>{/each}
  <button disabled={busy} on:click={refresh}>Refresh requests</button>
</section>
<style>
  section{padding:24px}article{display:flex;align-items:center;flex-wrap:wrap;gap:12px;padding:16px 0;border-bottom:1px solid #dce3dc}strong{overflow-wrap:anywhere}p{line-height:1.6;color:#526359}button{font:inherit;padding:10px 14px;border:1px solid #bbc4bc;border-radius:6px;background:white;color:#20332a;cursor:pointer;min-height:44px}button:disabled{opacity:.6}button:focus-visible{outline:3px solid #008879;outline-offset:3px}
</style>
