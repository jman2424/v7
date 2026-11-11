<script lang="ts">
  import { t } from './i18n';
  import { onMount, onDestroy } from 'svelte';
  export let csrf: string;
  export let apiPrefix = '';
  type Settings = {
    configured: boolean;
    owner_access: boolean;
    clients: string[];
    connected_clients: string[];
    mcp_url: string;
    api_url: string;
    authorization_url: string;
    token_url: string;
    configuration_issues?: string[];
  };
  const issueLabels: Record<string, string> = {
    mcp_not_configured: 'Ask the platform operator to set the public HTTPS integration address.',
    mcp_invalid_public_url: 'Ask the platform operator to correct the public HTTPS integration address.',
    mcp_https_configuration_required: 'Ask the platform operator to match the integration address to the site’s HTTPS address and enable secure cookies.',
    mcp_no_oauth_clients: 'Ask the platform operator to register your app’s exact HTTPS callback URL.',
    mcp_invalid_oauth_configuration: 'Ask the platform operator to check the registered OAuth client settings.',
  };
  let settings: Settings | null = null;
  let error = '';
  let status = '';
  let busy = false;
  let confirmRevoke = false;
  const controller = new AbortController();
  onMount(() => { void load(); });
  onDestroy(() => controller.abort());
  async function load() {
    error = '';
    try {
      const response = await fetch(apiPrefix+'/auth/mcp/connections', {credentials:'same-origin',signal:controller.signal});
      if (response.status === 401) throw new Error('Sign in again to view connection settings.');
      if (response.status === 403) throw new Error('This account cannot view integration settings.');
      if (!response.ok) throw new Error('Could not load connection settings. Try again.');
      settings = await response.json();
    } catch (failure) { if (!controller.signal.aborted) error = failure instanceof Error ? failure.message : 'Could not load connections.'; }
  }
  async function copy(value:string) {
    try { await navigator.clipboard.writeText(value); status = 'Copied.'; }
    catch { status = 'Select the text and copy it manually.'; }
  }
  async function revoke() {
    busy = true; error = ''; status = '';
    try {
      const response = await fetch(apiPrefix+'/auth/mcp/revoke',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:'{}',signal:controller.signal});
      if (!response.ok) throw new Error('Could not revoke connections. Refresh and try again.');
      confirmRevoke = false; status = 'Your MCP and API connections have been revoked.'; await load();
    } catch (failure) { if (!controller.signal.aborted) error = failure instanceof Error ? failure.message : 'Could not revoke connections.'; }
    finally { busy = false; }
  }
  $: setupIssues = (settings?.configuration_issues ?? []).map(
    (code) => issueLabels[code] ?? 'Ask the platform operator to check the integration settings.'
  );
  $: example = settings?.configured && settings.api_url
    ? `curl --fail-with-body "${settings.api_url}/health" -H "Authorization: Bearer YOUR_ACCESS_TOKEN"`
    : '';
</script>

<section class="connections" aria-label="MCP and REST API connections">
  {#if error}<p role="alert">{error}</p><button type="button" on:click={load}>Retry</button>{/if}
  {#if settings}
    <div class="heading"><div><p class="eyebrow">Apps and developers</p><h2>MCP &amp; API connections</h2></div><span class="badge">{settings.configured ? 'Ready for OAuth authorization' : 'Setup required'}</span></div>
    {#if setupIssues.length}
      <ul aria-label="Connection setup steps">{#each setupIssues as issue}<li>{issue}</li>{/each}</ul>
    {:else if !settings.configured}
      <p>Ask the platform operator to configure the public HTTPS address and register your app’s exact callback URL.</p>
    {/if}
    {#if !settings.owner_access}<p>Connections must be authorized from a business owner account. This account can view setup information only.</p>{/if}
    <div class="cards">
      <article><h3>MCP connection</h3><p>Connect an MCP-compatible app to your business stats, catalogue, offers, roles, health and errors.</p>
        <label>Server URL<input readonly value={settings.mcp_url} placeholder="Available after server setup" /></label><button type="button" disabled={!settings.mcp_url} on:click={()=>copy(settings!.mcp_url)}>Copy MCP URL</button>
        <ol><li>Add a remote MCP server in your app and paste this URL.</li><li>Choose OAuth and use a registered client ID below. Ask the operator to register your app’s exact callback URL if needed.</li><li>Sign in through the console as the business owner, then approve read access and optional write access.</li></ol>
      </article>
      <article><h3>REST API connection</h3><p>Use the same OAuth connection for authenticated HTTP requests.</p>
        <label>API base URL<input readonly value={settings.api_url} placeholder="Available after server setup" /></label><button type="button" disabled={!settings.api_url} on:click={()=>copy(settings!.api_url)}>Copy API URL</button>
        <ol>
          <li>Use your app’s registered client ID and exact callback URL.</li>
          <li>Use the authorization-code flow with S256 PKCE and request the <code>business:read</code> scope. Use the MCP server URL as the resource in both requests.</li>
          <li>Approve the connection from the business-owner account and send the resulting access token as <code>Authorization: Bearer</code>.</li>
        </ol>
        <p><a href={apiPrefix+'/api/v1/openapi.json'}>Open the REST API reference</a></p>
        {#if example}
          <label>Example request<textarea readonly value={example} rows="3"></textarea></label>
          <button type="button" on:click={()=>copy(example)}>Copy example</button>
        {/if}
        <p>Start with <code>/health</code>, <code>/statistics</code>, <code>/catalog</code> or <code>/offerings</code>. Writes require <code>business:write</code>, the corresponding business permission and the latest document revision.</p>
      </article>
    </div>
    <details><summary>OAuth connection details</summary>
      <label>Authorization endpoint<input readonly value={settings.authorization_url} /></label>
      <label>Token endpoint<input readonly value={settings.token_url} /></label>
      <p>Registered client IDs: {settings.clients.join(', ') || 'None configured'}</p>
      <p>Scopes: <code>business:read</code> and optional <code>business:write</code>. Tokens expire after 15 minutes; refresh tokens rotate on use. Both interfaces use your assigned business and share a 60-request-per-minute allowance.</p>
      <p>Keep access tokens, refresh tokens and client secrets in your app’s protected storage. No API key is needed or displayed here.</p>
    </details>
    {#if settings.owner_access}
      <h3>Your connected apps</h3>
      <p>{settings.connected_clients.length ? settings.connected_clients.join(', ') : 'No active authorized apps.'}</p>
      <p>Revoking disconnects your apps from both MCP and REST. Each app must be authorized again.</p>
      {#if confirmRevoke}<p>Revoke all your MCP and API connections?</p><button type="button" disabled={busy} on:click={revoke}>{busy ? 'Revoking…' : 'Confirm revocation'}</button> <button type="button" disabled={busy} on:click={()=>confirmRevoke=false}>{$t("Cancel")}</button>
      {:else}<button type="button" on:click={()=>confirmRevoke=true}>Revoke my connections</button>{/if}
    {/if}
  {:else if !error}<p>Loading connection settings…</p>{/if}
  {#if status}<p role="status">{status}</p>{/if}
</section>

<style>
  .connections{grid-column:1/-1;background:var(--v7-surface);border:1px solid var(--v7-line);border-radius:var(--v7-radius-panel);padding:24px;min-width:0;color:var(--v7-ink);box-shadow:var(--v7-card-shadow, 0 8px 28px #203b3008);}.heading{display:flex;justify-content:space-between;gap:16px;align-items:center;flex-wrap:wrap}.eyebrow{font-size:var(--v7-text-xs);text-transform:uppercase;letter-spacing:.08em;color:var(--v7-accent);font-weight:700;}.badge{background:var(--v7-tint);border-radius:var(--v7-radius-panel);padding:8px 12px;font-size:var(--v7-text-sm)}.cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin:20px 0}article{padding:22px;border:1px solid var(--v7-line);border-radius:var(--v7-radius-panel);min-width:0;background:var(--v7-soft, var(--v7-tint));}h2,h3{margin:0 0 12px}p,li{line-height:1.6;color:var(--v7-muted);font-size:var(--v7-text-sm);}label{display:block;font-weight:600;margin:14px 0 8px}input,textarea{display:block;width:100%;box-sizing:border-box;margin-top:7px;padding:10px;border:1px solid var(--v7-control-line, var(--v7-control-line));border-radius:var(--v7-radius-panel);background:var(--v7-surface);font:13px monospace;color:inherit;min-height:44px;line-height:1.65;}button{cursor:pointer;padding:9px 13px;border:1px solid var(--v7-control-line, var(--v7-control-line));border-radius:var(--v7-radius-panel);background:var(--v7-surface);color:var(--v7-accent);min-height:44px;font-weight:650;}button:disabled{opacity:.5;cursor:default}code{overflow-wrap:anywhere}details{padding:16px 0;border-top:1px solid var(--v7-line)}summary{cursor:pointer;font-weight:600}[role=alert]{color:#a52424}@media(max-width:720px){.cards{grid-template-columns:1fr}.connections{padding:16px}}
  h2 { font-size:var(--v7-text-xl); letter-spacing:-.025em; }
    h3 { font-size:var(--v7-text-lg); }
    button:hover:not(:disabled) { background:var(--v7-soft, var(--v7-tint)); }
    :is(button,input,textarea,summary):focus-visible { outline:3px solid var(--v7-focus); outline-offset:3px; }
</style>
