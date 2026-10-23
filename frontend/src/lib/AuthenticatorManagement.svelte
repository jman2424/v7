<script lang="ts">
  import { onDestroy } from 'svelte';
  import { t } from './i18n';
  export let csrf: string;
  export let apiPrefix = '';
  let open = false, busy = false, disposed = false;
  let password = '', code = '', setupKey = '', qrImage = '', error = '';
  let controller: AbortController | null = null;
  let expiry: ReturnType<typeof setTimeout> | undefined;

  function close() {
    controller?.abort(); controller = null;
    clearTimeout(expiry);
    open = busy = false;
    password = code = setupKey = qrImage = error = '';
  }
  async function reveal() {
    if (busy || disposed || !open) return;
    busy = true; error = '';
    const pending = new AbortController(); controller = pending;
    try {
      const response = await fetch(apiPrefix + '/auth/mfa/add-device', {
        method: 'POST', credentials: 'same-origin', cache: 'no-store', signal: pending.signal,
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json', 'X-CSRF-Token': csrf },
        body: JSON.stringify({ current_password: password, code })
      });
      const data: unknown = await response.json();
      if (disposed || pending.signal.aborted || controller !== pending) return;
      if (!response.ok) throw new Error(response.status === 429 ? 'Too many attempts. Please wait and try again.' :
        response.status === 403 ? 'Reload the page and try again.' : 'Password or authenticator code was not accepted. Wait for a fresh code and try again.');
      if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('The request could not be completed. Please try again.');
      const result = data as Record<string, unknown>;
      if (typeof result.setup_key !== 'string' || !/^[A-Z2-7]{16,128}$/.test(result.setup_key)
        || typeof result.qr_image !== 'string' || !result.qr_image.startsWith('data:image/svg+xml;base64,')) {
        throw new Error('The request could not be completed. Please try again.');
      }
      setupKey = result.setup_key; qrImage = result.qr_image;
      expiry = setTimeout(close, 120000);
    } catch (failure) {
      if (!disposed && !pending.signal.aborted) error = failure instanceof Error ? failure.message : 'The request could not be completed. Please try again.';
    } finally {
      if (controller === pending) { password = code = ''; busy = false; controller = null; }
    }
  }
  onDestroy(() => { disposed = true; close(); });
</script>

<section class="authenticator-card" aria-labelledby="authenticator-heading">
  <h3 id="authenticator-heading">{$t('Two-factor authentication')}</h3>
  <p>{$t('Add another phone to the same account without replacing your current authenticator.')}</p>
  <p>{$t('Both phones generate the same codes. A code can only be used once; wait for a fresh code after signing in. Keep setup details private.')}</p>
  {#if !open}
    <button type="button" on:click={() => { open = true; }}>{$t('Add another authenticator')}</button>
  {:else if setupKey}
    <p role="status">{$t('Scan this QR code on your other phone, or enter the setup key manually. It hides after two minutes.')}</p>
    <img class="qr" src={qrImage} alt={$t('Authenticator setup QR code')} />
    <p><strong>{$t('Setup key')}</strong></p><code>{setupKey}</code>
    <p>{$t('Your existing phone keeps working. Use a fresh code from either phone at your next sign-in. This does not create a separate team login.')}</p>
    <button type="button" on:click={close}>{$t('Done — hide setup details')}</button>
  {:else}
    <form on:submit|preventDefault={reveal}>
      <label>{$t('Current password')}<input type="password" autocomplete="current-password" bind:value={password} required maxlength="256" disabled={busy}/></label>
      <label>{$t('Code from your current authenticator')}<input type="text" inputmode="numeric" autocomplete="one-time-code" bind:value={code} required pattern="[0-9]{6}" maxlength="6" disabled={busy}/></label>
      <div class="actions"><button type="submit" disabled={busy}>{$t(busy ? 'Please wait…' : 'Verify and show setup')}</button>
        <button type="button" class="secondary" on:click={close}>{$t('Cancel')}</button></div>
    </form>
  {/if}
  {#if error}<p role="alert">{$t(error)}</p>{/if}
  <p class="note">{$t('Lost access to your authenticator? Contact the platform operator for identity-verified recovery. Password resets do not bypass two-factor authentication.')}</p>
</section>

<style>
  .authenticator-card {padding:24px;background:#fff;border:1px solid var(--v7-line);border-radius:18px;line-height:1.65}
  h3 {margin:0 0 10px;font-size:18px} p {font-size:14px;color:var(--v7-muted)}
  form,label {display:grid;gap:10px} form {max-width:440px;gap:18px}
  label {font-size:14px;font-weight:600} input {min-height:44px;padding:9px;border:1px solid var(--v7-line);border-radius:8px;font:inherit}
  .actions {display:flex;flex-wrap:wrap;gap:12px}
  button {padding:11px 17px;border:1px solid var(--v7-accent);border-radius:9px;background:var(--v7-accent);color:#fff;font:inherit;cursor:pointer}
  button.secondary {background:#fff;color:var(--v7-ink)} button:disabled {opacity:.6;cursor:wait}
  .qr {display:block;width:220px;max-width:100%;height:auto;background:#fff}
  code {display:block;overflow-wrap:anywhere;font-size:16px;padding:12px;background:var(--v7-tint);border-radius:8px}
  .note {font-size:12px;margin-bottom:0} [role=alert] {color:#a51825}
</style>
