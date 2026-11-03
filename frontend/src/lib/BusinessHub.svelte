<script lang="ts">
  import {onMount,onDestroy} from 'svelte';
  import BusinessEmailSetup from './BusinessEmailSetup.svelte';
  import AgentModules from './AgentModules.svelte';
  import DraftGuard from './DraftGuard.svelte';
  import ConfirmDialog from './ConfirmDialog.svelte';
  export let tenant: string;
  export let csrf: string;
  export let isPlatform = false;
  export let canManage = false;
  export let apiPrefix = '';
  type Channel = 'email'|'phone';
  export let channel:Channel|''='';
  export let presentation:'all'|'activity'='all';
  export let showRules=true;
  $: visibleChannels=channel?[channel]:['email','phone'] as Channel[];
  let activitySearch='',activityState='';
  $: channelOperations=operations.filter(row=>!channel||row.channel===channel);
  $: visibleOperations=filterOperations(channelOperations,activitySearch,activityState);
  $: reviewCount=channelOperations.filter(row=>row.state==='needs_review').length;
  type Preferences = {enabled:boolean;mode:'review'|'automatic';daily_limit:number;retention_days:number;privacy_confirmed:boolean;language:string;provider_cleanup?:'keep'|'trash_handled';cleanup_confirmed?:boolean};
  type Operation = {id:string;channel:string;state:string;source_address:string;reply:string;provider_id:string;error_code:string;version:number;created:number;payload:{subject?:string;text?:string;recipient?:string}};
  let savedSettings='',savedDrafts='';
  let confirmation:ConfirmDialog;
  $: dirty=Boolean(savedSettings&&savedSettings!==JSON.stringify(settings))||Boolean(savedDrafts&&savedDrafts!==JSON.stringify(drafts))||Boolean(actionFor);
  let settings: Record<Channel,Preferences>|null = null;
  let grants: Record<Channel,boolean> = {email:false,phone:false};
  let readiness: Record<Channel,{configured:boolean;recipients:string[];checks?:Record<string,boolean>;provider_cleanup_available?:boolean}> = {email:{configured:false,recipients:[]},phone:{configured:false,recipients:[]}};
  let emailNotice='';
  const checkNames:Record<string,string>={permission:'Channel permission and module switch',routing:'Provider routing',worker:'Processing worker',business_active:'Business active',privacy:'Privacy information confirmed'};
  const operationReasons:Record<string,string>={reply_review_required:'Review this draft and check its business details before approving it.',call_reply_timed_out:'The live call ended before a verified reply was ready. Follow up with the caller.',channel_processing_failed:'The enquiry could not be processed safely. Check the connection and prepare a reply manually.',call_transcript_unclear:'The caller was difficult to understand twice. Check the transcript with them before acting.',call_message_received:'A caller left a message for your team. No automatic action was taken.',channel_disabled:'Handling was disabled. Review this enquiry manually.',channel_route_changed:'The provider route changed. Ask the operator to check it before sending.',channel_sender_changed:'The verified sender changed. Check the email connection.',channel_invalid_answer:'The reply did not pass validation. Prepare a checked reply manually.',channel_unapproved_link:'An unapproved link was blocked. Use only your verified business links.',send_window_expired:'The safe sending window expired. Check the provider before replying manually.'};
  let workerEnabled = false;
  let moduleInitialized = false;
  let phoneWebhook = '';
  let operations:Operation[] = [];
  let drafts:Record<string,string> = {};
  let actionFor = '';
  let actionType = 'callback',actionName = '',actionContact = '',actionDetails = '',actionSlot = '';
  let actionConsent = false;
  let status = '',error = false,loading = true,saving = false,busyId = '';
  let disposed = false;
  let generation = 0;
  const controllers = new Set<AbortController>();
  const channelNames:Record<Channel,string> = {email:'Email assistant',phone:'Phone assistant'};
  const stateNames:Record<string,string> = {queued:'Queued',processing:'Preparing reply',needs_review:'Needs your review',approved:'Approved for sending',sending:'Sending',completed:'Completed',failed:'Failed',uncertain:'Outcome needs checking',rejected:'Declined / skipped'};
  const errorMessages:Record<string,string> = {operation_changed:'This item changed. Refresh activity before continuing.',
    channel_storage_unavailable:'Channel storage is not available yet. Email setup can be prepared; live processing is awaiting platform provisioning.',
    email_cleanup_not_supported:'Connected-inbox cleanup needs an explicitly configured Resend Inbox. Other mailbox copies use your provider’s own retention settings.',
    email_setup_verification_required:'The requested mailbox must be verified and routed before email handling can be enabled.',
    channel_not_granted:'The platform operator must permit this channel first.',channel_connection_required:'Provider routing and the channel worker must be configured first.',
    channel_disabled:'This channel is disabled. Enable it before approving a reply.',action_unavailable:'This action is disabled in your agent settings. Refresh activity after configuring it.',
    slot_unavailable:'That V7 slot is unavailable. Refresh activity and choose another slot or submit a request without a slot.',
    action_outcome_unknown:'The action outcome needs checking. Refresh activity and check existing requests before doing anything again.',
    action_outcome_needs_reconciliation:'Check existing requests before taking further action. Refresh activity for its status.',
    consent_required:'Confirm the customer’s consent before submitting.',invalid_operation_reply:'Enter a reply of up to 6,000 characters.'};
  function url(path:string) {return `${apiPrefix}/admin/api/${path}?tenant=${encodeURIComponent(tenant)}`;}
  function filterOperations(rows:Operation[],search:string,state:string) {
    const query=search.trim().toLocaleLowerCase();
    return rows.filter(row=>(!state||row.state===state)&&(!query||[row.source_address,row.payload.subject||'',row.payload.text||''].some(value=>value.toLocaleLowerCase().includes(query))));
  }
  function emailPreview(reply:string) {
    const footer='\n\n---\n'+emailNotice;
    return reply.endsWith(footer)?reply:reply+footer;
  }
  function emailSubject(subject:string) {
    subject=subject||'Your enquiry';
    return subject.toLowerCase().startsWith('re:')?subject:'Re: '+subject;
  }
  async function copyWebhook() {
    try {await navigator.clipboard.writeText(phoneWebhook);status='Incoming call webhook copied.';error=false;}
    catch {status='Copy is unavailable. Select and copy the webhook URL above.';error=true;}
  }
  async function call(path:string,options:RequestInit={}) {
    const controller = new AbortController();controllers.add(controller);
    const timeout=setTimeout(()=>controller.abort(),20000);
    try {
      const response = await fetch(url(path),{...options,credentials:'same-origin',signal:controller.signal,
        headers:{...(options.body?{'Content-Type':'application/json'}:{}),'X-CSRF-Token':csrf,...options.headers}});
      const data = await response.json();
      if (!response.ok) throw new Error(errorMessages[data.error] || 'The business hub could not complete this request. Refresh activity or ask the platform operator.');
      return data;
    } catch(err) {
      if(controller.signal.aborted)throw new Error('The request timed out. Refresh activity to check its outcome before retrying; a submitted change may already have completed.');
      throw err;
    } finally {clearTimeout(timeout);controllers.delete(controller);}
  }
  async function load() {
    if(dirty&&!await confirmation.ask())return;
    const current = ++generation;loading = true;status = '';error = false;
    try {
      const [configurationResult,activityResult] = await Promise.allSettled([call('business-channels'),call('business-operations')]);
      if (disposed || current !== generation) return;
      if(configurationResult.status==='rejected')throw configurationResult.reason;
      const configuration=configurationResult.value;
      settings = configuration.settings;grants = configuration.grants;readiness = configuration.channels;
      workerEnabled = configuration.worker_enabled;
      emailNotice=configuration.email_notice||'';
      if(activityResult.status==='fulfilled')operations=activityResult.value.operations;
      else {operations=[];error=true;status=activityResult.reason instanceof Error?activityResult.reason.message:'Activity is unavailable.';}
      drafts = Object.fromEntries(operations.map(row=>[row.id,row.reply]));
      savedSettings=JSON.stringify(settings);savedDrafts=JSON.stringify(drafts);
    } catch (err) {if (!disposed && current === generation) {error = true;status = err instanceof Error?err.message:'Could not load the business hub.';}}
    finally {if (!disposed && current === generation) loading = false;}
  }
  async function save() {
    if (!settings || saving || !canManage) return;
    const submitted = JSON.stringify(settings);saving = true;status = '';error = false;
    try {
      const result = await call('business-channels',{method:'PUT',body:JSON.stringify({settings:JSON.parse(submitted)})});
      if (disposed) return;
      savedSettings=submitted;
      if (submitted === JSON.stringify(settings)){settings = result.settings;savedSettings=JSON.stringify(settings);}
      readiness=result.channels;workerEnabled=result.worker_enabled;
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
      const latestReply=result.operation.reply??drafts[row.id]??'';
      drafts={...drafts,[row.id]:latestReply};savedDrafts=JSON.stringify({...JSON.parse(savedDrafts||'{}'),[row.id]:latestReply});
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
  onMount(()=>{phoneWebhook = new URL(`${apiPrefix}/channels/phone/incoming`,window.location.origin).href;load();});
  onDestroy(()=>{disposed = true;generation++;for(const controller of controllers) controller.abort();});
</script>

<DraftGuard {dirty}/><ConfirmDialog bind:this={confirmation}/>
<section class="hub" aria-labelledby="business-hub-title">
  <div class="heading"><div><p class="eyebrow">Business operations</p><h2 id="business-hub-title">{presentation==='activity'?'Review and follow up':channel==='email'?'Your email assistant':channel==='phone'?'Your phone assistant':'Email, calls and follow-ups'}</h2><p>Use the same saved business knowledge across your website, email and phone. Review important requests and confirmed outcomes here.</p></div><button type="button" on:click={load} disabled={loading||saving||Boolean(busyId)}>Refresh activity and drafts</button></div>
  {#if status}<p role="status" class:error>{status}</p>{/if}
  {#if loading}<p role="status">Loading your business hub…</p>{/if}
  {#if settings && presentation!=='activity'}
    {#if channel}<nav class="channel-workflow" aria-label={channel+' setup steps'}><a href="#channel-connect"><span>1</span>Connect</a><a href="#channel-settings"><span>2</span>Configure</a><a href="#channel-test"><span>3</span>Test</a><a href="#channel-settings"><span>4</span>Activate</a><a href="#hub-activity"><span>5</span>Monitor</a></nav><div class="channel-readiness" id="channel-connect"><strong>{readiness[channel].configured?'Provider routing configured':'Connect your provider first'}</strong><p>{!grants[channel]?'The platform operator must permit this channel before you can enable it.':!workerEnabled?'Configuration can be saved, but the platform worker must be enabled for live handling.':readiness[channel].configured?'Configure handling, test a real enquiry, then enable this channel below.':'Complete the provider connection below before enabling customer handling.'}</p></div>{/if}
    {#if showRules}<AgentModules {tenant} {csrf} {canManage} {isPlatform} {apiPrefix} onReady={(value)=>moduleInitialized=value} onSaved={load}/>{/if}
    {#if !channel||channel==='email'}<BusinessEmailSetup {tenant} {csrf} {canManage} {apiPrefix}/>{/if}
    {#if !channel||channel==='phone'}<section class="notice" aria-labelledby="phone-setup-title"><h3 id="phone-setup-title">Connect your business phone</h3>
      <p>Bring a voice-capable Twilio number you control. Your platform operator securely connects the provider account and assigns the exact number to your company. Start in review mode to take messages; automatic mode answers permitted business questions.</p>
      <label>Incoming call webhook<input readonly value={phoneWebhook}/></label>
      <button type="button" on:click={copyWebhook}>Copy call webhook</button>
      <p>Set the number’s incoming-call webhook to this URL using HTTP POST after the operator confirms the connection. Then choose your call language and enable the channel below. Test a real call before publishing the number.</p>
      <p>Callers hear an AI and synthetic-voice notice before input collection. They can press 0 to leave a message for the team; this requests follow-up and does not transfer to a live person. Number rental, calls and provider speech charges are separate. No number is purchased here.</p>
      <a href="https://www.twilio.com/docs/voice/quickstart" target="_blank" rel="noopener noreferrer">Twilio inbound voice setup ↗</a>
    </section>{/if}
    <div class="notice"><strong>Provider connections and costs</strong><p>Email needs a verified sender, incoming mail routing and a signed webhook. Phone needs a connected business number and signed call routing. AI replies use this business’s prepaid AI credit. Email delivery, number rental, calls and provider speech services have separate provider charges. No number or subscription is purchased here.</p><p>{workerEnabled?'The channel worker is enabled.':'The platform operator must enable the channel worker before live handling can start.'}</p></div>
    {#if isPlatform&&!moduleInitialized}<fieldset><legend>Platform permissions for {tenant}</legend><p>These permissions make a channel available to this business. The business must still configure and enable it.</p>{#each ['email','phone'] as key}<label class="check"><input type="checkbox" bind:checked={grants[key as Channel]} disabled={saving}/>{channelNames[key as Channel]} allowed</label>{/each}<button type="button" on:click={saveGrants} disabled={saving}>Save platform permissions</button></fieldset>{/if}
    {#if channel}<section class="channel-test" id="channel-test"><h3>Test before going live</h3><p>{channel==='email'?'After routing is configured, send a normal enquiry to your connected business inbox from a separate address. In review mode, check the draft in Activity, approve it only when correct, and verify receipt in the sender’s inbox. A provider-accepted result does not establish inbox delivery.':'Call your connected number and check the AI disclosure and language. Review mode should take a message for your team; automatic mode may answer permitted routine questions. Check the recorded activity and the follow-up path before publishing your number.'}</p><p class="hint">This page does not send a test email or place a call. Provider charges may apply to your own test. Enable the channel only when its connection, privacy information and handling rules are ready.</p></section>{/if}
    <form id="channel-settings" on:submit|preventDefault={save}>
      <div class="channels">{#each visibleChannels as key}{@const channel=key as Channel}
        <fieldset><legend>{channelNames[channel]}</legend>
          <p class="connection">{readiness[channel].configured?'Provider routing configured':'Awaiting provider connection'} · {grants[channel]?'Permitted by platform':'Not yet permitted by platform'}</p>
          {#if readiness[channel].checks}<ul class="readiness-checks" aria-label={channel+' configuration checks'}>{#each Object.entries(readiness[channel].checks||{}) as [name,ready]}<li><strong>{ready?'Ready':'Needs attention'}</strong> · {checkNames[name]||name}</li>{/each}</ul><p class="hint">These are configuration checks. Confirm queue availability in Activity and test actual delivery before going live. AI credit and provider charges still apply.</p>{/if}
          {#each readiness[channel].recipients as recipient}<p><code>{recipient}</code></p>{/each}
          <label class="check"><input type="checkbox" bind:checked={settings[channel].enabled} disabled={!canManage||!grants[channel]||!readiness[channel].configured||!workerEnabled}/>Enable this channel</label>
          <label>Handling mode<select bind:value={settings[channel].mode} disabled={!canManage}><option value="review">Review first</option><option value="automatic">Answer routine questions automatically</option></select></label>
          <p class="hint">{channel==='email'?'Review mode prepares drafts for your approval. Automatic mode can reply to routine questions; unauthenticated senders, attachments and important requests stay in review.':'Review mode takes a message. Automatic mode answers routine questions during the call; important requests are saved for the team. No audio recording is created by V7.'}</p>
          {#if channel==='email'}<p class="hint">Every sent assistant reply includes the non-editable notice: “AI-assisted reply. Please check important details with the business team.” This also applies to edited and approved drafts.</p>{/if}
          <label>Daily inbound {channel==='phone'?'call turns':'messages'}<input type="number" min="1" max="1000" bind:value={settings[channel].daily_limit} disabled={!canManage} required/></label>
          <label>Keep {channel==='email'?'V7 email':'hub message'} content for (days)<input type="number" min="1" max="90" bind:value={settings[channel].retention_days} disabled={!canManage} required/></label><p class="hint">{channel==='email'?'The worker removes expired email text, drafts and email conversation memory. New email bodies are not duplicated into CRM history.':'Content is removed by the channel worker after this period.'} Hashed delivery identifiers stay for up to 90 days to prevent duplicate replies. Customer records, action requests, audit records and provider copies have separate retention.</p>
          {#if channel==='email'}
            <label>Cleanup of the connected inbox<select bind:value={settings.email.provider_cleanup} disabled={!canManage}>
              <option value="keep">Keep provider copies; delete V7 content only</option>
              <option value="trash_handled" disabled={!readiness.email.provider_cleanup_available}>Also trash old, handled Resend Inbox conversations</option>
            </select></label>
            <p class="hint">Optional inbox cleanup uses the same retention period. It skips unhandled, recent, unrecognised or incomplete threads. Resend moves eligible conversations (including replies) to Trash and schedules permanent deletion 30 days later. Gmail/Outlook originals and forwarded copies are not deleted by this setting; configure retention with that provider.</p>
            {#if settings.email.provider_cleanup==='trash_handled'}<label class="check"><input type="checkbox" bind:checked={settings.email.cleanup_confirmed} disabled={!canManage} required/>I am authorised to apply this retention policy to handled conversations in the connected inbox.</label>{/if}
          {/if}
          {#if channel==='phone'}<label>Call language<select bind:value={settings.phone.language} disabled={!canManage}><option value="en-GB">English (UK)</option><option value="en-US">English (US)</option><option value="fr-FR">French</option><option value="es-ES">Spanish</option><option value="de-DE">German</option></select></label>{/if}
          <label class="check"><input type="checkbox" bind:checked={settings[channel].privacy_confirmed} disabled={!canManage}/>Our privacy notice covers this channel and its saved messages.</label>
        </fieldset>
      {/each}</div>
      <button type="submit" disabled={!canManage||saving}>{saving?'Saving…':'Save channel settings'}</button>
    </form>
  {/if}
  <section class="activity" aria-labelledby="hub-activity"><h3 id="hub-activity">Activity and approvals</h3><p>Refresh reloads drafts. “Completed” records a prepared call response, a provider-accepted email, or an item your team marked as handled; it does not establish inbox delivery or a completed external booking.</p>
    <p class="hint">{reviewCount} awaiting review · Search covers the latest {channelOperations.length} loaded items.</p>
    <div class="activity-filters"><label>Search enquiries<input type="search" bind:value={activitySearch} placeholder="Sender, subject or enquiry"/></label><label>Activity status<select bind:value={activityState}><option value="">All statuses</option>{#each Object.entries(stateNames) as [value,label]}<option {value}>{label}</option>{/each}</select></label></div>
    {#if !visibleOperations.length&&!loading&&!error}<p>{channelOperations.length?'No enquiries match these filters.':'No channel activity yet. Connect and enable a channel to start receiving enquiries.'}</p>{/if}
    {#each visibleOperations as row (row.id)}
      <article><div class="row"><strong>{row.channel==='email'?'Email':row.channel==='phone'?'Phone':'Workflow'} · {stateNames[row.state]||row.state}</strong><time datetime={new Date(row.created*1000).toISOString()}>{new Date(row.created*1000).toLocaleString()}</time></div>
        <p>{row.source_address}</p>{#if row.payload.subject}<h4>{row.payload.subject}</h4>{/if}
        {#if row.payload.text}<pre>{row.payload.text}</pre>{/if}
        {#if row.error_code}<p class="hint">{operationReasons[row.error_code]||'This item needs a review. Check its state and connection before taking further action.'} <span>Reference: {row.error_code.replaceAll('_',' ')}</span></p>{/if}
        {#if row.state==='needs_review'&&row.channel==='email'}<label for={'draft-'+row.id}>Reply to {row.source_address}<textarea id={'draft-'+row.id} bind:value={drafts[row.id]} maxlength="6000" rows="6" disabled={!canManage||Boolean(busyId)}></textarea></label><p class="hint">Approving sends this reply only to the original sender, from the verified business support address.</p><details class="email-preview"><summary>Preview final email</summary><p><strong>To:</strong> {row.source_address}</p><p><strong>Subject:</strong> {emailSubject(row.payload.subject||'')}</p><pre>{emailPreview(drafts[row.id]||'')}</pre></details>{:else if row.reply}<pre>{row.reply}</pre>{/if}
        {#if isPlatform&&row.provider_id}<p class="hint">Result reference: <code>{row.provider_id}</code></p>{/if}
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
  .activity-filters{display:flex;gap:1rem;flex-wrap:wrap}.activity-filters label{flex:1;min-width:min(100%,220px)}.readiness-checks{padding-left:1.2rem;font-size:.85rem;line-height:1.8}.email-preview{margin:.8rem 0;padding:1rem;border:1px solid #d6dfda;border-radius:8px}.email-preview summary{cursor:pointer;font-weight:600;min-height:28px}.email-preview pre{margin-bottom:0}
  .hub{display:grid;gap:1.25rem}.heading,.row{display:flex;justify-content:space-between;gap:1rem;align-items:start}.heading p{max-width:65ch}.eyebrow{font-size:.75rem;text-transform:uppercase;font-weight:700;color:#476358}h2,h3,h4,p{margin:.35rem 0 .75rem}.channels{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,290px),1fr));gap:1rem}fieldset,article,.notice{padding:1.2rem;border:1px solid #d6dfda;border-radius:12px;background:white}legend{font-weight:700;padding:0 .4rem}label{display:grid;gap:.35rem;margin:.8rem 0}.check{display:flex;gap:.6rem;align-items:flex-start}.check input{width:auto;margin-top:.2rem}input,select,textarea,button{font:inherit}input,select,textarea{max-width:100%;padding:.65rem;border:1px solid #bdc9c2;border-radius:7px;background:white}textarea{width:100%;box-sizing:border-box}button{padding:.65rem .9rem;border:1px solid #b9cbc1;border-radius:8px;color:#14503b;background:#f3f7f4;cursor:pointer;min-height:44px}button:disabled{opacity:.55;cursor:not-allowed}.hint,.connection,time{font-size:.85rem;color:#53645c}article{margin:1rem 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;line-height:1.5}code{overflow-wrap:anywhere}.buttons{display:flex;flex-wrap:wrap;gap:.5rem}.error{color:#9b1c1c}.notice{background:#f0f7f3}@media(max-width:640px){.heading,.row{display:block}.heading button{width:100%}}

 .channel-workflow{display:flex;gap:8px;overflow-x:auto;margin:20px 0;padding-bottom:7px}.channel-workflow a{display:flex;align-items:center;gap:8px;min-height:44px;padding:10px 13px;border:1px solid var(--v7-line);border-radius:9px;color:var(--v7-accent);font-size:12px;font-weight:600;text-decoration:none;white-space:nowrap}.channel-workflow span{width:21px;height:21px;border-radius:50%;display:grid;place-items:center;background:var(--v7-soft);font-size:10px}.channel-readiness{padding:18px 20px;border:1px solid var(--v7-tint-line);border-radius:12px;background:var(--v7-tint);margin-bottom:22px}.channel-readiness strong{font-size:14px}.channel-readiness p,.channel-test p{font-size:13px;line-height:1.8;margin:9px 0 0;color:var(--v7-muted)}.channel-test{padding:22px;border:1px solid var(--v7-line);border-radius:12px;margin-block:22px;background:var(--v7-canvas)}.channel-test h3{margin:0;font-size:16px}.channel-test .hint{font-size:11px}.channel-workflow a:focus-visible{outline:3px solid var(--v7-focus);outline-offset:3px}
</style>
