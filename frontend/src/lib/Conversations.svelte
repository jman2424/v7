<script lang="ts">
  import { t } from './i18n';
  import {conversationThreads,type InboxMessage} from './conversationInbox';
  import { onMount, onDestroy } from 'svelte';

  export let tenant: string;
  export let apiPrefix = '';
  type View = 'messages' | 'leads' | 'questions';
  export let initialView:View='messages';
  export let showViewSwitcher=true;
  type Message = InboxMessage;
  let query='',channel='',selectedThread='',threadOpen=false;
  $: channels=[...new Set(messages.map(message=>message.channel))];
  $: threads=conversationThreads(messages,channel,query);
  $: currentThread=threads.find(thread=>thread.key===selectedThread)||threads[0];
  type Lead = { lead_id: string; name?: string; phone?: string; status?: string; updated_utc: string };
  type Question = { question: string; count: number };
  const views: { key: View; title: string }[] = [
    { key: 'messages', title: 'Messages' }, { key: 'leads', title: 'Leads' },
    { key: 'questions', title: 'Common questions' }
  ];
  let view: View = initialView;
  let minutes = 1440;
  let messages: Message[] = [];
  let leads: Lead[] = [];
  let questions: Question[] = [];
  let nextBefore: number | null = null;
  let busy = false;
  let error = '';
  let mounted = false;
  let controller: AbortController | undefined;
  $: if (mounted) refresh(tenant, view, minutes);

  onMount(() => { mounted = true; });
  onDestroy(() => { controller?.abort(); controller = undefined; });

  function dateLabel(value: string) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? 'Time unavailable' : date.toLocaleString();
  }

  async function refresh(company: string, selectedView: View, period: number, before?: number) {
    controller?.abort();
    const request = new AbortController();
    controller = request;
    const timeout = setTimeout(() => request.abort(), 20000);
    busy = true;
    error = '';
    if (!before) {
      messages = [];
      leads = [];
      questions = [];
      nextBefore = null;selectedThread='';threadOpen=false;
    }
    const query = new URLSearchParams({ tenant: company, minutes: String(period) });
    const endpoint = selectedView === 'messages' ? 'conversations' : selectedView;
    if (before) query.set('before', String(before));
    if (selectedView === 'leads') query.set('limit', '50');
    if (selectedView === 'questions') query.set('top', '20');
    try {
      const response = await fetch(apiPrefix + '/admin/api/' + endpoint + '?' + query, {
        credentials: 'same-origin', signal: request.signal
      });
      if (!response.ok) throw new Error(response.status === 401 ? 'Your session expired. Sign in again to view conversations.' : 'Could not load conversations. Try refreshing.');
      const data = await response.json();
      if (controller !== request || request.signal.aborted) return;
      if (selectedView === 'messages') {
        messages = [...(before ? messages : []), ...(Array.isArray(data.messages) ? data.messages : [])];
        nextBefore = data.has_more && Number.isSafeInteger(data.next_before) ? data.next_before : null;
      } else if (selectedView === 'leads') {
        leads = Array.isArray(data) ? data : [];
      } else {
        questions = Array.isArray(data) ? data : [];
      }
    } catch (failure) {
      if (controller === request) error = request.signal.aborted ? 'Loading timed out. Try refreshing.' : failure instanceof Error ? failure.message : 'Unable to load conversations.';
    } finally {
      clearTimeout(timeout);
      if (controller === request) { busy = false; controller = undefined; }
    }
  }
</script>

<section class="surface" aria-label="Conversations and leads">
  <header>
    {#if showViewSwitcher}<nav aria-label="Conversation views">
      {#each views as item}
        <button type="button" class:active={view === item.key} aria-pressed={view === item.key} on:click={() => view = item.key}>{item.title}</button>
      {/each}
    </nav>{/if}
    <div class="tools">
      {#if view !== 'leads'}
        <label>Time period<select bind:value={minutes}><option value={1440}>Last 24 hours</option><option value={10080}>Last 7 days</option><option value={43200}>Last 30 days</option></select></label>
      {/if}
      <button type="button" disabled={busy} on:click={() => refresh(tenant, view, minutes)}>{$t("Refresh")}</button>
      {#if view === 'leads'}
        <a href={apiPrefix + '/analytics/export.csv?tenant=' + encodeURIComponent(tenant)}>Export leads</a>
      {/if}
    </div>
  </header>
  <div class="content" aria-busy={busy}>
    <div class="content-heading">
      <div><h2>{view === 'messages' ? 'Recent messages' : view === 'leads' ? 'Latest leads' : 'Common questions'}</h2>
        <p class="hint">{view === 'messages' ? 'Messages and reported website button clicks in the selected period. A click does not confirm a purchase, booking or completed page visit.' : view === 'leads' ? 'The most recent 50 leads across all dates. Manage follow-ups in Sales pipeline.' : 'The most frequent recorded questions in the selected period.'}</p></div>
      {#if !busy && !error}<span class="result-count">{view === 'messages' ? `${messages.length} loaded` : view === 'leads' ? `${leads.length} leads` : `${questions.length} questions`}</span>{/if}
    </div>
    {#if error}<p class="error" role="alert">{error}</p>{/if}
    {#if busy}<p class="loading" role="status">{view === 'messages' && messages.length ? 'Loading older messages…' : view === 'messages' ? 'Loading messages…' : view === 'leads' ? 'Loading leads…' : 'Loading common questions…'}</p>{/if}
    {#if !busy || (view === 'messages' && messages.length)}
    {#if !error && view === 'messages'}
      <div class="inbox-filters"><label>Search loaded messages<input type="search" bind:value={query} placeholder="Find a conversation…"/></label><label>Channel<select bind:value={channel}><option value="">All channels</option>{#each channels as value}<option value={value}>{value}</option>{/each}</select></label></div>
      <div class="inbox" class:thread-open={threadOpen}>
        <div class="thread-list" role="region" aria-label="Customer conversations">
          {#each threads as thread}<button class="thread" class:selected={currentThread?.key===thread.key} aria-pressed={currentThread?.key===thread.key} on:click={()=>{selectedThread=thread.key;threadOpen=true;}}><span class="thread-top"><strong>{thread.channel}</strong><time datetime={thread.latest.ts_utc}>{new Date(thread.latest.ts_utc).toLocaleDateString()}</time></span><span class="thread-title">{thread.title}</span><span class="thread-preview">{thread.latest.text}</span><span class="thread-count">{thread.messages.length} loaded messages</span></button>{:else}<div class="empty"><strong>{messages.length?'No matching conversations':'No messages recorded'}</strong><p>{messages.length?'Try another search or channel.':'Choose a longer time period to find earlier conversations.'}</p></div>{/each}
        </div>
        <div class="thread-content" role="region" aria-label="Selected conversation">
          {#if currentThread}<div class="thread-heading"><button class="back-to-inbox" on:click={()=>threadOpen=false}>← Conversations</button><div><h3>Customer conversation</h3><p>{currentThread.channel} · Loaded history in the selected period</p></div></div><div class="message-bubbles">{#each currentThread.messages as message (message.id)}<article class="bubble" class:agent={message.event_type==='msg_out'} class:activity={message.event_type==='navigation_click'}><div class="message-meta"><strong>{message.event_type==='navigation_click'?'Customer clicked a button':message.event_type==='msg_in'?'Customer':'AI assistant'}</strong><time datetime={message.ts_utc}>{dateLabel(message.ts_utc)}</time></div><p>{message.text}</p></article>{/each}</div>{:else}<div class="thread-placeholder"><strong>Your customer conversations, together</strong><p>Select a conversation to read its available history.</p></div>{/if}
        </div>
      </div>
      {#if nextBefore}<button class="load-older" type="button" disabled={busy} on:click={() => refresh(tenant, view, minutes, nextBefore ?? undefined)}>Load older messages</button>{/if}
      <p class="hint inbox-note">Only loaded messages are searched. Load older messages to see more history. A button click does not confirm a completed booking or purchase.</p>
    {:else if !error && view === 'leads'}
      {#each leads as lead (lead.lead_id)}
        <article class="lead"><div><strong>{lead.name || lead.phone || 'Contact details not supplied'}</strong>{#if lead.name && lead.phone}<span>{lead.phone}</span>{/if}</div><span class="status">{lead.status || 'Open'}</span><time datetime={lead.updated_utc}>{dateLabel(lead.updated_utc)}</time></article>
      {:else}<div class="empty"><strong>No leads recorded yet</strong><p>Customers who share contact details will appear here.</p></div>{/each}
    {:else if !error}
      {#each questions as question}
        <div class="question"><span>{question.question}</span><strong>{question.count}</strong></div>
      {:else}<div class="empty"><strong>No questions recorded</strong><p>Try a longer time period to review earlier customer questions.</p></div>{/each}
    {/if}
    {/if}
  </div>
</section>

<style>
  .surface { min-width:0; background:var(--v7-surface,#fff); color:var(--v7-ink,var(--v7-ink)); border:1px solid var(--v7-line,var(--v7-line)); border-radius:var(--v7-radius-panel); overflow-wrap:anywhere; }
  header { display:flex; flex-wrap:wrap; justify-content:space-between; align-items:end; gap:16px; padding:18px 20px; border-bottom:1px solid var(--v7-line); }
  nav,.tools { display:flex; flex-wrap:wrap; align-items:end; gap:8px; max-width:100%; }
  button,a { display:inline-flex; align-items:center; justify-content:center; min-height:44px; padding:9px 12px; border:1px solid var(--v7-control-line,var(--v7-control-line)); border-radius:var(--v7-radius-control); color:var(--v7-ink); background:var(--v7-surface,#fff); font:inherit; font-size:var(--v7-text-sm); font-weight:600; text-decoration:none; }
  button { cursor:pointer; }
  button:hover:not(:disabled),a:hover { background:var(--v7-soft,var(--v7-tint)); border-color:var(--v7-accent,var(--v7-accent)); }
  nav button { border-color:transparent; color:var(--v7-muted); }
  nav button.active { color:var(--v7-accent,var(--v7-accent)); background:var(--v7-soft,var(--v7-tint)); border-color:var(--v7-line); }
  button:disabled { opacity:.6; cursor:wait; }
  :is(button,a,select):focus-visible { outline:3px solid var(--v7-accent,var(--v7-accent)); outline-offset:3px; }
  label { display:grid; gap:6px; min-width:0; color:var(--v7-muted); font-size:var(--v7-text-xs); font-weight:600; }
  select { max-width:100%; min-width:0; min-height:44px; padding:8px 10px; border:1px solid var(--v7-control-line,var(--v7-control-line)); border-radius:var(--v7-radius-control); color:var(--v7-ink); background:var(--v7-surface,#fff); font:inherit; font-size:var(--v7-text-sm); }
  .content { padding:20px; }
  h2 { margin:0; font-size:var(--v7-text-xl); letter-spacing:-.025em; }
  .content-heading { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:12px; margin-bottom:20px; }
  .content-heading .hint { margin:6px 0 0; }
  .result-count { color:var(--v7-muted); background:var(--v7-canvas,var(--v7-canvas)); border:1px solid var(--v7-line); border-radius:var(--v7-radius-control); padding:5px 8px; font-size:var(--v7-text-xs); font-weight:600; }
  .empty,.hint { color:var(--v7-muted); font-size:var(--v7-text-sm); line-height:1.6; }
  .empty { margin:0; padding:28px 20px; background:var(--v7-canvas,var(--v7-canvas)); border:1px dashed var(--v7-line); border-radius:var(--v7-radius-control); text-align:center; }
  .empty strong { color:var(--v7-ink); font-size:var(--v7-text-sm); }
  .empty p { margin:6px 0 0; }
  .loading { margin:0 0 16px; padding:12px 14px; background:var(--v7-soft,var(--v7-tint)); border-radius:var(--v7-radius-control); font-size:var(--v7-text-sm); color:var(--v7-accent); }
  .lead,.question { padding:16px 0; border-top:1px solid var(--v7-line); }
  .message-meta { display:flex; flex-wrap:wrap; align-items:center; gap:10px; font-size:var(--v7-text-sm); }
  .message-meta strong { color:var(--v7-ink); }
  time { color:var(--v7-muted); font-size:var(--v7-text-xs); }
  .message-meta time { margin-left:auto; }
  .lead { display:grid; grid-template-columns:minmax(0,1fr) auto auto; gap:16px; align-items:center; font-size:var(--v7-text-sm); }
  .lead>div { display:grid; gap:6px; min-width:0; }
  .lead>div>span { color:var(--v7-muted); font-size:var(--v7-text-sm); }
  .status { padding:5px 8px; background:var(--v7-canvas,var(--v7-canvas)); border:1px solid var(--v7-line); border-radius:var(--v7-radius-control); color:var(--v7-muted); font-size:var(--v7-text-xs); font-weight:600; }
  .question { display:flex; justify-content:space-between; gap:20px; line-height:1.6; font-size:var(--v7-text-sm); }
  .question strong { min-width:36px; align-self:start; padding:3px 7px; background:var(--v7-soft,var(--v7-tint)); border-radius:var(--v7-radius-control); color:var(--v7-accent); text-align:center; font-size:var(--v7-text-xs); font-variant-numeric:tabular-nums; }
  .error { color:var(--v7-danger); padding:12px 14px; background:var(--v7-danger-soft); border-radius:var(--v7-radius-control); font-size:var(--v7-text-sm); }
  @media(max-width:720px) { .lead { grid-template-columns:minmax(0,1fr) auto; } .lead time { grid-column:1 / -1; } .message-meta time { width:100%; margin-left:0; } }
  @media(max-width:520px) { header,.content { padding:16px; } nav { width:100%; } nav button { flex:1 1 120px; } .tools { width:100%; } .tools label { flex:1; } }

 .inbox-filters{display:flex;align-items:end;gap:12px;margin:0 0 20px}.inbox-filters>label:first-child{flex:1}.inbox-filters input{width:100%;min-height:44px;border:1px solid var(--v7-control-line);border-radius:var(--v7-radius-control);padding:10px 12px;background:var(--v7-surface);color:var(--v7-ink);font:inherit}.inbox{display:grid;grid-template-columns:minmax(210px,.8fr) minmax(0,1.6fr);border:1px solid var(--v7-line);border-radius:var(--v7-radius-panel);min-height:440px;overflow:hidden;background:var(--v7-canvas)}.thread-list{background:var(--v7-surface);border-inline-end:1px solid var(--v7-line);max-height:650px;overflow-y:auto}.thread{width:100%;display:flex;align-items:stretch;flex-direction:column;gap:9px;text-align:start;border:0;border-radius:0;border-bottom:1px solid var(--v7-line);padding:18px;font-weight:400;background:var(--v7-surface);color:var(--v7-ink)}.thread.selected{background:var(--v7-soft);box-shadow:inset 3px 0 var(--v7-accent)}.thread-top{display:flex;justify-content:space-between;gap:12px;align-items:center}.thread-top strong{font-size:var(--v7-text-xs);text-transform:uppercase;letter-spacing:.06em;color:var(--v7-accent)}.thread-top time{font-size:var(--v7-text-xs)}.thread-title,.thread-preview{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:block;max-width:100%}.thread-title{font-size:var(--v7-text-xs);font-weight:600}.thread-preview{color:var(--v7-muted);font-size:var(--v7-text-xs)}.thread-count{color:var(--v7-muted);font-size:var(--v7-text-xs)}.thread-content{min-width:0}.thread-heading{border-bottom:1px solid var(--v7-line);background:var(--v7-surface);padding:20px}.thread-heading h3{font-size:var(--v7-text-sm);margin:0 0 5px}.thread-heading p{font-size:var(--v7-text-xs);color:var(--v7-muted);margin:0}.message-bubbles{display:flex;flex-direction:column;gap:16px;padding:24px;max-height:565px;overflow-y:auto}.bubble{align-self:flex-start;max-width:92%;padding:16px;border:1px solid var(--v7-line);border-radius:12px 12px 12px 3px;background:var(--v7-surface)}.bubble.agent{align-self:flex-end;background:#e9f2eb;border-color:#d2e2d6;border-radius:12px 12px 3px 12px}.bubble.activity{background:none;border-style:dashed;align-self:center}.bubble p{white-space:pre-wrap;font-size:var(--v7-text-sm);line-height:1.8;margin:12px 0 0}.bubble .message-meta{gap:8px;font-size:var(--v7-text-xs)}.bubble .message-meta time{font-size:var(--v7-text-xs)}.thread-placeholder{min-height:400px;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;padding:30px;color:var(--v7-muted);font-size:var(--v7-text-sm)}.thread-placeholder strong{color:var(--v7-ink)}.thread-placeholder p{line-height:1.7}.back-to-inbox{display:none}.load-older{margin-top:18px}.inbox-note{margin:15px 0 0}input:focus-visible{outline:3px solid var(--v7-accent);outline-offset:3px}
 @media(max-width:650px){.inbox-filters{align-items:stretch;flex-direction:column}.inbox{grid-template-columns:1fr;min-height:360px}.thread-content{display:none}.thread-open .thread-list{display:none}.thread-open .thread-content{display:block}.thread-list{border:0}.back-to-inbox{display:inline-flex;margin-bottom:15px;border:0;padding:0;min-height:44px;color:var(--v7-accent)}.message-bubbles{padding:16px}.bubble{max-width:96%;padding:14px}.thread-heading{padding:15px}}
</style>
