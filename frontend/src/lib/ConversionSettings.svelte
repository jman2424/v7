<script lang="ts">
  import { onMount } from 'svelte';

  export let tenant: string;
  export let csrf: string;
  export let apiPrefix = '';

  type Slot = { id: string; label: string; start_at: string };
  type Settings = { consultation: { enabled: boolean; slots: Slot[] }; quote: { enabled: boolean }; callback: { enabled: boolean } };
  type Request = { reference: string; action: string; status: string; slot_label?: string; name: string; contact: string; details: string; created_at: string };
  let settings: Settings = { consultation: { enabled: false, slots: [] }, quote: { enabled: false }, callback: { enabled: false } };
  let requests: Request[] = [];
  let loading = true;
  let busy = false;
  let status = '';
  let failed = false;
  const query = () => `?tenant=${encodeURIComponent(tenant)}`;

  async function load() {
    loading = true;
    try {
      const [setup, history] = await Promise.all([
        fetch(`${apiPrefix}/admin/api/sales-actions${query()}`, { credentials: 'same-origin' }),
        fetch(`${apiPrefix}/admin/api/action-requests${query()}`, { credentials: 'same-origin' })
      ]);
      if (!setup.ok || !history.ok) throw new Error('Could not load customer action settings.');
      settings = await setup.json() as Settings;
      requests = (await history.json() as { requests: Request[] }).requests || [];
    } catch (error) {
      failed = true;
      status = error instanceof Error ? error.message : 'Could not load customer action settings.';
    } finally {
      loading = false;
    }
  }

  function localTime(value: string): string {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
    return local.toISOString().slice(0, 16);
  }

  function updateTime(slot: Slot, value: string) {
    const date = new Date(value);
    slot.start_at = value && !Number.isNaN(date.getTime()) ? date.toISOString() : '';
    settings = settings;
  }

  function addSlot() {
    settings.consultation.slots = [...settings.consultation.slots, {
      id: `slot_${Date.now()}`, label: '', start_at: ''
    }];
    settings = settings;
  }

  function removeSlot(id: string) {
    settings.consultation.slots = settings.consultation.slots.filter(slot => slot.id !== id);
    settings = settings;
  }

  async function save() {
    busy = true;
    failed = false;
    status = 'Saving customer actions…';
    try {
      const response = await fetch(`${apiPrefix}/admin/api/sales-actions${query()}`, {
        method: 'PUT', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
        body: JSON.stringify(settings)
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || 'Could not save customer actions.');
      settings = data.settings as Settings;
      status = 'Saved. Enabled actions are available in the customer widget.';
    } catch (error) {
      failed = true;
      status = error instanceof Error ? error.message : 'Could not save customer actions.';
    } finally {
      busy = false;
    }
  }

  onMount(load);
</script>

<section class="actions" aria-labelledby="customer-actions-heading">
  <header><div><h2 id="customer-actions-heading">Customer next steps</h2><p>Enable only the actions this business can fulfil. Confirmed consultation times are reserved once; requests without a selected time still need staff follow-up.</p></div></header>
  {#if loading}<p class="notice" role="status">Loading customer actions…</p>
  {:else}
    <form on:submit|preventDefault={save}>
      <label class="toggle"><input type="checkbox" bind:checked={settings.consultation.enabled} />Book consultations</label>
      {#if settings.consultation.enabled}
        <div class="slots"><div class="slot-heading"><h3>Available time slots</h3><button type="button" on:click={addSlot}>Add time</button></div>
          <p>Times use your computer's local time zone. A slot confirms only after the customer submits it successfully.</p>
          {#each settings.consultation.slots as slot (slot.id)}
            <div class="slot"><label>Label<input bind:value={slot.label} maxlength="120" placeholder="Introductory consultation" required /></label>
              <label>Start time<input type="datetime-local" value={localTime(slot.start_at)} on:change={(event) => updateTime(slot, event.currentTarget.value)} required /></label>
              <button type="button" on:click={() => removeSlot(slot.id)} aria-label={`Remove ${slot.label || 'time slot'}`}>Remove</button></div>
          {/each}
        </div>
      {/if}
      <label class="toggle"><input type="checkbox" bind:checked={settings.quote.enabled} />Request quotes</label>
      <label class="toggle"><input type="checkbox" bind:checked={settings.callback.enabled} />Request callbacks</label>
      <div class="footer"><button type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save next steps'}</button><span class:error={failed} role="status">{status}</span></div>
    </form>
    <div class="requests"><div class="slot-heading"><h3>Recent customer requests</h3><button type="button" on:click={load}>Refresh</button></div>
      {#each requests as item}<article><strong>{item.action} · {item.status}</strong><span>{item.name} · {item.contact}</span>{#if item.slot_label}<span>{item.slot_label}</span>{/if}{#if item.details}<p>{item.details}</p>{/if}<small>{new Date(item.created_at).toLocaleString()} · {item.reference}</small></article>
      {:else}<p>No requests recorded yet.</p>{/each}
    </div>
  {/if}
</section>

<style>
  .actions { border:1px solid #d9ddd7; border-radius:8px; background:#fff; }
  header, form, .requests { padding:20px; }
  header { border-bottom:1px solid #e4e8e1; }
  h2, h3, p { margin:0; }
  h2 { margin-bottom:8px; font-size:17px; } h3 { font-size:14px; }
  p, small { color:#667085; font-size:13px; line-height:1.5; }
  form { display:grid; gap:15px; }
  .toggle { display:flex; align-items:center; gap:9px; font-weight:700; }
  .toggle input { width:17px; height:17px; accent-color:#0b765b; }
  .slots { display:grid; gap:12px; padding:16px; border:1px solid #e4e8e1; border-radius:7px; }
  .slot-heading, .footer { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:12px; }
  .slot { display:grid; grid-template-columns:minmax(120px,1fr) minmax(170px,1fr) auto; align-items:end; gap:10px; }
  .slot label { display:grid; gap:5px; font-size:12px; font-weight:700; }
  .slot input { width:100%; min-height:39px; padding:7px; border:1px solid #bbc4bc; border-radius:5px; }
  button { min-height:39px; padding:7px 12px; border:1px solid #b8c8bd; border-radius:5px; color:#224333; background:#fff; font-weight:700; cursor:pointer; }
  button[type=submit] { color:#fff; background:#0b765b; border-color:#0b765b; }
  button:disabled { opacity:.55; cursor:default; }
  button:focus-visible, input:focus-visible { outline:3px solid #8bcdc0; outline-offset:2px; }
  .error { color:#b42318; }
  .requests { border-top:1px solid #e4e8e1; }
  .requests article { display:grid; gap:3px; padding:12px 0; border-bottom:1px solid #e4e8e1; font-size:13px; overflow-wrap:anywhere; }
  .requests article strong { text-transform:capitalize; }
  .requests article p { color:#344054; }
  @media (max-width:650px) { .slot { grid-template-columns:1fr; } }
</style>
