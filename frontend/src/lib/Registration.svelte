<script lang="ts">
  import { t } from './i18n';
  import { onMount, onDestroy, createEventDispatcher } from 'svelte';
  export let csrf = '';
  export let apiPrefix = '';
  const dispatch = createEventDispatcher<{login: {tenant:string;email:string}}>();
  type RequestState = {status:string;email:string;tenant:string};
  let enabled = false, loaded = false, busy = false, sender = '';
  let error = '', email = '', password = '', tenant = '', businessName = '', code = '';
  let kind = 'owner';
  let state:RequestState|null = null;
  let alive = true;
  const requests = new Set<AbortController>();
  async function requestJson(path: string, options: RequestInit = {}) {
    const controller = new AbortController();
    requests.add(controller);
    const deadline = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch(apiPrefix + path, {...options, credentials:'same-origin', signal:controller.signal});
      const data = await response.json();
      if (controller.signal.aborted) throw new Error('Request timed out. Check request status before trying again.');
      return {response, data};
    } catch (failure) {
      if (controller.signal.aborted) throw new Error('Request timed out. Check request status before trying again.');
      throw failure;
    } finally { clearTimeout(deadline); requests.delete(controller); }
  }
  onDestroy(() => { alive = false; for (const controller of requests) controller.abort(); });
  async function refresh() {
    if(busy)return;
    busy=true;error='';
    try {
      const {response, data}=await requestJson('/auth/registration');
      if(!response.ok)throw new Error();
      if(!alive)return;
      enabled=data.enabled; sender=typeof data.sender==='string'?data.sender:''; state=data.request; loaded=true;
    } catch {if(alive)error='Signup status could not be loaded. Try again.';}
    finally {if(alive)busy=false;}
  }
  onMount(refresh);
  async function submit() {
    if(busy)return;
    busy=true;error='';
    try {
      let sessionResult=await requestJson('/auth/session');
      if(sessionResult.response.status===401)sessionResult=await requestJson('/auth/session');
      if(!alive)return;
      if(!sessionResult.response.ok)throw new Error('Reload the page to start a secure signup session.');
      csrf=sessionResult.data.csrf_token;
      if(typeof csrf!=='string'||!csrf)throw new Error('Reload the page to start a secure signup session.');
      const verifying=state?.status==='verification';
      const {response,data}=await requestJson(verifying?'/auth/register/confirm':'/auth/register',{
        method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},
        body:JSON.stringify(verifying?{code}:{email,password,tenant,business_name:businessName,kind})});
      if(!alive)return;
      if(!response.ok)throw new Error(data.error || 'The request could not be completed.');
      state=data.request;password='';code='';
    } catch(failure) {if(alive)error=failure instanceof Error?failure.message:'Could not connect. Try again.';}
    finally {if(alive)busy=false;}
  }
</script>

<section class="registration" aria-labelledby="signup-title">
  <h1 id="signup-title">Create your V7 account</h1>
  {#if error}<p role="alert" class="error">{error}</p>{#if loaded}<button disabled={busy} type="button" on:click={refresh}>Check request status</button>{/if}{/if}
  {#if !loaded}<p>Checking signup availability…</p><button disabled={busy} on:click={refresh}>Retry</button>
  {:else if state?.status==='approved'}
    <h2>Account ready</h2><p>Your company key is <strong>{state.tenant}</strong>. Sign in with your password and set up your authenticator. New business owners can then complete payment before adding business data.</p>
    <button on:click={()=>dispatch('login',{tenant:state!.tenant,email:state!.email})}>Go to sign in</button>
  {:else if state?.status==='pending'}
    <h2>Waiting for the business owner</h2><p>Your email is verified. The owner of <strong>{state.tenant}</strong> must approve your staff-access request. You have no access to their data yet.</p><button disabled={busy} on:click={refresh}>Refresh request status</button>
  {:else if state?.status==='rejected'}
    <p>The business owner declined this request. Contact them if you think this is a mistake.</p>
  {:else if state?.status==='creating'}
    <p>Your workspace is being created. Refresh shortly, or contact the operator if this continues.</p><button disabled={busy} on:click={refresh}>Refresh status</button>
  {:else if !enabled && state?.status!=='verification'}
    <p>Account creation is not available yet. The platform operator must configure a verified sender email first. Existing accounts can still sign in.</p>
  {:else}
    <form aria-busy={busy} on:submit|preventDefault={submit}>
      {#if state?.status==='verification'}
        <p>Enter the verification code for <strong>{state.email}</strong>{sender ? ` from ${sender}` : ''}. It expires after 10 minutes. If it has not arrived, check spam or start again after one minute. Verification does not grant access to an existing business.</p>
        <label>Email verification code<input disabled={busy} bind:value={code} inputmode="numeric" pattern={'[0-9]{6}'} maxlength="6" autocomplete="one-time-code" required/></label>
        <button disabled={busy} type="submit">{busy?'Verifying…':'Verify email'}</button>
        <button disabled={busy} type="button" on:click={()=>{state=null;code='';}}>{$t("Start again")}</button>
      {:else}
        {#if state}<p>Your previous request could not be completed or has expired. Start a new request.</p>{/if}
        <label>I want to<select disabled={busy} bind:value={kind}><option value="owner">Create my business workspace</option><option value="join">Request to join an existing business</option></select></label>
        <label>{$t("Email")}<input disabled={busy} type="email" maxlength="254" autocomplete="email" bind:value={email} required/></label>
        {#if sender}<p>Verification codes are sent from <strong>{sender}</strong>.</p>{/if}
        <label>{$t("Password")}<input disabled={busy} type="password" minlength="12" maxlength="256" autocomplete="new-password" bind:value={password} required/><small>At least 12 characters. An authenticator is also required at sign-in.</small></label>
        <label>{kind==='owner'?'New company key':'Company key from your business owner'}<input disabled={busy} bind:value={tenant} maxlength="64" pattern={'[A-Za-z0-9][A-Za-z0-9_\\-]{0,63}'} required/></label>
        {#if kind==='owner'}<label>Business name<input disabled={busy} bind:value={businessName} maxlength="120" required/></label><p>After email verification, sign in and pay the platform subscription and implementation fee. Business data and the agent unlock only after payment is confirmed.</p>
        {:else}<p>Your verified request goes to this business’s owner. Approval grants staff access only, with no billing permissions by default.</p>{/if}
        <button disabled={busy} type="submit">{busy?'Sending…':'Send verification code'}</button>
      {/if}
    </form>
  {/if}
</section>

<style>
  .registration{background:white;border:1px solid var(--v7-line);border-radius:var(--v7-radius, 18px);padding:clamp(24px, 4vw, 36px);max-width:560px;width:100%;box-sizing:border-box;box-shadow:var(--v7-card-shadow, 0 8px 28px #203b3008);}h1{font-size:28px;margin:0 0 20px;letter-spacing:-.035em;}h2{font-size:19px}p{line-height:1.6;color:var(--v7-muted);font-size:14px;}form,label{display:grid;gap:10px}form{gap:18px}input,select,button{font:inherit;padding:12px;border:1px solid var(--v7-control-line);border-radius:10px;max-width:100%;box-sizing:border-box;min-height:44px;}button{cursor:pointer;background:var(--v7-accent);color:white;min-height:44px;font-weight:700;}button:disabled{opacity:.6;cursor:wait}small{font-weight:normal;color:var(--v7-muted);line-height:1.6;}.error{color:#ad2020}:focus-visible{outline:3px solid var(--v7-focus);outline-offset:2px}
</style>
