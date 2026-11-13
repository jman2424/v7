<script lang="ts">
  import {onMount,onDestroy} from 'svelte';
  import {statusText,decisionProblem,decisionNotice,waitingText,type Decision} from './applicationsText';
  export let csrf:string;
  export let apiPrefix='';
  type Application={tenant:string;status:string;revision:number;business_name:string;website:string;description:string;plan_id:string;contact_email:string;created:number;public_message:string;research?:{state?:string;summary?:string;sources?:{url:string;title:string}[]};history?:{kind:string;actor:string;note:string;created:number}[]};
  type Settings={revision:number;intake_enabled:boolean;research_enabled:boolean;guidance:string;policy:string;policy_version:string;legal_review_completed:boolean;categories:Record<string,string[]>;owner_email_enabled:boolean;owner_email:string;retention_days:number};
  let rows:Application[]=[], selected:Application|null=null, settings:Settings|null=null;
  let status='', search='', sort='newest', page=1, total=0, pending=0, hasNext=false;
  let decision:Decision='approve', note='', message='', error='', notice='', busy=false, alive=true;
  let general='', closer='', excluded='';
  const states=['PENDING_REVIEW','NEEDS_INFORMATION','APPROVED','REJECTED','EXPIRED','CANCELLED'];
  const requests=new Set<AbortController>();
  const date=(value:number)=>new Date(value*1000).toLocaleString();
  async function api(path:string,method='GET',body?:unknown,query:Record<string,string>={}){
    const controller=new AbortController();requests.add(controller);const timer=setTimeout(()=>controller.abort(),20000);
    try{const response=await fetch(apiPrefix+'/business-applications/'+path+'?'+new URLSearchParams(query),{method,credentials:'same-origin',signal:controller.signal,headers:{'X-CSRF-Token':csrf,...(body===undefined?{}:{'Content-Type':'application/json'})},...(body===undefined?{}:{body:JSON.stringify(body)})});const result=await response.json();if(!response.ok)throw new Error(result.error||'application_request_failed');return result;}
    finally{clearTimeout(timer);requests.delete(controller);}
  }
  async function fetchQueue(){const result=await api('queue','GET',undefined,{status,search,sort,page:String(page)});if(!alive)return;rows=result.applications;total=result.total;pending=result.pending;hasNext=result.has_next;}
  async function load(){if(busy)return;busy=true;error='';try{await fetchQueue();const result=await api('settings');if(!alive)return;settings=result.settings;general=settings!.categories.general.join('\n');closer=settings!.categories.closer_review.join('\n');excluded=settings!.categories.excluded.join('\n');}catch(failure){if(alive)error=failure instanceof Error?failure.message:'Could not load applications.';}finally{if(alive)busy=false;}}
  async function open(key:string){if(busy)return;busy=true;error='';notice='';try{const result=await api('review','GET',undefined,{tenant:key});if(alive){selected=result.application;note='';message='';}}catch(failure){if(alive)error=failure instanceof Error?failure.message:'Could not load review.';}finally{if(alive)busy=false;}}
  async function decide(choice:Decision=decision){if(!selected||busy)return;decision=choice;const problem=decisionProblem(decision,message);if(problem){error=problem;return;}if(decision==='reject'&&!confirm('Tell '+selected.business_name+' they are not approved? They can still correct their details and ask again.'))return;busy=true;error='';notice='';const name=selected.business_name;try{await api('review','POST',{revision:selected.revision,decision,note,message},{tenant:selected.tenant});const result=await api('review','GET',undefined,{tenant:selected.tenant});if(!alive)return;selected=result.application;note='';message='';notice=decisionNotice(decision,name);await fetchQueue();}catch(failure){if(alive)error=failure instanceof Error?failure.message:'Could not save review.';}finally{if(alive)busy=false;}}
  async function saveSettings(){if(!settings||busy)return;busy=true;error='';notice='';try{const result=await api('settings','PUT',{...settings,categories:{general:general.split('\n').filter(Boolean),closer_review:closer.split('\n').filter(Boolean),excluded:excluded.split('\n').filter(Boolean)}});if(alive){settings=result.settings;notice='Application settings saved and audited.';}}catch(failure){if(alive)error=failure instanceof Error?failure.message:'Could not save settings.';}finally{if(alive)busy=false;}}
  async function research(){if(!selected||busy)return;busy=true;error='';try{await api('research','POST',{revision:selected.revision},{tenant:selected.tenant});if(alive)notice='Advisory research queued. It cannot approve or reject the application.';}catch(failure){if(alive)error=failure instanceof Error?failure.message:'Research unavailable.';}finally{if(alive)busy=false;}}
  async function closePayments(){if(!selected||busy)return;busy=true;error='';try{await api('close-payments','POST',{}, {tenant:selected.tenant});if(alive)notice='Unpaid Stripe sessions resolved. Review the application again before deciding.';}catch(failure){if(alive)error=failure instanceof Error?failure.message:'Could not reconcile checkout.';}finally{if(alive)busy=false;}}
  onMount(async()=>{await load();const key=new URLSearchParams(window.location.search).get('application');if(key&&alive)await open(key);});
  onDestroy(()=>{alive=false;for(const request of requests)request.abort();});
</script>

<section class="applications">
  <div class="surface panel"><h2>Business Applications</h2><p>{#if pending}<strong>{waitingText(pending)}</strong>{:else}No applications are waiting.{/if} Only you can approve or decline a business. AI research is advice, never a decision.</p>
    {#if error}<p role="alert" class="error">{error.replaceAll('_',' ')}</p>{/if}{#if notice}<p role="status">{notice}</p>{/if}
    <form class="filters" on:submit|preventDefault={()=>{page=1;load();}}><label>Search<input bind:value={search} maxlength="120" placeholder="Business name, website or email"/></label><label>Status<select bind:value={status}><option value="">All applications</option>{#each states as state}<option value={state}>{statusText(state)}</option>{/each}</select></label><label>Sort<select bind:value={sort}><option value="newest">Newest first</option><option value="oldest">Oldest first</option></select></label><button disabled={busy}>Search</button></form>
    <p>{total} applications</p><div class="queue">{#each rows as row}<button class="application-row" disabled={busy} on:click={()=>open(row.tenant)}><strong>{row.business_name}</strong><span class="state" class:waiting={row.status==='PENDING_REVIEW'}>{statusText(row.status)}</span><span>{row.plan_id} · {date(row.created)}</span><small>{row.website||row.description}</small></button>{:else}<p>No matching applications.</p>{/each}</div>
    <div class="actions"><button disabled={busy||page===1} on:click={()=>{page--;load();}}>Previous</button><span>Page {page}</span><button disabled={busy||!hasNext} on:click={()=>{page++;load();}}>Next</button></div>
  </div>
  {#if selected}<section class="surface panel" aria-label="Application review"><h2>{selected.business_name}</h2><p>{selected.contact_email} · {selected.plan_id} · <span class="state" class:waiting={selected.status==='PENDING_REVIEW'}>{statusText(selected.status)}</span></p><p class="prose">{selected.description||'No separate description provided.'}</p>
    {#if selected.website}<a href={selected.website} target="_blank" rel="noopener noreferrer">Open business website ↗</a>{/if}
    <form on:submit|preventDefault={()=>decide('approve')}><fieldset disabled={busy}><legend>Your decision</legend><p>Judge what the business actually does and how it will use the assistant. Mixed activities need an individual decision. Never infer an owner's religion or other personal characteristics.</p><label>Private notes (only you see these)<textarea bind:value={note} maxlength="4000" rows="3"></textarea></label><label>Question for the applicant (sent to them when you ask for more information)<textarea bind:value={message} maxlength="2000" rows="3"></textarea></label><div class="decisions"><button class="primary" type="submit">Approve {selected.business_name}</button><button type="button" on:click={()=>decide('request_information')}>Ask for more information</button><button class="decline" type="button" on:click={()=>decide('reject')}>Do not approve</button></div><div class="decisions quiet"><button type="button" on:click={()=>decide('note')}>Save private note only</button><button type="button" on:click={()=>decide('expire')}>Mark as expired</button></div></fieldset></form>
    <details><summary>Payment and agent permissions</summary><p>An unresolved checkout blocks material changes or revocation until Stripe confirms that it is safely expired or paid. This does not cancel existing subscriptions.</p><button disabled={busy} on:click={closePayments}>Resolve unpaid checkouts</button><p>Business eligibility does not grant agent actions. Configure the business's separate tools and channel permissions in <a href={'/console/integrations?tenant='+encodeURIComponent(selected.tenant)}>Integrations</a> and <a href={'/console/operations?tenant='+encodeURIComponent(selected.tenant)}>Business hub</a>.</p></details>
    <h3>AI research</h3><p>Untrusted website claims are not proof of eligibility. Research cannot change the application status.</p><button disabled={busy||!settings?.research_enabled||!selected.website} on:click={research}>Gather advisory website research</button>{#if selected.research}<p>Status: {selected.research.state||'Not requested'}</p><p class="prose">{selected.research.summary||''}</p>{#each selected.research.sources||[] as source}<p><a href={source.url} target="_blank" rel="noopener noreferrer">{source.title||source.url} ↗</a></p>{/each}{/if}
    <h3>Review history</h3>{#each selected.history||[] as event}<article><strong>{event.kind.replaceAll('_',' ')}</strong> · {date(event.created)}{#if event.kind==='policy_accepted'}<details><summary>View accepted policy snapshot</summary><p class="prose">{event.note}</p></details>{:else}<p class="prose">{event.note}</p>{/if}</article>{/each}
  </section>{/if}
  {#if settings}<details class="surface panel"><summary>Restricted application settings</summary><form on:submit|preventDefault={saveSettings}><fieldset disabled={busy}><legend>Platform eligibility policy</legend><p class="legal">The AUP and rejection/reconsideration procedure require UK legal review before production rollout. This screen records your configuration; it does not provide legal clearance.</p><label class="check"><input type="checkbox" bind:checked={settings.legal_review_completed}/> Policy and rejection procedure have completed UK legal review</label><label class="check"><input type="checkbox" bind:checked={settings.intake_enabled}/> Accept new business applications</label><label>Customer guidance<textarea bind:value={settings.guidance} maxlength="2000" rows="3"></textarea></label><label>Public Acceptable Use Policy<textarea bind:value={settings.policy} maxlength="12000" rows="9"></textarea></label><label>Generally eligible activities (one per line)<textarea bind:value={general} rows="3"></textarea></label><label>Closer review (one per line)<textarea bind:value={closer} rows="3"></textarea></label><label>Excluded activities (one per line)<textarea bind:value={excluded} rows="3"></textarea></label><p>These categories inform human review. They do not automatically decide eligibility or grant agent action permissions.</p><label class="check"><input type="checkbox" bind:checked={settings.research_enabled}/> Enable advisory AI research using the platform's provider balance</label><label class="check"><input type="checkbox" bind:checked={settings.owner_email_enabled}/> Email the platform owner on submission</label><label>Owner notification email<input type="email" bind:value={settings.owner_email} maxlength="254"/></label><label>Closed-application personal-data retention (days)<input type="number" bind:value={settings.retention_days} min="30" max="730"/></label><button class="primary" type="submit">Save platform settings</button></fieldset></form></details>{/if}
</section>

<style>
  .applications{display:grid;gap:var(--v7-space-5)}
  .panel{padding:clamp(18px,3vw,28px)}
  h2{margin:0 0 var(--v7-space-2);font-size:var(--v7-text-xl)}h3{margin:var(--v7-space-5) 0 var(--v7-space-2);font-size:var(--v7-text-md)}
  p{margin:0 0 var(--v7-space-2);line-height:1.6;color:var(--v7-muted);font-size:var(--v7-text-sm)}
  form,fieldset,label{display:grid;gap:var(--v7-space-2)}form{margin:var(--v7-space-4) 0}
  fieldset{border:0;padding:0;gap:var(--v7-space-4);min-width:0}
  legend{padding:0;margin:0 0 var(--v7-space-2);font-size:var(--v7-text-md);font-weight:600;color:var(--v7-ink)}
  label{font-size:var(--v7-text-sm);font-weight:600;color:var(--v7-ink)}
  .filters{display:flex;flex-wrap:wrap;align-items:end;gap:var(--v7-space-3)}.filters label:first-child{flex:1;min-width:200px}
  input,textarea,select,button{box-sizing:border-box;max-width:100%;min-height:44px;padding:10px 12px;border:1px solid var(--v7-control-line);border-radius:var(--v7-radius-control);background:var(--v7-surface);color:var(--v7-ink);font:inherit;font-weight:400}
  input:focus,textarea:focus,select:focus{border-color:var(--v7-accent);outline:3px solid var(--v7-mint);outline-offset:0}
  button{font-weight:600;cursor:pointer;transition:background-color .15s,border-color .15s}
  button:hover{background:var(--v7-soft)}
  .primary{border-color:var(--v7-accent);background:var(--v7-accent);color:#fff}.primary:hover{background:var(--v7-accent-hover)}
  .decline{border-color:var(--v7-danger-line);color:var(--v7-danger)}.decline:hover{background:var(--v7-danger-soft)}
  .decisions{display:flex;flex-wrap:wrap;gap:var(--v7-space-2)}
  .decisions.quiet button{min-height:44px;border-color:transparent;padding-inline:4px;color:var(--v7-accent);text-decoration:underline;text-decoration-color:var(--v7-mint);text-decoration-thickness:2px;text-underline-offset:.3em;background:none}
  .queue{display:grid;border-top:1px solid var(--v7-line)}
  .application-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:4px var(--v7-space-4);align-items:center;min-height:0;padding:var(--v7-space-3) var(--v7-space-2);border:0;border-bottom:1px solid var(--v7-line);border-radius:0;text-align:start;font-weight:400;overflow-wrap:anywhere}
  .application-row strong{font-weight:600}.application-row small{grid-column:1/-1;color:var(--v7-muted)}.application-row span:nth-of-type(2){grid-column:1/-1;color:var(--v7-muted);font-size:var(--v7-text-xs)}
  .state{justify-self:end;padding:3px 10px;border-radius:var(--v7-radius-pill);background:var(--v7-soft);color:var(--v7-ink-soft);font-size:var(--v7-text-xs);font-weight:600;white-space:nowrap}
  .state.waiting{background:var(--v7-mint);color:var(--v7-on-mint)}
  .actions{display:flex;align-items:center;gap:var(--v7-space-3);margin-top:var(--v7-space-4)}
  .check{display:flex;align-items:center;font-weight:400}.check input{min-height:20px}
  .prose{white-space:pre-line;overflow-wrap:anywhere}
  article{border-top:1px solid var(--v7-line);padding:var(--v7-space-3) 0}
  summary{min-height:44px;align-content:center;font-size:var(--v7-text-md);font-weight:600;cursor:pointer}
  .legal{padding:var(--v7-space-3);border:1px solid var(--v7-line);border-radius:var(--v7-radius-control);background:var(--v7-canvas)}
  .error{padding:10px 12px;border:1px solid var(--v7-danger-line);border-radius:var(--v7-radius-control);background:var(--v7-danger-soft);color:var(--v7-danger)}
  [role=status]{padding:10px 12px;border:1px solid var(--v7-mint-line);border-radius:var(--v7-radius-control);background:var(--v7-mint-soft);color:var(--v7-on-mint)}
  button:disabled{opacity:.6;cursor:default}:focus-visible{outline:3px solid var(--v7-focus);outline-offset:2px}
</style>
