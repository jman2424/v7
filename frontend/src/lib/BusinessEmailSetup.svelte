<script lang="ts">
  import {onMount,onDestroy} from 'svelte';
  export let tenant:string;
  export let csrf:string;
  export let canManage=false;
  export let apiPrefix='';
  let address='',provider='hosted_email',revision='',state='not_started',loading=true,busy=false,disposed=false;
  let storageAvailable=false,cleanupCounts:Record<string,number>|null=null;
  let forwardTo:string[]=[];
  let message='',error=false;
  const controllers=new Set<AbortController>();
  const states:Record<string,string>={not_started:'Not set up',requested:'Awaiting mailbox verification and routing',routing_configured:'Mailbox routing configured'};
  async function request(method='GET') {
    const controller=new AbortController();controllers.add(controller);
    try {
      const response=await fetch(`${apiPrefix}/admin/api/business-email-setup?tenant=${encodeURIComponent(tenant)}`,{
        method,credentials:'same-origin',signal:controller.signal,
        headers:{'X-CSRF-Token':csrf,...(method==='PUT'?{'Content-Type':'application/json'}:{})},
        ...(method==='PUT'?{body:JSON.stringify({revision,settings:{address,provider,purpose:'support'}})}:{})});
      const data=await response.json();
      if(!response.ok)throw new Error(data.error==='email_setup_disable_before_change'?
        'Disable email handling before changing its connected address.':'Could not save or load email setup. Refresh and check the address and your permissions.');
      return data;
    } finally {controllers.delete(controller);}
  }
  function apply(data:any) {
    address=data.settings.address;provider=data.settings.provider;revision=data.revision;state=data.state;
    storageAvailable=data.storage_available;cleanupCounts=data.cleanup_counts;
    forwardTo=data.forward_to||[];
  }
  async function load() {
    try {const data=await request();if(!disposed)apply(data);}
    catch(err){if(!disposed){error=true;message=err instanceof Error?err.message:'Email setup is unavailable.';}}
    finally{if(!disposed)loading=false;}
  }
  async function save() {
    if(!canManage||busy)return;
    busy=true;message='';error=false;
    try {const data=await request('PUT');if(!disposed){apply(data);message=data.state==='routing_configured'?
      'Setup saved. Check the connection and choose your reply and retention settings below.':
      'Setup request saved. Your platform operator must verify the mailbox and configure its routing before it can receive or send mail.';}}
    catch(err){if(!disposed){error=true;message=err instanceof Error?err.message:'Could not save setup.';}}
    finally{if(!disposed)busy=false;}
  }
  onMount(load);
  onDestroy(()=>{disposed=true;for(const controller of controllers)controller.abort();});
</script>

<section aria-labelledby="client-email-title" class="setup">
  <h3 id="client-email-title">Set up your company’s support email</h3>
  <p>Connect a support address your business controls. Replies use this account’s saved business knowledge, policies and approved links.</p>
  <ol><li><strong>Choose your mailbox.</strong> Save its address below. This requests setup; it does not connect your whole email account.</li>
    <li><strong>Verify and route enquiries.</strong> Your platform operator verifies the sending address and gives you any forwarding or domain setup needed. Google Workspace, Microsoft 365 and other hosted mail use verified forwarding here; direct Google/Microsoft sign-in is not available yet.</li>
    <li><strong>Choose replies and retention.</strong> Start with review-first drafts, choose how long V7 keeps message content, then enable the channel once its connection is ready.</li></ol>
  {#if loading}<p role="status">Loading email setup…</p>{:else}
    <p><strong>{states[state]||'Check setup'}</strong></p>
    {#if forwardTo.length}<p>After your operator confirms verification, forward support enquiries from <strong>{address}</strong> to:</p><ul>{#each forwardTo as target}<li><code>{target}</code></li>{/each}</ul><p>V7 replies from your approved business address. Forward only the mailbox or messages you want the assistant to handle.</p>{/if}
    {#if !storageAvailable}<p class="notice">The platform’s email queue storage is not available yet. You can prepare setup, but live processing must remain off until the operator provisions it.</p>{/if}
    <form on:submit|preventDefault={save}>
      <label>Company support email<input type="email" bind:value={address} maxlength="254" placeholder="support@yourcompany.com" required disabled={!canManage||busy}/></label>
      <label>Where you manage this mailbox<select bind:value={provider} disabled={!canManage||busy}>
        <option value="hosted_email">Other hosted business email</option><option value="google_workspace">Google Workspace</option>
        <option value="microsoft_365">Microsoft 365</option><option value="resend_inbox">Resend Inbox</option>
      </select></label>
      <p>Use an address you are authorised to connect. A verified sending domain or approved sender is required; entering an address does not prove ownership. Do not enter your mailbox password or API keys here.</p>
      <button type="submit" disabled={!canManage||busy}>{busy?'Saving…':'Save support email setup'}</button>
    </form>
    {#if message}<p role="status" class:error>{message}</p>{/if}
    <p class="notice">V7 answers routine business support questions. Account access, refunds, cancellations and other consequential requests need the configured verification and approval steps. A sender address is not account authentication.</p>
    {#if cleanupCounts&&Object.keys(cleanupCounts).length}<h4>Recent connected-inbox cleanup</h4><ul>
      <li>Conversations moved to Trash: {cleanupCounts.retention_trashed||0}</li><li>Kept for review or newer activity: {cleanupCounts.retention_skipped||0}</li>
      <li>Reopened after newer activity: {cleanupCounts.retention_restored||0}</li><li>Outcomes requiring a provider check: {cleanupCounts.retention_failed||0}</li>
    </ul>{/if}
  {/if}
</section>

<style>
  .setup{padding:1.25rem;border:1px solid #d6dfda;border-radius:12px;background:white}h3,h4{margin:.2rem 0 .8rem}p,li{line-height:1.5}li{margin:.5rem 0}form{max-width:620px}label{display:grid;gap:.4rem;margin:1rem 0}input,select,button{font:inherit;padding:.7rem;border:1px solid #bdc9c2;border-radius:7px;box-sizing:border-box;max-width:100%;min-width:0}button{color:#14503b;background:#f3f7f4;cursor:pointer;min-height:44px}button:disabled{opacity:.6;cursor:not-allowed}.notice{padding:.8rem;background:#f3f7f4;border-radius:8px}.error{color:#9b1c1c}
</style>
