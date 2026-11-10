<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import ConfirmDialog from './ConfirmDialog.svelte';
  import DraftGuard from './DraftGuard.svelte';

  export let tenant: string;
  export let csrf: string;
  export let canManage = false;
  export let apiPrefix = '';

  type Content = { title: string; subject: string; body: string };
  type Campaign = Content & {
    id: string; revision: string; audience_count: number; state: string; error_code: string;
  };
  type CampaignReport = {
    configured: boolean; sender: string; mailing_address: string; campaigns: Campaign[];
    can_manage?: boolean;
  };
  const blank = (): Content => ({ title: '', subject: '', body: '' });
  const states: Record<string, string> = {
    draft: 'Draft', reviewed: 'Reviewed', sending: 'Submitting', submitted: 'Submitted to provider',
    failed: 'Failed', uncertain: 'Check provider outcome'
  };
  const messages: Record<string, string> = {
    campaign_changed: 'This campaign changed. Refresh before trying again.',
    campaign_audience_changed: 'The audience changed. Review the latest recipient list before sending.',
    campaign_sender_not_configured: 'Ask the platform operator to connect a verified campaign sender and audience.',
    campaign_draft_unavailable: 'A draft could not be verified. Check your saved business knowledge and AI credit, or write the copy yourself.',
    campaign_consent_confirmation_required: 'Confirm the audience has opted in to these marketing emails.',
    campaign_review_required: 'Review the campaign and current audience again before sending.',
    campaign_audience_empty: 'This audience has no subscribed recipients.',
    campaign_audience_too_large: 'This audience exceeds the campaign recipient limit.',
    campaign_draft_rate_limited: 'Too many drafts requested. Wait a minute before drafting again.',
    campaign_provider_review_required: 'Check the outcome in your provider dashboard before trying again.',
    campaign_storage_limit: 'This workspace has reached its saved campaign limit.',
    campaign_provider_draft_failed: 'The provider could not create the broadcast draft. Review the settings before trying again.',
    campaign_provider_send_rejected: 'The provider rejected this broadcast. Review the sender and audience before trying again.',
    campaign_outcome_unknown: 'The send outcome is unknown. Check provider status before proceeding.'
  };

  let report: CampaignReport | null = null;
  let selected: Campaign | null = null;
  let form = blank();
  let saved = JSON.stringify(form);
  let brief = '', status = '', error = '', busy = '';
  let consent = false, disposed = false;
  let sendDialog: ConfirmDialog;
  let discardDialog: ConfirmDialog;
  let controller: AbortController | null = null;
  $: dirty = JSON.stringify(form) !== saved;
  $: editable = canManage && report?.can_manage !== false && (!selected || ['draft', 'reviewed', 'failed'].includes(selected.state));
  $: complete = Boolean(form.title.trim() && form.subject.trim() && form.body.trim());

  async function call<T>(path = '', method = 'GET', payload?: object): Promise<T> {
    const request = new AbortController();
    controller = request;
    const timer = setTimeout(() => request.abort(), path === '/generate' ? 70000 : 45000);
    try {
      const response = await fetch(`${apiPrefix}/admin/api/email-campaigns${path}?tenant=${encodeURIComponent(tenant)}`, {
        method, credentials: 'same-origin', signal: request.signal,
        headers: { Accept: 'application/json', 'X-CSRF-Token': csrf, ...(payload ? {'Content-Type': 'application/json'} : {}) },
        ...(payload ? { body: JSON.stringify(payload) } : {})
      });
      const data = await response.json();
      if (!response.ok) {
        const fallback = response.status === 403 ? 'Campaign management is available to authorised business owners.'
          : response.status === 409 ? 'The campaign or its audience changed. Refresh the status before continuing.'
          : 'The campaign request could not be completed. Refresh its status before retrying.';
        throw new Error(messages[data?.error] || fallback);
      }
      return data as T;
    } catch (failure) {
      if (request.signal.aborted) throw new Error('The outcome could not be confirmed. Refresh the campaign status before retrying.');
      throw failure;
    } finally {
      clearTimeout(timer);
      if (controller === request) controller = null;
    }
  }

  function show(campaign: Campaign | null) {
    selected = campaign;
    form = campaign ? { title: campaign.title, subject: campaign.subject, body: campaign.body } : blank();
    saved = JSON.stringify(form);
    consent = false;
  }

  async function choose(campaign: Campaign | null) {
    if (busy || (dirty && !await discardDialog.ask())) return;
    show(campaign);
    status = error = '';
  }

  async function run(label: string, action: () => Promise<void>) {
    if (busy || disposed) return;
    busy = label;
    status = error = '';
    try { await action(); }
    catch (failure) {
      if (!disposed) error = failure instanceof Error ? failure.message : 'The campaign request could not be completed.';
    } finally {
      if (!disposed) busy = '';
    }
  }

  async function refresh() {
    if (dirty && !await discardDialog.ask()) return;
    await run('Loading', async () => {
      const data = await call<CampaignReport>();
      if (disposed) return;
      report = data;
      if (selected) show(data.campaigns.find(campaign => campaign.id === selected?.id) || null);
      else if (dirty) show(null);
    });
  }

  function apply(campaign: Campaign) {
    if (!report || disposed) return;
    report = { ...report, campaigns: [campaign, ...report.campaigns.filter(row => row.id !== campaign.id)] };
    show(campaign);
  }

  async function save() {
    if (!editable || !complete) return;
    await run('Saving', async () => {
      const data = await call<{campaign: Campaign}>(selected ? '/' + selected.id : '', selected ? 'PUT' : 'POST',
        selected ? { ...form, revision: selected.revision } : form);
      if (disposed) return;
      apply(data.campaign);
      status = 'Draft saved.';
    });
  }

  async function generate() {
    if (!editable || !brief.trim()) return;
    if (form.body.trim() && !await discardDialog.ask()) return;
    await run('Drafting', async () => {
      const data = await call<{body: string}>('/generate', 'POST', { brief: brief.trim() });
      if (disposed) return;
      form = { ...form, body: data.body };
      status = 'AI draft prepared. Check the details and save it for review.';
    });
  }

  async function transition(action: 'review' | 'send' | 'reconcile') {
    if (!selected || !report?.configured || !canManage || dirty || busy) return;
    const target = selected;
    if (action === 'review' && (!consent || !editable)) return;
    if (action === 'send' && (target.state !== 'reviewed' || !await sendDialog.ask())) return;
    if (action === 'reconcile' && target.state !== 'uncertain') return;
    if (disposed || selected?.id !== target.id || selected?.revision !== target.revision || dirty) return;
    const body = { revision: target.revision, ...(action === 'review' ? { consent_confirmed: true }
      : action === 'send' ? { confirmed: true } : {}) };
    await run(action === 'send' ? 'Submitting' : 'Checking', async () => {
      const data = await call<{campaign: Campaign}>('/' + target.id + '/' + action, 'POST', body);
      if (disposed) return;
      apply(data.campaign);
      status = states[data.campaign.state] || 'Campaign updated.';
    });
  }

  onMount(refresh);
  onDestroy(() => { disposed = true; controller?.abort(); });
</script>

<DraftGuard {dirty}/>
<ConfirmDialog bind:this={discardDialog}/>
<ConfirmDialog bind:this={sendDialog} title="Submit this campaign?"
  description={`This will submit the saved email to the provider for ${selected?.audience_count || 0} opted-in recipients. Check the subject and copy before sending.`}
  confirmLabel="Submit campaign"/>

<section class="campaigns" aria-labelledby="campaign-heading" aria-busy={Boolean(busy)}>
  <header>
    <div><h3 id="campaign-heading">Email campaigns</h3>
      <p>Draft a message from your saved business knowledge, then review the copy and audience before sending.</p></div>
    <button type="button" class="secondary" on:click={refresh} disabled={Boolean(busy)}>Refresh</button>
  </header>
  {#if report}
    {#if report.configured}
      <p class="configuration">Sender <strong>{report.sender}</strong><br/>Mailing address <strong>{report.mailing_address}</strong></p>
    {:else}
      <p class="configuration">Campaign delivery awaits a verified sender and an opted-in audience. You can prepare drafts here.</p>
    {/if}
    <div class="campaign-grid">
      <div class="campaign-list">
        {#if canManage}<button type="button" class="secondary" on:click={() => choose(null)} disabled={Boolean(busy)}>New draft</button>{/if}
        {#if !report.campaigns.length}<p>No saved campaigns.</p>{/if}
        {#each report.campaigns as campaign (campaign.id)}
          <button type="button" class="campaign-row secondary" aria-pressed={selected?.id === campaign.id}
            on:click={() => choose(campaign)} disabled={Boolean(busy)}>
            <strong>{campaign.title}</strong><span>{states[campaign.state] || campaign.state}</span>
          </button>
        {/each}
      </div>
      <form on:submit|preventDefault={save}>
        <fieldset disabled={Boolean(busy) || !editable}>
          <label>Campaign name<input bind:value={form.title} maxlength="80" required/></label>
          <label>Subject<input bind:value={form.subject} maxlength="140" required/></label>
          <label>Campaign brief<textarea bind:value={brief} rows="2" maxlength="1200" placeholder="What should this email promote?"></textarea></label>
          <button type="button" class="secondary" on:click={generate} disabled={!brief.trim()}>Draft with AI</button>
          <label>Message<textarea bind:value={form.body} maxlength="6000" rows="7" required></textarea></label>
          <button type="submit" disabled={!complete || !dirty}>Save draft</button>
        </fieldset>
        {#if selected && editable && report.configured}
          <label class="checkbox"><input type="checkbox" bind:checked={consent} disabled={Boolean(busy) || dirty}/>
            I confirmed this audience opted in to receive marketing emails from this business.</label>
          <button type="button" on:click={() => transition('review')} disabled={!consent || dirty || Boolean(busy)}>Review audience and copy</button>
        {/if}
        {#if selected?.state === 'reviewed'}
          <p>Reviewed audience: {selected.audience_count} opted-in recipients. The provider adds the unsubscribe link.</p>
          <button type="button" on:click={() => transition('send')} disabled={!report.configured || !canManage || dirty || Boolean(busy)}>Send campaign</button>
        {:else if selected?.state === 'uncertain'}
          <p>Check whether the provider accepted this campaign before taking further action.</p>
          <button type="button" on:click={() => transition('reconcile')} disabled={!report.configured || !canManage || Boolean(busy)}>Check provider status</button>
        {/if}
        {#if selected?.error_code && messages[selected.error_code]}<p class="error">{messages[selected.error_code]}</p>{/if}
      </form>
    </div>
  {/if}
  {#if busy || status}<p role="status">{busy ? busy + '…' : status}</p>{/if}
  {#if error}<p class="error" role="alert">{error}</p>{/if}
</section>

<style>
  .campaigns { border: 1px solid var(--v7-line); border-radius: 16px; padding: 20px; margin: 20px 0; }
  header { display: flex; justify-content: space-between; align-items: start; gap: 16px; }
  h3 { margin: 0; }
  p { line-height: 1.5; }
  .configuration { background: #eef5f1; border-radius: 10px; padding: 12px; overflow-wrap: anywhere; }
  .campaign-grid { display: grid; grid-template-columns: minmax(135px, 1fr) minmax(0, 3fr); gap: 20px; }
  .campaign-list, form, fieldset { display: grid; align-content: start; gap: 12px; min-width: 0; }
  fieldset { padding: 0; margin: 0; border: 0; }
  label { display: grid; gap: 6px; font-weight: 600; }
  input:not([type='checkbox']), textarea { width: 100%; box-sizing: border-box; padding: 10px; border: 1px solid #b5c5bc; border-radius: 8px; font: inherit; }
  button { min-height: 44px; border: 1px solid #127557; border-radius: 8px; padding: 8px 12px; background: #127557; color: #fff; font: inherit; cursor: pointer; }
  .secondary { background: white; color: #174739; border-color: #aabdb2; }
  .campaign-row { display: grid; gap: 5px; text-align: left; overflow-wrap: anywhere; }
  .campaign-row[aria-pressed='true'] { background: #eef5f1; }
  .checkbox { display: flex; align-items: start; gap: 8px; }
  button:disabled { opacity: .55; cursor: default; }
  .error { color: #8d3026; }
  @media (max-width: 650px) { .campaign-grid { grid-template-columns: 1fr; } }
</style>
