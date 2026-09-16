<script lang="ts">
  import { onMount, createEventDispatcher } from 'svelte';
  export let csrf = '';
  export let apiPrefix = '';
  const dispatch = createEventDispatcher<{login: {tenant:string;email:string}}>();
  type RequestState = {status:string;email:string;tenant:string};
  let enabled = false, loaded = false, busy = false;
  let error = '', email = '', password = '', tenant = '', businessName = '', code = '';
  let kind = 'owner';
  let state:RequestState|null = null;
  async function refresh() {
    try {
      const response=await fetch(apiPrefix+'/auth/registration',{credentials:'same-origin'});
      if(!response.ok)throw new Error();
      const data=await response.json(); enabled=data.enabled; state=data.request; loaded=true;
    } catch {error='Signup status could not be loaded. Try again.';}
  }
  onMount(refresh);
  async function submit() {
    if(busy)return;
    busy=true;error='';
    try {
      const sessionResponse=await fetch(apiPrefix+'/auth/session',{credentials:'same-origin'});
      if(!sessionResponse.ok)throw new Error('Reload the page to start a secure signup session.');
      csrf=(await sessionResponse.json()).csrf_token;
      const verifying=state?.status==='verification';
      const response=await fetch(apiPrefix+(verifying?'/auth/register/confirm':'/auth/register'),{
        method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},
        body:JSON.stringify(verifying?{code}:{email,password,tenant,business_name:businessName,kind})});
      const data=await response.json();
      if(!response.ok)throw new Error(data.error || 'The request could not be completed.');
      state=data.request;password='';code='';
    } catch(failure) {error=failure instanceof Error?failure.message:'Could not connect. Try again.';}
    finally {busy=false;}
  }
</script>

<section class="registration" aria-labelledby="signup-title">
  <h1 id="signup-title">Create your V7 account</h1>
  {#if error}<p role="alert" class="error">{error}</p>{/if}
  {#if !loaded}<p>Checking signup availability…</p><button on:click={refresh}>Retry</button>
  {:else if state?.status==='approved'}
    <h2>Account ready</h2><p>Your company key is <strong>{state.tenant}</strong>. Sign in with your password and set up your authenticator. New business owners can then complete payment before adding business data.</p>
    <button on:click={()=>dispatch('login',{tenant:state!.tenant,email:state!.email})}>Go to sign in</button>
  {:else if state?.status==='pending'}
    <h2>Waiting for the business owner</h2><p>Your email is verified. The owner of <strong>{state.tenant}</strong> must approve your staff-access request. You have no access to their data yet.</p><button disabled={busy} on:click={refresh}>Refresh request status</button>
  {:else if state?.status==='rejected'}
    <p>The business owner declined this request. Contact them if you think this is a mistake.</p>
  {:else if state?.status==='creating'}
    <p>Your workspace is being created. Refresh shortly, or contact the operator if this continues.</p><button on:click={refresh}>Refresh status</button>
  {:else if !enabled}
    <p>Account creation is not available yet. The platform operator must configure verification email first. Existing accounts can still sign in.</p>
  {:else}
    <form on:submit|preventDefault={submit}>
      {#if state?.status==='verification'}
        <p>Enter the code sent to <strong>{state.email}</strong>. It expires after 10 minutes. Verification does not grant access to an existing business.</p>
        <label>Email verification code<input bind:value={code} inputmode="numeric" pattern={'[0-9]{6}'} maxlength="6" autocomplete="one-time-code" required/></label>
        <button disabled={busy} type="submit">{busy?'Verifying…':'Verify email'}</button>
        <button disabled={busy} type="button" on:click={()=>{state=null;code='';}}>Start again</button>
      {:else}
        {#if state}<p>Your previous request could not be completed or has expired. Start a new request.</p>{/if}
        <label>I want to<select bind:value={kind}><option value="owner">Create my business workspace</option><option value="join">Request to join an existing business</option></select></label>
        <label>Email<input type="email" maxlength="254" autocomplete="email" bind:value={email} required/></label>
        <label>Password<input type="password" minlength="12" maxlength="256" autocomplete="new-password" bind:value={password} required/><small>At least 12 characters. An authenticator is also required at sign-in.</small></label>
        <label>{kind==='owner'?'New company key':'Company key from your business owner'}<input bind:value={tenant} maxlength="64" pattern={'[A-Za-z0-9][A-Za-z0-9_\\-]{0,63}'} required/></label>
        {#if kind==='owner'}<label>Business name<input bind:value={businessName} maxlength="120" required/></label><p>After email verification, sign in and pay the platform subscription and implementation fee. Business data and the agent unlock only after payment is confirmed.</p>
        {:else}<p>Your verified request goes to this business’s owner. Approval grants staff access only, with no billing permissions by default.</p>{/if}
        <button disabled={busy} type="submit">{busy?'Sending…':'Send verification code'}</button>
      {/if}
    </form>
  {/if}
</section>

<style>
  .registration{background:white;border:1px solid #dce3dc;border-radius:10px;padding:32px;max-width:520px;width:100%;box-sizing:border-box}h1{font-size:25px;margin:0 0 20px}h2{font-size:19px}p{line-height:1.6;color:#526359}form,label{display:grid;gap:10px}form{gap:18px}input,select,button{font:inherit;padding:12px;border:1px solid #b8c6be;border-radius:6px;max-width:100%;box-sizing:border-box}button{cursor:pointer;background:#007d70;color:white;min-height:44px}button:disabled{opacity:.6;cursor:wait}small{font-weight:normal;color:#526359}.error{color:#ad2020}:focus-visible{outline:3px solid #8bcdc0;outline-offset:2px}
</style>
