<script lang="ts">
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
  onDestroy(() => controller?.abort());

  function dateLabel(value: string) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? 'Time unavailable' : date.toLocaleString();
  }

  async function refresh(company: string, selectedView: View, period: number, before?: number) {
    controller?.abort();
    const request = new AbortController();
    controller = request;
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
      if (request.signal.aborted) return;
      if (selectedView === 'messages') {
        messages = [...(before ? messages : []), ...(Array.isArray(data.messages) ? data.messages : [])];
        nextBefore = data.has_more && Number.isSafeInteger(data.next_before) ? data.next_before : null;
      } else if (selectedView === 'leads') {
        leads = Array.isArray(data) ? data : [];
      } else {
        questions = Array.isArray(data) ? data : [];
      }
    } catch (failure) {
      if (!request.signal.aborted) error = failure instanceof Error ? failure.message : 'Unable to load conversations.';
    } finally {
      if (!request.signal.aborted) busy = false;
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
      <button type="button" disabled={busy} on:click={() => refresh(tenant, view, minutes)}>Refresh</button>
      {#if view === 'leads'}
        <a href={apiPrefix + '/analytics/export.csv?tenant=' + encodeURIComponent(tenant)}>Export leads</a>
      {/if}
    </div>
  </header>
  <div class="content" aria-busy={busy}>
    {#if error}<p class="error" role="alert">{error}</p>{/if}
    {#if busy && !messages.length}<p class="empty" role="status">Loading…</p>
    {:else if !error && view === 'messages'}
      <h2>Recent messages</h2>
      {#each messages as message (message.id)}
        <article class="message">
          <div class="message-meta"><strong>{message.event_type === 'msg_in' ? 'Customer' : 'Agent'}</strong><span>{message.channel}</span><time datetime={message.ts_utc}>{dateLabel(message.ts_utc)}</time></div>
          <p>{message.text}</p>
        </article>
      {:else}<p class="empty">No messages recorded in this period.</p>{/each}
      {#if nextBefore}<button type="button" disabled={busy} on:click={() => refresh(tenant, view, minutes, nextBefore ?? undefined)}>Load older messages</button>{/if}
    {:else if !error && view === 'leads'}
      <h2>Latest leads</h2>
      <p class="hint">The most recent 50 leads. Manage follow-ups in Sales pipeline.</p>
      {#each leads as lead (lead.lead_id)}
        <article class="lead"><div><strong>{lead.name || lead.phone || 'Contact details not supplied'}</strong>{#if lead.name && lead.phone}<span>{lead.phone}</span>{/if}</div><span class="status">{lead.status || 'Open'}</span><time datetime={lead.updated_utc}>{dateLabel(lead.updated_utc)}</time></article>
      {:else}<p class="empty">No leads recorded yet.</p>{/each}
    {:else if !error}
      <h2>Common questions</h2>
      {#each questions as question}
        <div class="question"><span>{question.question}</span><strong>{question.count}</strong></div>
      {:else}<p class="empty">No questions recorded in this period.</p>{/each}
    {/if}
  </div>
</section>

<style>
  .surface { min-width: 0; background: #fff; border: 1px solid #d9ddd7; border-radius: 8px; overflow-wrap: anywhere; }
  header { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: end; gap: 20px; padding: 20px; border-bottom: 1px solid #e4e8e1; }
  nav, .tools { display: flex; flex-wrap: wrap; align-items: end; gap: 8px; max-width: 100%; }
  button, a { min-height: 40px; padding: 9px 12px; border: 1px solid #bbc4bc; border-radius: 6px; color: #2f3833; background: #fff; font-size: 14px; font-weight: 600; text-decoration: none; }
  button.active { color: #fff; background: #007d70; border-color: #007d70; }
  button:disabled { opacity: .6; cursor: wait; }
  button:focus-visible, a:focus-visible, select:focus-visible { outline: 3px solid #8bcdc0; outline-offset: 2px; }
  label { display: grid; gap: 6px; min-width: 0; color: #2f3833; font-size: 12px; font-weight: 600; }
  select { max-width: 100%; min-width: 0; min-height: 40px; padding: 8px 10px; border: 1px solid #bbc4bc; border-radius: 6px; color: #1f2923; background: #fff; }
  .content { padding: 20px; }
  h2 { margin: 0 0 16px; font-size: 17px; }
  .empty, .hint { color: #67706b; font-size: 14px; line-height: 1.5; }
  .empty { margin: 0; padding: 12px 0; }
  .message, .lead, .question { padding: 16px 0; border-top: 1px solid #e4e8e1; }
  .message-meta { display: flex; flex-wrap: wrap; align-items: baseline; gap: 12px; font-size: 13px; }
  .message-meta span, time { color: #67706b; font-size: 12px; }
  .message-meta time { margin-left: auto; }
  .message p { margin: 10px 0 0; white-space: pre-wrap; line-height: 1.6; }
  .lead { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 16px; align-items: center; font-size: 14px; }
  .lead > div { display: grid; gap: 6px; min-width: 0; }
  .status { padding: 5px 9px; background: #f1f5f0; border-radius: 6px; }
  .question { display: flex; justify-content: space-between; gap: 20px; line-height: 1.5; }
  .error { color: #b42318; padding: 12px; background: #fff2f0; border-radius: 6px; }
  @media (max-width: 720px) { .lead { grid-template-columns: minmax(0, 1fr) auto; } .lead time { grid-column: 1 / -1; } .message-meta time { width: 100%; margin-left: 0; } }
</style>
