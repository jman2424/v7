<script lang="ts">
  import {onMount,onDestroy} from 'svelte';
  import {base} from './consoleBase';
  export let tenant:string;
  export let csrf:string;
  export let apiPrefix='';
  export let canEdit=true;
  type Application={status:string;revision:number;business_name:string;website:string;description:string;plan_id:string;public_message:string;existing_service_preserved:boolean};
  let application:Application|null=null;
  let policy:{intake_enabled:boolean;guidance:string;policy_version:string;plans:{id:string;name:string;monthly_pence:number;setup_pence:number}[]}={intake_enabled:false,guidance:'',policy_version:'',plans:[]};
  let businessName='', website='', description='', planId='starter', acceptedTerms=false;
  let busy=false, loaded=false, editing=false, error='', notice='';
  let alive=true;
  const requests=new Set<AbortController>();
  const labels:Record<string,string>={PENDING_REVIEW:'Application under review',NEEDS_INFORMATION:'More information needed',APPROVED:'Business approved',REJECTED:'Application decision',EXPIRED:'Application expired',CANCELLED:'Application withdrawn'};
  async function api(path:string, method='GET', body?:unknown){
    const controller=new AbortController();requests.add(controller);
    const timer=setTimeout(()=>controller.abort(),20000);
    try{
      const response=await fetch(apiPrefix+'/business-applications/'+path+'?tenant='+encodeURIComponent(tenant),{method,credentials:'same-origin',signal:controller.signal,headers:{'X-CSRF-Token':csrf,...(body===undefined?{}:{'Content-Type':'application/json'})},...(body===undefined?{}:{body:JSON.stringify(body)})});
      const result=await response.json();if(!response.ok)throw new Error(result.error||'application_request_failed');return result;
    }finally{clearTimeout(timer);requests.delete(controller);}
  }
  function fill(){if(application){businessName=application.business_name;website=application.website;description=application.description;planId=application.plan_id;}}
  async function load(){
    if(busy)return;busy=true;error='';
    try{const result=await api('current');if(!alive)return;application=result.application;policy=result.policy;loaded=true;fill();if(!application&&result.prefill){businessName=result.prefill.business_name;website=result.prefill.website;const selected=new URLSearchParams(window.location.search).get('plan');if(selected&&policy.plans.some(plan=>plan.id===selected))planId=selected;}}
    catch{if(alive)error='Your application could not be loaded. Please retry.';}finally{if(alive)busy=false;}
  }
  async function submit(){
    if(busy)return;busy=true;error='';notice='';
    try{
      const result=await api('current',application?'PUT':'POST',{business_name:businessName,website,description,plan_id:planId,accepted_terms:acceptedTerms,policy_version:policy.policy_version,revision:application?.revision});
      if(!alive)return;application=result.application;editing=false;acceptedTerms=false;notice='Application submitted for manual review. No payment has been taken.';
    }catch(failure){if(alive)error=failure instanceof Error?failure.message:'Application could not be saved.';}finally{if(alive)busy=false;}
  }
  async function closePayments(){
    if(busy)return;busy=true;error='';
    try{await api('close-payments','POST',{});if(alive)notice='Unpaid checkout sessions closed. You can now correct or withdraw the application.';}
    catch(failure){if(alive)error=failure instanceof Error?failure.message:'Checkout status could not be checked.';}finally{if(alive)busy=false;}
  }
  async function withdraw(){
    if(!application||busy||!confirm('Withdraw this application? Existing subscriptions are not cancelled by this action.'))return;
    busy=true;error='';try{const result=await api('cancel','POST',{revision:application.revision});if(alive)application=result.application;}
    catch(failure){if(alive)error=failure instanceof Error?failure.message:'Application could not be withdrawn.';}finally{if(alive)busy=false;}
  }
  onMount(load);
  onDestroy(()=>{alive=false;for(const request of requests)request.abort();});
</script>

<section class="application surface">
  <h2>{application?labels[application.status]:'Apply to Vertex Seven'}</h2>
  {#if error}<p role="alert" class="error">{error.replaceAll('_',' ')}</p>{/if}
  {#if notice}<p role="status">{notice}</p>{/if}
  {#if !loaded}<p>Loading application…</p><button disabled={busy} on:click={load}>Retry</button>
  {:else}
    {#if application}
      <p><strong>{application.business_name}</strong> · {application.plan_id}</p>
      {#if application.status==='PENDING_REVIEW'}<p>We've received your application and are reviewing your business details. We'll email you when there is an update. No payment is needed while it is under review.</p>{/if}
      {#if application.public_message}<p class="message">{application.public_message}</p>{/if}
      {#if application.existing_service_preserved}<p>Existing services and prepaid balances remain subject to their current billing and permissions. This review does not automatically cancel your subscription.</p>{/if}
      {#if application.status==='APPROVED'}<a class="primary" href={base+'/subscription?'+new URLSearchParams({tenant,plan:application.plan_id})}>Continue to secure checkout</a><p>Monthly subscription and setup fees are separate from prepaid AI usage credit. Activation follows verified payment.</p>{/if}
      <div class="actions"><button disabled={busy} on:click={load}>Refresh status</button>{#if canEdit}<button disabled={busy} on:click={()=>{editing=!editing;fill();}}>Correct details / request reconsideration</button>{#if application.status!=='CANCELLED'}<button disabled={busy} on:click={withdraw}>Withdraw application</button>{/if}{/if}</div>
    {/if}
    {#if canEdit&&(!application||editing)}
      <form on:submit|preventDefault={submit}>
        <p>{policy.guidance}</p>
        {#if application}<p>Changing the business name, website, activities or selected application plan returns it to manual review before further purchases. Resolve open checkouts first.</p>{:else if !policy.intake_enabled}<p>New business applications are currently closed.</p>{/if}
        <fieldset disabled={busy||(!application&&!policy.intake_enabled)}>
          <label>Business name<input bind:value={businessName} maxlength="120" required/></label>
          <label>Business website (optional)<input type="url" placeholder="https://example.com" bind:value={website} maxlength="2048"/></label>
          <label>Business description {website?'(optional)':''}<textarea bind:value={description} maxlength="2000" rows="3" required={!website}></textarea></label>
          <label>Selected plan<select bind:value={planId}>{#each policy.plans as plan}<option value={plan.id}>{plan.name} · £{plan.monthly_pence/100}/month + £{plan.setup_pence/100} setup</option>{/each}</select></label>
          <label class="check"><input type="checkbox" bind:checked={acceptedTerms} required/><span>I agree to the <a href="/acceptable-use" target="_blank" rel="noopener noreferrer">Acceptable Use Policy</a> and <a href="/terms" target="_blank" rel="noopener noreferrer">terms</a>.</span></label>
          <button type="submit" class="primary">{busy?'Saving…':application?'Submit for another review':'Submit application'}</button>
        </fieldset>
      </form>
    {/if}
    {#if canEdit&&application}<details><summary>Open checkout preventing a correction?</summary><p>This checks and expires unpaid Stripe checkouts. Completed or uncertain payments must be reconciled before editing. It does not cancel an existing subscription.</p><button disabled={busy} on:click={closePayments}>Resolve unpaid checkouts</button></details>{/if}
  {/if}
</section>

<style>
  .application{padding:clamp(18px,3vw,30px);max-width:850px}h2{margin-top:0}p{line-height:1.6;color:var(--v7-muted)}.message{white-space:pre-line}.actions{display:flex;flex-wrap:wrap;gap:10px;margin:20px 0}form,fieldset,label{display:grid;gap:10px}form{margin-top:25px}fieldset{border:0;padding:0;gap:18px}input,textarea,select,button,.primary{font:inherit;box-sizing:border-box;max-width:100%;border:1px solid var(--v7-control-line,#bdcbc6);border-radius:9px;padding:12px;min-height:44px}button{cursor:pointer;background:white;color:#164536}.primary{display:inline-block;background:#164536;color:white;text-decoration:none;width:fit-content}.check{display:flex;align-items:flex-start}.check input{min-height:20px}details{margin-top:25px}summary{cursor:pointer}.error{color:#a52222}button:disabled,fieldset:disabled{opacity:.6}:focus-visible{outline:3px solid #79b398;outline-offset:2px}
</style>
