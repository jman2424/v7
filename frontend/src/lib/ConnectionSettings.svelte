<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  export let csrf: string;
  export let apiPrefix = '';
  type Settings = {configured:boolean;owner_access:boolean;clients:string[];connected_clients:string[];mcp_url:string;api_url:string;authorization_url:string;token_url:string};
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
      if (!response.ok) throw new Error('Could not load connections. Refresh or sign in again.');
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
  $: example = settings?.api_url ? `curl "${settings.api_url}/statistics" -H "Authorization: Bearer YOUR_ACCESS_TOKEN"` : '';
</script>

<section class="connections" aria-label="MCP and REST API connections">
  {#if error}<p role="alert">{error}</p><button type="button" on:click={load}>Retry</button>{/if}
  {#if settings}
    <div class="heading"><div><p class="eyebrow">Apps and developers</p><h2>MCP &amp; API connections</h2></div><span class="badge">{settings.configured ? 'Ready for OAuth connections' : 'Awaiting server setup'}</span></div>
    {#if !settings.configured}<p>The platform operator needs to configure the public HTTPS address and register an OAuth client with its exact callback URL before connections can be authorized.</p>{/if}
    {#if !settings.owner_access}<p>Connections must be authorized from a business owner account. This account can view setup information only.</p>{/if}
    <div class="cards">
      <article><h3>MCP connection</h3><p>Connect an MCP-compatible app to your business stats, catalogue, offers, roles, health and errors.</p>
        <label>Server URL<input readonly value={settings.mcp_url} placeholder="Available after server setup" /></label><button type="button" disabled={!settings.mcp_url} on:click={()=>copy(settings!.mcp_url)}>Copy MCP URL</button>
        <ol><li>Add a remote MCP server in your app and paste this URL.</li><li>Choose OAuth and use a registered client ID below. Ask the operator to register your app’s exact callback URL if needed.</li><li>Sign in through the console as the business owner, then approve read access and optional write access.</li></ol>
      </article>
      <article><h3>REST API connection</h3><p>Use the same OAuth connection for authenticated HTTP requests.</p>
        <label>API base URL<input readonly value={settings.api_url} placeholder="Available after server setup" /></label><button type="button" disabled={!settings.api_url} on:click={()=>copy(settings!.api_url)}>Copy API URL</button>
        <p>Use the authorization-code flow with S256 PKCE. Set the resource to the MCP server URL. Send the resulting access token in the Authorization header.</p>
        <label>Example request<textarea readonly value={example} rows="3"></textarea></label><button type="button" disabled={!example} on:click={()=>copy(example)}>Copy example</button>
        <p>GET endpoints: <code>/statistics</code>, <code>/catalog</code>, <code>/offers</code>, <code>/roles</code>, <code>/health</code>, <code>/errors</code>. Catalog and offer writes require <code>business:write</code> and the latest document revision.</p>
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
      {#if confirmRevoke}<p>Revoke all your MCP and API connections?</p><button type="button" disabled={busy} on:click={revoke}>{busy ? 'Revoking…' : 'Confirm revocation'}</button> <button type="button" disabled={busy} on:click={()=>confirmRevoke=false}>Cancel</button>
      {:else}<button type="button" on:click={()=>confirmRevoke=true}>Revoke my connections</button>{/if}
    {/if}
  {:else if !error}<p>Loading connection settings…</p>{/if}
  {#if status}<p role="status">{status}</p>{/if}
</section>

<style>
  .connections{grid-column:1/-1;background:white;border:1px solid #dde3e9;border-radius:16px;padding:24px;min-width:0;color:#243449}.heading{display:flex;justify-content:space-between;gap:16px;align-items:center;flex-wrap:wrap}.eyebrow{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:#61738a}.badge{background:#edf3fa;border-radius:20px;padding:8px 12px;font-size:13px}.cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px;margin:20px 0}article{padding:20px;border:1px solid #dde3e9;border-radius:12px;min-width:0}h2,h3{margin:0 0 12px}p,li{line-height:1.6}label{display:block;font-weight:600;margin:14px 0 8px}input,textarea{display:block;width:100%;box-sizing:border-box;margin-top:7px;padding:10px;border:1px solid #cbd5e1;border-radius:7px;background:#f7f9fc;font:13px monospace;color:inherit}button{cursor:pointer;padding:9px 13px;border:1px solid #bdcbd9;border-radius:8px;background:white;color:#203d64}button:disabled{opacity:.5;cursor:default}code{overflow-wrap:anywhere}details{padding:16px 0;border-top:1px solid #dde3e9}summary{cursor:pointer;font-weight:600}[role=alert]{color:#a52424}@media(max-width:720px){.cards{grid-template-columns:1fr}.connections{padding:16px}}
</style>
