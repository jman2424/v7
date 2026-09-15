<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  export let tenant: string;
  export let apiPrefix = '';

  type Group = { label: string; count: number };
  type FileCheck = { exists: boolean; valid: boolean | null };
  let minutes = 10080;
  let mounted = false;
  let loading = false;
  let checking = false;
  let activityError = '';
  let healthError = '';
  let errors: Group[] = [];
  let fallbacks: Group[] = [];
  let totals: { errors: number; fallbacks: number } | null = null;
  let checks: [string, FileCheck][] | null = null;
  let activityController: AbortController | undefined;
  let healthController: AbortController | undefined;

  async function get(path: string, signal: AbortSignal): Promise<unknown> {
    const response = await fetch(apiPrefix + path, { credentials: 'same-origin', signal, headers: { Accept: 'application/json' } });
    if (!response.ok) throw new Error('Request failed');
    return response.json();
  }

  function groups(value: unknown): Group[] {
    if (!Array.isArray(value) || !value.every(row => row && typeof row.label === 'string' && Number.isFinite(row.count) && row.count >= 0)) {
      throw new Error('Invalid activity response');
    }
    return value;
  }

  async function loadActivity(selectedTenant: string, period: number) {
    activityController?.abort();
    const controller = new AbortController();
    activityController = controller;
    loading = true; activityError = ''; totals = null; errors = []; fallbacks = [];
    const query = '?tenant=' + encodeURIComponent(selectedTenant) + '&minutes=' + period;
    try {
      const [errorRows, fallbackRows, kpis] = await Promise.all([
        get('/admin/api/errors' + query + '&top=50', controller.signal),
        get('/admin/api/fallbacks' + query + '&top=50', controller.signal),
        get('/admin/api/kpis' + query, controller.signal)
      ]);
      if (controller.signal.aborted) return;
      const parsedErrors = groups(errorRows), parsedFallbacks = groups(fallbackRows);
      if (!kpis || typeof kpis !== 'object' || !('errors' in kpis) || !('fallbacks' in kpis)
          || typeof kpis.errors !== 'number' || !Number.isFinite(kpis.errors) || kpis.errors < 0
          || typeof kpis.fallbacks !== 'number' || !Number.isFinite(kpis.fallbacks) || kpis.fallbacks < 0) throw new Error('Invalid totals');
      errors = parsedErrors; fallbacks = parsedFallbacks;
      totals = { errors: kpis.errors, fallbacks: kpis.fallbacks };
    } catch {
      if (!controller.signal.aborted) activityError = 'Activity could not be loaded. Retry, or sign in again if your session has expired.';
    } finally {
      if (!controller.signal.aborted) loading = false;
    }
  }

  async function checkHealth(selectedTenant: string) {
    healthController?.abort();
    const controller = new AbortController();
    healthController = controller;
    checking = true; healthError = ''; checks = null;
    try {
      const payload = await get('/__diag/validate?tenant=' + encodeURIComponent(selectedTenant), controller.signal);
      if (controller.signal.aborted) return;
      if (!payload || typeof payload !== 'object' || !('validation' in payload)
          || !payload.validation || typeof payload.validation !== 'object' || !('files' in payload.validation)
          || !payload.validation.files || typeof payload.validation.files !== 'object' || Array.isArray(payload.validation.files)) throw new Error('Invalid health response');
      const entries = Object.entries(payload.validation.files);
      if (!entries.length || !entries.every(([, result]) => result && typeof result.exists === 'boolean'
          && (typeof result.valid === 'boolean' || result.valid === null))) throw new Error('Invalid checks');
      checks = entries.map(([name, result]) => [name, { exists: result.exists, valid: result.valid }]);
    } catch {
      if (!controller.signal.aborted) healthError = 'Business data checks could not be completed. Retry, or sign in again if your session has expired.';
    } finally {
      if (!controller.signal.aborted) checking = false;
    }
  }

  onMount(() => { mounted = true; });
  onDestroy(() => { activityController?.abort(); healthController?.abort(); });
  $: if (mounted && tenant) loadActivity(tenant, minutes);
  $: if (mounted && tenant) checkHealth(tenant);
</script>

<section class="health-workspace" aria-label="Errors and business health">
  <div class="heading">
    <div><h2>Errors &amp; health</h2><p>Recorded failures and saved business data for {tenant}.</p></div>
    <div class="controls"><label>Activity period<select bind:value={minutes}><option value={1440}>Last 24 hours</option><option value={10080}>Last 7 days</option><option value={43200}>Last 30 days</option></select></label>
      <button type="button" disabled={loading} on:click={() => loadActivity(tenant, minutes)}>Refresh activity</button></div>
  </div>
  {#if loading}<p role="status">Loading recorded activity…</p>{/if}
  {#if activityError}<p class="failure" role="alert">{activityError}</p>{/if}
  <div class="metrics"><article class="panel"><h3>Recorded errors</h3><strong>{totals ? totals.errors.toLocaleString() : '—'}</strong></article>
    <article class="panel"><h3>Fallback replies</h3><strong>{totals ? totals.fallbacks.toLocaleString() : '—'}</strong><p>Replies where the agent needed more help.</p></article></div>
  {#if totals}
    <div class="breakdowns">
      {#each [{ title: 'Errors by cause', rows: errors }, { title: 'Fallbacks by topic', rows: fallbacks }] as group}
        <article class="panel"><h3>{group.title}</h3>
          {#if group.rows.length}<ul>{#each group.rows as row}<li><span>{row.label}</span><strong>{row.count.toLocaleString()}</strong></li>{/each}</ul><p>Up to 50 groups for the selected period.</p>
          {:else}<p>No recorded activity in this period.</p>{/if}
        </article>
      {/each}
    </div>
  {/if}
  <article class="panel" aria-labelledby="business-health-title">
    <div class="heading"><div><h3 id="business-health-title">Business data checks</h3><p>Check saved files without leaving your workspace.</p></div>
      <button type="button" disabled={checking} on:click={() => checkHealth(tenant)}>{checking ? 'Checking…' : 'Run data check'}</button></div>
    {#if checking}<p role="status">Checking this company's saved data…</p>{/if}
    {#if healthError}<p class="failure" role="alert">{healthError}</p>{/if}
    {#if checks}
      <p role="status">{checks.filter(([, result]) => result.exists && result.valid === true).length} files passed · {checks.filter(([, result]) => result.valid === false).length} need attention · {checks.filter(([, result]) => !result.exists).length} not configured.</p>
      <div class="table-wrap"><table><caption>Current business data</caption><thead><tr><th>File</th><th>Result</th><th>Next step</th></tr></thead>
        <tbody>{#each checks as [name, result]}<tr><th>{name}</th><td>{!result.exists ? 'Not configured' : result.valid === true ? 'Passed' : result.valid === false ? 'Needs attention' : 'Not checked'}</td><td>{!result.exists ? 'Add this information if your business uses it.' : result.valid === false ? 'Review the saved format with your platform operator.' : result.valid === true ? 'No action required.' : 'No schema check is available.'}</td></tr>{/each}</tbody>
      </table></div>
    {/if}
    <p class="note">These checks cover stored business data. They do not verify live WhatsApp delivery or external provider availability.</p>
  </article>
</section>

<style>
  .health-workspace{display:grid;gap:20px;min-width:0}.heading{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}h2,h3{margin:0 0 8px;color:#20332a}h2{font-size:22px}h3{font-size:16px}p{color:#59675f;line-height:1.5;margin:8px 0}.controls{display:flex;gap:12px;align-items:end;flex-wrap:wrap}label{display:grid;gap:6px;font-size:13px;font-weight:600}select,button{font:inherit;padding:10px 14px;border:1px solid #bbc4bc;border-radius:6px;background:#fff;color:#20332a}button{cursor:pointer;font-weight:600}button:disabled{opacity:.65;cursor:wait}:focus-visible{outline:3px solid #008879;outline-offset:3px}.metrics,.breakdowns{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.panel{background:#fff;border:1px solid #dce3dc;border-radius:10px;padding:22px;min-width:0}.metrics strong{font-size:30px}.panel ul{list-style:none;padding:0;margin:16px 0}.panel li{display:flex;justify-content:space-between;gap:20px;padding:10px 0;border-bottom:1px solid #edf0ec}.panel li span{overflow-wrap:anywhere}.table-wrap{overflow-x:auto}table{width:100%;border-collapse:collapse;text-align:left}caption{text-align:left;font-weight:600;padding:12px 0}th,td{padding:12px 10px;border-bottom:1px solid #e5e9e4;vertical-align:top;font-size:14px;overflow-wrap:anywhere}.failure{color:#a92b34;background:#fff0f0;padding:14px;border-radius:6px}.note{font-size:13px;margin-top:18px}@media(max-width:700px){.metrics,.breakdowns{grid-template-columns:1fr}.panel{padding:16px}.controls{width:100%}th,td{min-width:110px}}
</style>
