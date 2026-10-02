<script lang="ts">
  import { onMount } from 'svelte';
  import { language, t } from './i18n';

  export let tenant: string;
  export let csrf: string;
  export let apiPrefix = '';

  type Provider = { id: 'google' | 'microsoft'; name: string; configured: boolean; linked: boolean; has_links: boolean };
  type Device = { expires_utc: string; current: boolean };
  let providers: Provider[] = [];
  let devices: Device[] = [];
  let count = 0;
  let loading = true;
  let loaded = false;
  let busy = '';
  let error = '';
  let notice = '';

  class UiError extends Error {}
  const object = (value: unknown): Record<string, unknown> | null =>
    value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null;

  function safeError(status: number, code: unknown): string {
    if (status === 401 || code === 'account_changed') return 'Your session expired. Sign in again.';
    if (status === 403) return 'This action could not be authorized. Reload this page and try again.';
    if (status === 429) return 'Too many attempts. Please wait and try again.';
    if (code === 'provider_not_configured') return 'This sign-in provider is not configured. Contact the platform operator.';
    if (code === 'provider_already_linked') return 'This provider account is already connected to an account.';
    if (code === 'unknown_tenant' || code === 'invalid_tenant') return 'Choose an available company before connecting a provider.';
    return 'The request could not be completed. Please try again.';
  }

  async function request(path: string, method = 'GET', body?: Record<string, unknown>): Promise<unknown> {
    const response = await fetch(apiPrefix + path, {
      method, credentials: 'same-origin',
      headers: { 'Accept': 'application/json', ...(method !== 'GET' ? { 'X-CSRF-Token': csrf } : {}),
        ...(body ? { 'Content-Type': 'application/json' } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {})
    });
    let data: unknown;
    try { data = await response.json(); }
    catch { throw new UiError(safeError(response.status, null)); }
    if (!response.ok) throw new UiError(safeError(response.status, object(data)?.error));
    return data;
  }

  function providerList(value: unknown): Provider[] {
    const rows = object(value)?.providers;
    if (!Array.isArray(rows)) throw new UiError('Account security details could not be loaded.');
    return rows.map(row => {
      const item = object(row);
      if (!item || (item.id !== 'google' && item.id !== 'microsoft') || typeof item.name !== 'string'
        || typeof item.configured !== 'boolean' || typeof item.linked !== 'boolean') {
        throw new UiError('Account security details could not be loaded.');
      }
      return { id: item.id, name: item.name, configured: item.configured, linked: item.linked,
        has_links: typeof item.has_links === 'boolean' ? item.has_links : item.linked };
    });
  }

  function deviceList(value: unknown): { count: number; rows: Device[] } {
    const payload = object(value);
    if (!payload || typeof payload.count !== 'number' || !Number.isSafeInteger(payload.count)
      || payload.count < 0 || !Array.isArray(payload.devices)) throw new UiError('Account security details could not be loaded.');
    const rows = payload.devices.map(row => {
      const item = object(row);
      if (!item || typeof item.expires_utc !== 'string' || !Number.isFinite(Date.parse(item.expires_utc))
        || typeof item.current !== 'boolean') throw new UiError('Account security details could not be loaded.');
      return { expires_utc: item.expires_utc, current: item.current };
    });
    return { count: payload.count, rows };
  }

  async function refresh() {
    loading = true;
    error = '';
    try {
      const [providerData, deviceData] = await Promise.all([
        request('/auth/oidc/providers'), request('/auth/devices')
      ]);
      const parsedProviders = providerList(providerData);
      const parsedDevices = deviceList(deviceData);
      providers = parsedProviders;
      devices = parsedDevices.rows;
      count = parsedDevices.count;
      loaded = true;
    } catch (failure) {
      error = failure instanceof UiError ? failure.message : 'Account security details could not be loaded.';
    } finally { loading = false; }
  }

  async function connect(provider: Provider) {
    if (busy || loading) return;
    busy = provider.id;
    error = notice = '';
    try {
      const data = object(await request('/auth/oidc/' + provider.id + '/start', 'POST', { intent: 'link', tenant }));
      if (!data || typeof data.authorization_url !== 'string') throw new UiError('The request could not be completed. Please try again.');
      const url = new URL(data.authorization_url);
      const expected = provider.id === 'google' ? 'accounts.google.com' : 'login.microsoftonline.com';
      if (url.protocol !== 'https:' || url.hostname !== expected || url.username || url.password) {
        throw new UiError('The request could not be completed. Please try again.');
      }
      window.location.assign(url.href);
    } catch (failure) {
      error = failure instanceof UiError ? failure.message : 'The request could not be completed. Please try again.';
      busy = '';
    }
  }

  async function disconnect(provider: Provider) {
    if (busy || loading) return;
    busy = provider.id;
    error = notice = '';
    try {
      await request('/auth/oidc/' + provider.id + '/link', 'DELETE');
      providers = providers.map(item => item.id === provider.id ? { ...item, linked: false, has_links: false } : item);
      notice = 'Sign-in provider disconnected.';
      await refresh();
    } catch (failure) {
      error = failure instanceof UiError ? failure.message : 'The request could not be completed. Please try again.';
    } finally { busy = ''; }
  }

  async function revokeDevices() {
    if (busy || loading) return;
    busy = 'devices';
    error = notice = '';
    try {
      await request('/auth/devices', 'DELETE');
      devices = [];
      count = 0;
      notice = 'All trusted devices revoked. Your next sign-in will require your authenticator.';
      await refresh();
    } catch (failure) {
      error = failure instanceof UiError ? failure.message : 'The request could not be completed. Please try again.';
    } finally { busy = ''; }
  }

  const expiry = (value: string) => new Date(value).toLocaleString($language, { dateStyle: 'medium', timeStyle: 'short' });
  onMount(() => { void refresh(); });
</script>

<div class="account-security">
  <header class="security-heading">
    <p class="eyebrow">{$t('Account & security')}</p>
    <h2>{$t('Account security')}</h2>
    <p>{$t('Manage how you sign in and which devices you trust.')}</p>
  </header>

  {#if error}<p class="message error" role="alert">{$t(error)}</p>{/if}
  {#if notice}<p class="message success" role="status">{$t(notice)}</p>{/if}
  {#if loading}
    <p class="loading" role="status">{$t('Loading…')}</p>
  {:else if !loaded}
    <button type="button" class="secondary retry" disabled={Boolean(busy)} on:click={refresh}>{$t('Try again')}</button>
  {:else}
    <section class="security-card" aria-labelledby="provider-heading">
      <div class="card-heading"><h3 id="provider-heading">{$t('Linked sign-in providers')}</h3>
        <p>{$t('Connect a provider while signed in to use it with this same V7 account.')}</p></div>
      <div class="provider-list">
        {#each providers as provider (provider.id)}
          <div class="provider-row">
            <span class="provider-mark" aria-hidden="true">{provider.name.slice(0, 1)}</span>
            <div class="provider-copy"><strong>{provider.name}</strong>
              <span>{$t(provider.linked ? 'Connected' : provider.has_links ? 'Previous connection saved' : provider.configured ? 'Not connected' : 'Not configured')}</span></div>
            <div class="provider-actions">
              {#if provider.has_links}
                <button type="button" class="secondary" aria-label={$t('Disconnect')+' '+provider.name} disabled={Boolean(busy)} on:click={() => disconnect(provider)}>
                  {$t(busy === provider.id ? 'Please wait…' : 'Disconnect')}
                </button>
              {/if}
              {#if !provider.linked}
                <button type="button" aria-label={$t('Connect')+' '+provider.name} disabled={!provider.configured || Boolean(busy)} on:click={() => connect(provider)}>
                  {$t(busy === provider.id ? 'Please wait…' : 'Connect')}
                </button>
              {/if}
            </div>
          </div>
        {/each}
      </div>
      <p class="note">{$t('A connected provider does not change your company or access permissions.')}</p>
    </section>

    <section class="security-card" aria-labelledby="device-heading">
      <div class="card-heading"><h3 id="device-heading">{$t('Trusted devices')}</h3>
        <p>{$t('Choose trust this device after authenticator verification on a personal device.')}</p></div>
      <p class="trust-explanation">{$t('Trust lasts 30 days from verification. Using it does not extend that date. Password sign-in still requires your password.')}</p>
      <div class="device-summary"><strong>{count}</strong><span>{$t('Trusted devices')}</span></div>
      {#if devices.length}
        <ul class="device-list">
          {#each devices as device}
            <li><span>{$t(device.current ? 'This device' : 'Other device')}</span>
              <span>{$t('Expires')} <time datetime={device.expires_utc}>{expiry(device.expires_utc)}</time></span></li>
          {/each}
        </ul>
      {:else}<p class="empty">{$t('No trusted devices. Authenticator verification is required at sign-in.')}</p>{/if}
      <div class="device-footer"><button type="button" class="secondary" disabled={count === 0 || Boolean(busy)} on:click={revokeDevices}>
        {$t(busy === 'devices' ? 'Please wait…' : 'Forget all trusted devices')}</button>
        <p class="note">{$t('Revocation applies to future sign-ins. Existing signed-in sessions continue until they expire or you sign out.')}</p></div>
    </section>
    {#if error}<button type="button" class="secondary retry" disabled={Boolean(busy)} on:click={refresh}>{$t('Try again')}</button>{/if}
  {/if}
</div>

<style>
  .account-security {display:grid;gap:20px;max-width:960px;color:#17243b}
  .security-heading h2 {margin:4px 0 8px;font-size:28px;letter-spacing:-.035em}
  .security-heading p,.card-heading p {margin:0;color:#607089;line-height:1.65;font-size:14px}
  .security-heading .eyebrow {color:#23785d;text-transform:uppercase;font-size:11px;font-weight:800;letter-spacing:.14em}
  .security-card {padding:24px;background:#fff;border:1px solid #dce4ef;border-radius:18px;box-shadow:0 4px 18px #17243b05}
  .card-heading h3 {margin:0 0 7px;font-size:18px;letter-spacing:-.02em}
  .provider-list {margin-top:20px}
  .provider-row {display:flex;align-items:center;gap:14px;padding:17px 0;border-top:1px solid #e8edf4}
  .provider-mark {display:grid;place-items:center;flex-shrink:0;width:42px;height:42px;background:#f1f4ef;border:1px solid #dce4ef;border-radius:12px;font-size:19px;font-weight:800}
  .provider-copy {display:grid;gap:5px;flex:1;font-size:14px}
  .provider-copy span,.note,.empty,.loading {color:#607089;font-size:12px;line-height:1.7}
  .provider-actions {display:flex;gap:9px;flex-wrap:wrap}
  button {min-height:40px;padding:10px 16px;background:#173d31;color:#fff;border:1px solid #173d31;border-radius:10px;font:inherit;font-size:12px;font-weight:700;cursor:pointer}
  button.secondary {background:#fff;color:#263853;border-color:#cbd5e3}
  button:hover:not(:disabled) {filter:brightness(.94)}
  button:disabled {opacity:.45;cursor:not-allowed}
  button:focus-visible {outline:3px solid #8bcdc0;outline-offset:3px}
  .note {margin:14px 0 0}
  .trust-explanation {margin:18px 0;color:#4b5e78;font-size:13px;line-height:1.75}
  .device-summary {display:flex;align-items:center;gap:14px;padding:16px 18px;background:#f7faf7;border:1px solid #e5ebf4;border-radius:12px}
  .device-summary strong {font-size:29px;line-height:1;color:#173d31}
  .device-summary span {font-size:13px;font-weight:600}
  .device-list {list-style:none;padding:0;margin:15px 0 20px}
  .device-list li {display:flex;justify-content:space-between;gap:14px;padding:12px 0;border-bottom:1px solid #edf0f5;font-size:12px}
  .device-list li span:last-child {color:#607089}
  .device-footer {display:flex;align-items:center;gap:18px;margin-top:18px}
  .device-footer .note {margin:0;max-width:510px}
  .message {margin:0;padding:14px 17px;border:1px solid;border-radius:12px;font-size:13px;line-height:1.65}
  .message.error {background:#fff5f3;border-color:#ffd6cc;color:#a13728}
  .message.success {background:#eef9f3;border-color:#cce8d7;color:#236742}
  .retry {justify-self:start}
  @media(max-width:640px) {.security-card {padding:20px}.provider-row {flex-wrap:wrap}.provider-actions {width:100%;padding-inline-start:56px}.device-footer {align-items:flex-start;flex-direction:column}.device-list li {flex-direction:column;gap:5px}.security-heading h2 {font-size:24px}}
</style>
