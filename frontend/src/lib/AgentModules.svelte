<script lang="ts">
  import {onMount,onDestroy} from 'svelte';
  export let tenant:string;
  export let csrf:string;
  export let isPlatform=false;
  export let canManage=false;
  export let apiPrefix='';
  export let onReady:(value:boolean)=>void=()=>{};
  export let onSaved:()=>void=()=>{};
  type Module={id:string;label:string;granted:boolean;enabled:boolean;available:boolean;blocked_by:string;approval:string};
  let modules:Module[]=[],grants:Record<string,boolean>={},enabled:Record<string,boolean>={};
  let revision='',initialized=false,loading=true,busy=false,disposed=false,message='',error=false;
  const controllers=new Set<AbortController>();
  const reasons:Record<string,string>={platform_disabled:'Paused by platform-wide policy.',plan_not_allowed:'Unavailable under the operator’s plan policy.',
    business_inactive:'The business account needs activation before operations can run.',
    not_granted:'The platform operator has not permitted this module.',owner_disabled:'Disabled for your business.',
    module_policy_unavailable:'Policy needs an operator check. Execution is blocked.',service_setup_required:'Complete its existing service and provider setup before use.'};
  const failures:Record<string,string>={module_not_granted:'You can enable only modules permitted by the platform.',
    module_policy_not_initialized:'The platform operator must initialize module controls first.',
    invalid_module_settings:'Check the module settings and reload before saving.'};
  async function request(method='GET',field?:'grants'|'enabled') {
    const controller=new AbortController();controllers.add(controller);
    try {
      const response=await fetch(`${apiPrefix}/admin/api/agent-modules${field==='grants'?'/grants':''}?tenant=${encodeURIComponent(tenant)}`,{
        method,credentials:'same-origin',signal:controller.signal,
        headers:{'X-CSRF-Token':csrf,...(method==='PUT'?{'Content-Type':'application/json'}:{})},
        ...(field?{body:JSON.stringify({revision,[field]:{...(field==='grants'?grants:enabled)}})}:{})});
      const data=await response.json();
      if(!response.ok)throw new Error(failures[data.error]||'Module controls could not be loaded or saved. Refresh to check permissions and the latest settings.');
      return data;
    } finally {controllers.delete(controller);}
  }
  function apply(data:any) {
    modules=data.modules;revision=data.revision;initialized=data.initialized;
    grants=Object.fromEntries(modules.map(row=>[row.id,row.granted]));
    enabled=Object.fromEntries(modules.map(row=>[row.id,row.enabled&&row.granted]));
    onReady(initialized);
  }
  async function load() {
    if(busy||disposed)return;
    busy=true;message='';error=false;
    try {const data=await request();if(!disposed)apply(data);}
    catch(err){if(!disposed){error=true;message=err instanceof Error?err.message:'Module controls are unavailable.';}}
    finally{if(!disposed){busy=false;loading=false;}}
  }
  async function save(field:'grants'|'enabled') {
    if(busy||disposed||(field==='grants'?!isPlatform:!canManage))return;
    busy=true;message='';error=false;
    try {const data=await request('PUT',field);if(!disposed){apply(data);onSaved();message='Module controls saved. Services recheck these permissions before executing.';}}
    catch(err){if(!disposed){error=true;message=err instanceof Error?err.message:'Could not save module controls.';}}
    finally{if(!disposed)busy=false;}
  }
  onMount(load);
  onDestroy(()=>{disposed=true;for(const controller of controllers)controller.abort();});
</script>

<section class="modules" aria-labelledby="agent-module-title">
  <div class="heading"><h3 id="agent-module-title">What your agent is allowed to do</h3><button type="button" on:click={load} disabled={busy}>Refresh module controls</button></div>
  <p>Business knowledge, conversation quality and core security remain available on every plan. These switches control optional operations. AI credit and existing service permissions still apply.</p>
  {#if loading}<p role="status">Loading module controls…</p>{:else if modules.length}
    {#if !initialized}<p class="notice">Existing configured services are continuing under their current permissions. A platform operator must initialize these controls before you can use the new switches. Initialization preserves the existing enabled-service choices.</p>{/if}
    <form on:submit|preventDefault={()=>save('enabled')}>
      <div class="grid">{#each modules as row}<fieldset>
        <legend>{row.label}</legend>
        <label><input type="checkbox" bind:checked={enabled[row.id]} disabled={!initialized||!canManage||!row.granted||busy}/>Enable for this business</label>
        <p class="state">{row.available?'Available with existing verification and confirmation checks':reasons[row.blocked_by]||'Check configuration before use.'}</p>
        <p class="hint">{row.id==='booking_management'?'Changes need the customer’s private appointment receipt and confirmation. External calendars are separate.':
          ['consultation','quote','callback'].includes(row.id)?'Uses the existing customer-confirmed request form. A quote request is not a final quote; only a reserved V7 slot is a confirmed booking.':
          'Uses the channel’s existing review/automatic mode, verified provider connection and configured privacy settings.'}</p>
        <a href={row.id==='email'||row.id==='phone'?`/console/operations?tenant=${encodeURIComponent(tenant)}#channel-settings`:`/console/agent?tenant=${encodeURIComponent(tenant)}`}>Open service settings</a>
      </fieldset>{/each}</div>
      <button type="submit" disabled={!initialized||!canManage||busy}>Save business module switches</button>
    </form>
    {#if isPlatform}<form class="platform" on:submit|preventDefault={()=>save('grants')}>
      <h4>Platform permissions for this company</h4><p>Only platform operators can grant modules. New permissions do not configure a provider or automatically enable a previously disabled service.</p>
      {#each modules as row}<label><input type="checkbox" bind:checked={grants[row.id]} disabled={busy}/>{row.label} permitted</label>{/each}
      <button type="submit" disabled={busy}>{initialized?'Save module grants':'Initialize module controls'}</button>
    </form>{/if}
    <p class="hint">Platform-wide kill switches and plan restrictions use operator deployment configuration in this phase. A module switch stops future execution; it does not undo completed actions or remove existing customer records.</p>
  {/if}
  {#if message}<p role="status" class:error>{message}</p>{/if}
</section>

<style>
  .modules{background:#fff;border:1px solid #d6dfda;border-radius:12px;padding:1.25rem}.heading{display:flex;gap:1rem;align-items:center;justify-content:space-between;flex-wrap:wrap}h3,h4{margin:.3rem 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,270px),1fr));gap:1rem;margin:1rem 0}fieldset{min-width:0;border:1px solid #d6dfda;border-radius:8px;padding:1rem}legend{font-weight:650}p{line-height:1.5}label{display:flex;align-items:center;gap:.65rem;margin:.75rem 0}input{flex-shrink:0;width:18px;height:18px}button{padding:.7rem 1rem;min-height:44px;font:inherit;background:#f3f7f4;color:#14503b;border:1px solid #bdc9c2;border-radius:7px;cursor:pointer}button:disabled{opacity:.6;cursor:not-allowed}.hint{font-size:.9rem;color:#4d5f55}.notice,.platform{padding:1rem;background:#f3f7f4;border-radius:8px}.platform{margin-top:1rem}.state{font-weight:550}.error{color:#9b1c1c}a{color:#14503b}
</style>
