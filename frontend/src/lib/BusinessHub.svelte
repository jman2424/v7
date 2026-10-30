<script lang="ts">
  import {onMount,onDestroy} from 'svelte';
  export let tenant: string;
  export let csrf: string;
  export let isPlatform = false;
  export let canManage = false;
  export let apiPrefix = '';
  type Channel = 'email'|'phone';
  type Preferences = {enabled:boolean;mode:'review'|'automatic';daily_limit:number;retention_days:number;privacy_confirmed:boolean;language:string};
  type Operation = {id:string;channel:string;state:string;source_address:string;reply:string;provider_id:string;error_code:string;version:number;created:number;payload:{subject?:string;text?:string;recipient?:string}};
  let settings: Record<Channel,Preferences>|null = null;
  let grants: Record<Channel,boolean> = {email:false,phone:false};
  let readiness: Record<Channel,{configured:boolean;recipients:string[]}> = {email:{configured:false,recipients:[]},phone:{configured:false,recipients:[]}};
  let workerEnabled = false;
  let operations:Operation[] = [];
  let drafts:Record<string,string> = {};
  let actionFor = '';
  let actionType = 'callback',actionName = '',actionContact = '',actionDetails = '',actionSlot = '';
  let actionConsent = false;
  let status = '',error = false,loading = true,saving = false,busyId = '';
  let disposed = false;
  let generation = 0;
  const controllers = new Set<AbortController>();
  const channelNames:Record<Channel,string> = {email:'Email handler',phone:'Phone handler'};
  const stateNames:Record<string,string> = {queued:'Queued',processing:'Preparing reply',needs_review:'Needs your review',approved:'Approved for sending',sending:'Sending',completed:'Completed',failed:'Failed',uncertain:'Outcome needs checking',rejected:'Declined / skipped'};
  const errorMessages:Record<string,string> = {operation_changed:'This item changed. Refresh activity before continuing.',
    channel_not_granted:'The platform operator must permit this channel first.',channel_connection_required:'Provider routing and the channel worker must be configured first.',
    channel_disabled:'This channel is disabled. Enable it before approving a reply.',action_unavailable:'This action is disabled in your agent settings. Refresh activity after configuring it.',
    slot_unavailable:'That V7 slot is unavailable. Refresh activity and choose another slot or submit a request without a slot.',
    action_outcome_unknown:'The action outcome needs checking. Refresh activity and check existing requests before doing anything again.',
    action_outcome_needs_reconciliation:'Check existing requests before taking further action. Refresh activity for its status.',
    consent_required:'Confirm the customer’s consent before submitting.',invalid_operation_reply:'Enter a reply of up to 6,000 characters.'};
  function url(path:string) {return `${apiPrefix}/admin/api/${path}?tenant=${encodeURIComponent(tenant)}`;}
  async function call(path:string,options:RequestInit={}) {
    const controller = new AbortController();controllers.add(controller);
    try {
      const response = await fetch(url(path),{...options,credentials:'same-origin',signal:controller.signal,
        headers:{...(options.body?{'Content-Type':'application/json'}:{}),'X-CSRF-Token':csrf,...options.headers}});
      const data = await response.json();
      if (!response.ok) throw new Error(errorMessages[data.error] || 'The business hub could not complete this request. Refresh activity or ask the platform operator.');
      return data;
    } finally {controllers.delete(controller);}
  }
  async function load() {
    const current = ++generation;loading = true;status = '';error = false;
    try {
      const [configuration,activity] = await Promise.all([call('business-channels'),call('business-operations')]);
      if (disposed || current !== generation) return;
      settings = configuration.settings;grants = configuration.grants;readiness = configuration.channels;
      workerEnabled = configuration.worker_enabled;operations = activity.operations;
      drafts = Object.fromEntries(operations.map(row=>[row.id,row.reply]));
    } catch (err) {if (!disposed && current === generation) {error = true;status = err instanceof Error?err.message:'Could not load the business hub.';}}
    finally {if (!disposed && current === generation) loading = false;}
  }
  async function save() {
    if (!settings || saving || !canManage) return;
    const submitted = JSON.stringify(settings);saving = true;status = '';error = false;
    try {
      const result = await call('business-channels',{method:'PUT',body:JSON.stringify({settings:JSON.parse(submitted)})});
      if (disposed) return;
      if (submitted === JSON.stringify(settings)) settings = result.settings;
      status = 'Channel settings saved.';
    } catch (err) {if (!disposed) {error = true;status = err instanceof Error?err.message:'Could not save settings.';}}
    finally {if (!disposed) saving = false;}
  }
  async function saveGrants() {
    if (!isPlatform || saving) return;
    saving = true;status = '';error = false;
    try {await call('business-channel-grants',{method:'PUT',body:JSON.stringify(grants)});if (!disposed) status = 'Platform channel permissions saved.';}
    catch(err) {if (!disposed) {error = true;status = err instanceof Error?err.message:'Could not save permissions.';}}
    finally {if (!disposed) saving = false;}
  }
  async function decide(row:Operation,decision:'approve'|'reject'|'complete') {
    if (!canManage || busyId) return;
    busyId = row.id;status = '';error = false;
    try {
      const result = await call(`business-operations/${row.id}/decision`,{method:'POST',body:JSON.stringify({decision,version:row.version,reply:drafts[row.id]})});
      if (disposed) return;
      operations = operations.map(item=>item.id===row.id?result.operation:item);
      status = decision==='approve'?'Reply approved and queued for sending. Check activity for the provider result.':decision==='complete'?'Marked as handled by your team.':'Item declined.';
    } catch(err) {if (!disposed) {error = true;status = err instanceof Error?err.message:'Could not update this item.';}}
    finally {if (!disposed) busyId = '';}
  }
  function prepareAction(row:Operation) {
    actionFor=row.id;actionType='callback';actionName='';actionContact=row.source_address==='anonymous'?'':row.source_address;
    actionDetails='';actionSlot='';actionConsent=false;
  }
  async function performAction(row:Operation) {
    if (!canManage||busyId||!actionConsent) return;
    busyId=row.id;status='';error=false;
    const action={action:actionType,name:actionName,contact:actionContact,details:actionDetails,consent:actionConsent,
      ...(actionType==='consultation'&&actionSlot?{slot_id:actionSlot}:{})};
    try {
      const result=await call(`business-operations/${row.id}/action`,{method:'POST',body:JSON.stringify({version:row.version,action})});
      if(disposed)return;
      operations=operations.map(item=>item.id===row.id?result.operation:item);actionFor='';
      status=result.outcome.status==='confirmed'?`Appointment confirmed. Reference: ${result.outcome.reference}`:`Request saved for your team. Reference: ${result.outcome.reference}`;
    } catch(err) {if(!disposed){error=true;status=err instanceof Error?err.message:'Could not record the action. Refresh activity before retrying.';}}
    finally {if(!disposed)busyId='';}
  }
  onMount(load);
  onDestroy(()=>{disposed = true;generation++;for(const controller of controllers) controller.abort();});
</script>

<section class="hub" aria-labelledby="business-hub-title">
  <div class="heading"><div><p class="eyebrow">Business operations</p><h2 id="business-hub-title">Email, calls and follow-ups</h2><p>Use the same saved business knowledge across your website, email and phone. Review important requests and confirmed outcomes here.</p></div><button type="button" on:click={load} disabled={loading||saving||Boolean(busyId)}>Refresh activity and drafts</button></div>
  {#if status}<p role="status" class:error>{status}</p>{/if}
  {#if loading}<p role="status">Loading your business hub…</p>{/if}
  {#if settings}
    <div class="notice"><strong>Provider connections and costs</strong><p>Email needs a verified sender, incoming mail routing and a signed webhook. Phone needs a connected business number and signed call routing. AI replies use this business’s prepaid AI credit. Email delivery, number rental, calls and provider speech services have separate provider charges. No number or subscription is purchased here.</p><p>{workerEnabled?'The channel worker is enabled.':'The platform operator must enable the channel worker before live handling can start.'}</p></div>
    {#if isPlatform}<fieldset><legend>Platform permissions for {tenant}</legend><p>These permissions make a channel available to this business. The business must still configure and enable it.</p>{#each ['email','phone'] as key}<label class="check"><input type="checkbox" bind:checked={grants[key as Channel]} disabled={saving}/>{channelNames[key as Channel]} allowed</label>{/each}<button type="button" on:click={saveGrants} disabled={saving}>Save platform permissions</button></fieldset>{/if}
    <form on:submit|preventDefault={save}>
      <div class="channels">{#each ['email','phone'] as key}{@const channel=key as Channel}
        <fieldset><legend>{channelNames[channel]}</legend>
          <p class="connection">{readiness[channel].configured?'Provider routing configured':'Awaiting provider connection'} · {grants[channel]?'Permitted by platform':'Not yet permitted by platform'}</p>
          {#each readiness[channel].recipients as recipient}<p><code>{recipient}</code></p>{/each}
          <label class="check"><input type="checkbox" bind:checked={settings[channel].enabled} disabled={!canManage||!grants[channel]||!readiness[channel].configured||!workerEnabled}/>Enable this channel</label>
          <label>Handling mode<select bind:value={settings[channel].mode} disabled={!canManage}><option value="review">Review first</option><option value="automatic">Answer routine questions automatically</option></select></label>
          <p class="hint">{channel==='email'?'Review mode prepares drafts for your approval. Automatic mode can reply to routine questions; unauthenticated senders, attachments and important requests stay in review.':'Review mode takes a message. Automatic mode answers routine questions during the call; important requests are saved for the team. No audio recording is created by V7.'}</p>
          <label>Daily inbound {channel==='phone'?'call turns':'messages'}<input type="number" min="1" max="1000" bind:value={settings[channel].daily_limit} disabled={!canManage} required/></label>
          <label>Keep hub message content for (days)<input type="number" min="1" max="90" bind:value={settings[channel].retention_days} disabled={!canManage} required/></label><p class="hint">Content is removed by the channel worker after this period. Hashed delivery identifiers stay for up to 90 days to prevent duplicate replies. Conversation history, action records and provider retention are managed separately.</p>
          {#if channel==='phone'}<label>Call language<select bind:value={settings.phone.language} disabled={!canManage}><option value="en-GB">English (UK)</option><option value="en-US">English (US)</option><option value="fr-FR">French</option><option value="es-ES">Spanish</option><option value="de-DE">German</option></select></label>{/if}
          <label class="check"><input type="checkbox" bind:checked={settings[channel].privacy_confirmed} disabled={!canManage}/>Our privacy notice covers this channel and its saved messages.</label>
        </fieldset>
      {/each}</div>
      <button type="submit" disabled={!canManage||saving}>{saving?'Saving…':'Save channel settings'}</button>
    </form>
  {/if}
  <section class="activity" aria-labelledby="hub-activity"><h3 id="hub-activity">Activity and approvals</h3><p>Refresh reloads drafts. “Completed” records a prepared call response, a provider-accepted email, or an item your team marked as handled; it does not establish inbox delivery or a completed external booking.</p>
    {#if !operations.length&&!loading}<p>No channel activity yet. Connect and enable a channel to start receiving enquiries.</p>{/if}
    {#each operations as row (row.id)}
      <article><div class="row"><strong>{row.channel==='email'?'Email':row.channel==='phone'?'Phone':'Workflow'} · {stateNames[row.state]||row.state}</strong><time datetime={new Date(row.created*1000).toISOString()}>{new Date(row.created*1000).toLocaleString()}</time></div>
        <p>{row.source_address}</p>{#if row.payload.subject}<h4>{row.payload.subject}</h4>{/if}
        {#if row.payload.text}<pre>{row.payload.text}</pre>{/if}
        {#if row.error_code}<p class="hint">{row.error_code.replaceAll('_',' ')}</p>{/if}
        {#if row.state==='needs_review'&&row.channel==='email'}<label for={'draft-'+row.id}>Reply to {row.source_address}<textarea id={'draft-'+row.id} bind:value={drafts[row.id]} maxlength="6000" rows="6" disabled={!canManage||Boolean(busyId)}></textarea></label><p class="hint">Approving sends this reply only to the original sender, from the business address that received the enquiry.</p>{:else if row.reply}<pre>{row.reply}</pre>{/if}
        {#if row.provider_id}<p class="hint">Result reference: <code>{row.provider_id}</code></p>{/if}
        {#if row.state==='uncertain'}<p>Check the provider before taking further action. V7 will not automatically repeat this send.</p>{/if}
        {#if row.state==='needs_review'&&canManage}<div class="buttons">{#if row.channel==='email'}<button type="button" disabled={Boolean(busyId)||!drafts[row.id]?.trim()} on:click={()=>decide(row,'approve')}>Approve and send reply</button>{/if}<button type="button" disabled={Boolean(busyId)} on:click={()=>prepareAction(row)}>Prepare business action</button><button type="button" disabled={Boolean(busyId)} on:click={()=>decide(row,'complete')}>Mark handled by our team</button><button type="button" disabled={Boolean(busyId)} on:click={()=>decide(row,'reject')}>Decline</button></div>{/if}
        {#if row.state==='needs_review'&&actionFor===row.id&&canManage}
          <form on:submit|preventDefault={()=>performAction(row)}>
            <h4>Review and confirm a business action</h4>
            <p>This uses your existing enabled V7 action tools. A callback or quote records a request. A consultation is confirmed only when an available V7 slot is supplied. External website bookings need their own integration. This does not send an email or call the customer.</p>
            <label>Action<select bind:value={actionType}><option value="callback">Callback request</option><option value="quote">Quote request</option><option value="consultation">Consultation request / V7 appointment</option></select></label>
            <label>Customer name<input bind:value={actionName} maxlength="120" required/></label>
            <label>Contact details<input bind:value={actionContact} maxlength="254" required/></label>
            <label>Request details<textarea bind:value={actionDetails} maxlength="2000" rows="3"></textarea></label>
            {#if actionType==='consultation'}<label>Existing V7 slot ID (optional)<input bind:value={actionSlot} maxlength="64"/></label><p class="hint">Leave blank to request a consultation without confirming an appointment. Only your configured, available V7 slots can be booked.</p>{/if}
            <label class="check"><input type="checkbox" bind:checked={actionConsent} required/>I checked the enquiry: the customer requested this action and agreed to use these contact details.</label>
            <div class="buttons"><button type="submit" disabled={Boolean(busyId)||!actionConsent}>Confirm and run action</button><button type="button" disabled={Boolean(busyId)} on:click={()=>actionFor=''}>Cancel action</button></div>
          </form>
        {/if}
      </article>
    {/each}
  </section>
</section>

<style>
  .hub{display:grid;gap:1.25rem}.heading,.row{display:flex;justify-content:space-between;gap:1rem;align-items:start}.heading p{max-width:65ch}.eyebrow{font-size:.75rem;text-transform:uppercase;font-weight:700;color:#476358}h2,h3,h4,p{margin:.35rem 0 .75rem}.channels{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,290px),1fr));gap:1rem}fieldset,article,.notice{padding:1.2rem;border:1px solid #d6dfda;border-radius:12px;background:white}legend{font-weight:700;padding:0 .4rem}label{display:grid;gap:.35rem;margin:.8rem 0}.check{display:flex;gap:.6rem;align-items:flex-start}.check input{width:auto;margin-top:.2rem}input,select,textarea,button{font:inherit}input,select,textarea{max-width:100%;padding:.65rem;border:1px solid #bdc9c2;border-radius:7px;background:white}textarea{width:100%;box-sizing:border-box}button{padding:.65rem .9rem;border:1px solid #b9cbc1;border-radius:8px;color:#14503b;background:#f3f7f4;cursor:pointer;min-height:44px}button:disabled{opacity:.55;cursor:not-allowed}.hint,.connection,time{font-size:.85rem;color:#53645c}article{margin:1rem 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;line-height:1.5}code{overflow-wrap:anywhere}.buttons{display:flex;flex-wrap:wrap;gap:.5rem}.error{color:#9b1c1c}.notice{background:#f0f7f3}@media(max-width:640px){.heading,.row{display:block}.heading button{width:100%}}
</style>
