<script lang="ts">
  import { t } from './i18n';
  import { onMount, onDestroy } from 'svelte';

  export let tenant: string;
  export let apiPrefix = '';
  type View = 'messages' | 'leads' | 'questions';
  type Message = { id: number; ts_utc: string; channel: string; event_type: string; text: string };
  type Lead = { lead_id: string; name?: string; phone?: string; status?: string; updated_utc: string };
  type Question = { question: string; count: number };
  const views: { key: View; title: string }[] = [
    { key: 'messages', title: 'Messages' }, { key: 'leads', title: 'Leads' },
    { key: 'questions', title: 'Common questions' }
  ];
  let view: View = 'messages';
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
      nextBefore = null;
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
    <nav aria-label="Conversation views">
      {#each views as item}
        <button type="button" class:active={view === item.key} aria-pressed={view === item.key} on:click={() => view = item.key}>{item.title}</button>
      {/each}
    </nav>
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
        <p class="hint">{view === 'messages' ? 'Customer and agent messages in the selected period.' : view === 'leads' ? 'The most recent 50 leads across all dates. Manage follow-ups in Sales pipeline.' : 'The most frequent recorded questions in the selected period.'}</p></div>
      {#if !busy && !error}<span class="result-count">{view === 'messages' ? `${messages.length} loaded` : view === 'leads' ? `${leads.length} leads` : `${questions.length} questions`}</span>{/if}
    </div>
    {#if error}<p class="error" role="alert">{error}</p>{/if}
    {#if busy}<p class="loading" role="status">{view === 'messages' && messages.length ? 'Loading older messages…' : view === 'messages' ? 'Loading messages…' : view === 'leads' ? 'Loading leads…' : 'Loading common questions…'}</p>{/if}
    {#if !busy || (view === 'messages' && messages.length)}
    {#if !error && view === 'messages'}
      {#each messages as message (message.id)}
        <article class="message" class:agent={message.event_type !== 'msg_in'}>
          <div class="message-meta"><strong>{message.event_type === 'msg_in' ? 'Customer' : 'Agent'}</strong><span>{message.channel}</span><time datetime={message.ts_utc}>{dateLabel(message.ts_utc)}</time></div>
          <p>{message.text}</p>
        </article>
      {:else}<div class="empty"><strong>No messages recorded</strong><p>Try a longer time period to find earlier customer conversations.</p></div>{/each}
      {#if nextBefore}<button type="button" disabled={busy} on:click={() => refresh(tenant, view, minutes, nextBefore ?? undefined)}>Load older messages</button>{/if}
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
  .surface { min-width:0; background:var(--v7-surface,#fff); color:var(--v7-ink,#172b26); border:1px solid var(--v7-line,#e1e7e4); border-radius:12px; overflow-wrap:anywhere; }
  header { display:flex; flex-wrap:wrap; justify-content:space-between; align-items:end; gap:16px; padding:18px 20px; border-bottom:1px solid var(--v7-line); }
  nav,.tools { display:flex; flex-wrap:wrap; align-items:end; gap:8px; max-width:100%; }
  button,a { display:inline-flex; align-items:center; justify-content:center; min-height:44px; padding:9px 12px; border:1px solid var(--v7-control-line,#c5d1cb); border-radius:8px; color:var(--v7-ink); background:var(--v7-surface,#fff); font:inherit; font-size:13px; font-weight:600; text-decoration:none; }
  button { cursor:pointer; }
  button:hover:not(:disabled),a:hover { background:var(--v7-soft,#edf6f1); border-color:var(--v7-accent,#087f5b); }
  nav button { border-color:transparent; color:var(--v7-muted); }
  nav button.active { color:var(--v7-accent,#087f5b); background:var(--v7-soft,#edf6f1); border-color:var(--v7-line); }
  button:disabled { opacity:.6; cursor:wait; }
  :is(button,a,select):focus-visible { outline:3px solid var(--v7-accent,#087f5b); outline-offset:3px; }
  label { display:grid; gap:6px; min-width:0; color:var(--v7-muted); font-size:12px; font-weight:600; }
  select { max-width:100%; min-width:0; min-height:44px; padding:8px 10px; border:1px solid var(--v7-control-line,#c5d1cb); border-radius:8px; color:var(--v7-ink); background:var(--v7-surface,#fff); font:inherit; font-size:13px; }
  .content { padding:20px; }
  h2 { margin:0; font-size:20px; letter-spacing:-.025em; }
  .content-heading { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:12px; margin-bottom:20px; }
  .content-heading .hint { margin:6px 0 0; }
  .result-count { color:var(--v7-muted); background:var(--v7-canvas,#f5f7f7); border:1px solid var(--v7-line); border-radius:6px; padding:5px 8px; font-size:12px; font-weight:600; }
  .empty,.hint { color:var(--v7-muted); font-size:13px; line-height:1.6; }
  .empty { margin:0; padding:28px 20px; background:var(--v7-canvas,#f5f7f7); border:1px dashed var(--v7-line); border-radius:8px; text-align:center; }
  .empty strong { color:var(--v7-ink); font-size:14px; }
  .empty p { margin:6px 0 0; }
  .loading { margin:0 0 16px; padding:12px 14px; background:var(--v7-soft,#edf6f1); border-radius:8px; font-size:13px; color:var(--v7-accent); }
  .message,.lead,.question { padding:16px 0; border-top:1px solid var(--v7-line); }
  .message-meta { display:flex; flex-wrap:wrap; align-items:center; gap:10px; font-size:13px; }
  .message-meta strong { color:var(--v7-ink); }
  .message.agent .message-meta strong { color:var(--v7-accent); }
  .message-meta span,time { color:var(--v7-muted); font-size:12px; }
  .message-meta span { padding:3px 7px; background:var(--v7-canvas,#f5f7f7); border-radius:5px; }
  .message-meta time { margin-left:auto; }
  .message p { max-width:85ch; margin:10px 0 0; white-space:pre-wrap; line-height:1.7; font-size:14px; }
  .lead { display:grid; grid-template-columns:minmax(0,1fr) auto auto; gap:16px; align-items:center; font-size:14px; }
  .lead>div { display:grid; gap:6px; min-width:0; }
  .lead>div>span { color:var(--v7-muted); font-size:13px; }
  .status { padding:5px 8px; background:var(--v7-canvas,#f5f7f7); border:1px solid var(--v7-line); border-radius:6px; color:var(--v7-muted); font-size:12px; font-weight:600; }
  .question { display:flex; justify-content:space-between; gap:20px; line-height:1.6; font-size:14px; }
  .question strong { min-width:36px; align-self:start; padding:3px 7px; background:var(--v7-soft,#edf6f1); border-radius:5px; color:var(--v7-accent); text-align:center; font-size:12px; font-variant-numeric:tabular-nums; }
  .error { color:#b42318; padding:12px 14px; background:#fff2f0; border-radius:8px; font-size:13px; }
  @media(max-width:720px) { .lead { grid-template-columns:minmax(0,1fr) auto; } .lead time { grid-column:1 / -1; } .message-meta time { width:100%; margin-left:0; } }
  @media(max-width:520px) { header,.content { padding:16px; } nav { width:100%; } nav button { flex:1 1 120px; } .tools { width:100%; } .tools label { flex:1; } }
</style>
