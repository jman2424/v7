<script lang="ts">
  import { onMount, onDestroy, createEventDispatcher } from 'svelte';
  import { t } from './i18n';
  export let csrf: string;
  export let tenant = '';
  export let email = '';
  export let apiPrefix = '';
  export let recovery = false;
  const dispatch = createEventDispatcher<{ done: void }>();
  let currentPassword = '', password = '', confirmation = '', code = '';
  let stage: 'request' | 'confirm' | 'done' = 'request';
  let busy = false, loading = !recovery, available = recovery, error = '', notice = '';
  let controller: AbortController | null = null;
  const messages = new Set([
    'Use a password between 12 and 256 characters.', 'Current password was not accepted.',
    'Reset code is invalid, expired or already used. Request a new code.',
    'Please wait before requesting another reset code.', 'Enter a valid email address.',
    'Enter your company key and account email.',
    'Password reset email is unavailable. Contact the platform operator.'
  ]);
  async function request(path: string, body?: Record<string, string>) {
    controller = new AbortController();
    const response = await fetch(apiPrefix + path, { method: body ? 'POST' : 'GET', credentials: 'same-origin',
      signal: controller.signal, headers: { Accept: 'application/json', ...(body ? { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {}) });
    const data: unknown = await response.json();
    if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('The request could not be completed. Please try again.');
    const result = data as Record<string, unknown>;
    if (!response.ok) {
      const message = response.status === 429 ? 'Too many attempts. Please wait and try again.' :
        response.status === 401 ? 'Your session expired. Sign in again.' :
        typeof result.error === 'string' && messages.has(result.error) ? result.error : 'The request could not be completed. Please try again.';
      throw new Error(message);
    }
    return result;
  }
  async function submit() {
    if (busy) return;
    error = notice = '';
    if ((!recovery || stage === 'confirm') && password !== confirmation) { error = 'Passwords do not match.'; return; }
    busy = true;
    try {
      if (recovery && stage === 'request') {
        await request('/auth/password/reset', { email, tenant });
        currentPassword = password = confirmation = code = '';
        stage = 'confirm';
        notice = 'If an eligible account matches, a reset code has been sent. Check your email.';
      } else {
        await request(recovery ? '/auth/password/reset/confirm' : '/auth/password/change',
          recovery ? { code, password } : { current_password: currentPassword, password });
        currentPassword = password = confirmation = code = '';
        stage = 'done';
        notice = 'Password updated. Sign in again with your new password and authenticator.';
      }
    } catch (failure) { error = failure instanceof Error && (messages.has(failure.message) || ['Too many attempts. Please wait and try again.', 'Your session expired. Sign in again.'].includes(failure.message)) ? failure.message : 'The request could not be completed. Please try again.'; }
    finally { busy = false; }
  }
  onMount(async () => {
    if (recovery) return;
    try {
      const data = await request('/auth/account');
      available = data.password_change_available === true;
      email = typeof data.email === 'string' ? data.email : '';
    } catch { error = 'Account security details could not be loaded.'; }
    finally { loading = false; }
  });
  onDestroy(() => { controller?.abort(); currentPassword = password = confirmation = code = ''; });
</script>

<section class="password-card" aria-labelledby="password-heading">
  <h2 id="password-heading">{$t(recovery ? 'Reset password' : 'Manage password & accounts')}</h2>
  <p>{$t('Changing your password signs out existing sessions and removes trusted devices. Your authenticator stays enabled.')}</p>
  {#if email && !recovery}<p class="identity">{email}</p>{/if}
  {#if loading}<p role="status">{$t('Loading…')}</p>
  {:else if stage === 'done'}<button type="button" on:click={() => recovery ? dispatch('done') : window.location.reload()}>{$t('Back to sign in')}</button>
  {:else if !available}<p>{$t('This account is configured by the platform operator. Contact them to change its password.')}</p>
  {:else}
    <form on:submit|preventDefault={submit} aria-busy={busy}>
      {#if recovery && stage === 'request'}
        <label>{$t('Company key')}<input bind:value={tenant} required maxlength="64" autocomplete="organization" disabled={busy}/></label>
        <label>{$t('Email')}<input type="email" bind:value={email} required maxlength="254" autocomplete="username" disabled={busy}/></label>
        <p>{$t('Use your account email. For a username-only account, ask the platform operator for help.')}</p>
      {:else}
        {#if recovery}<label>{$t('Verification code')}<input bind:value={code} required maxlength="6" pattern={'[0-9]{6}'} inputmode="numeric" autocomplete="one-time-code" disabled={busy}/></label>
        {:else}<label>{$t('Current password')}<input type="password" bind:value={currentPassword} required maxlength="1024" autocomplete="current-password" disabled={busy}/></label>{/if}
        <label>{$t('New password')}<input type="password" bind:value={password} required minlength="12" maxlength="256" autocomplete="new-password" disabled={busy}/></label>
        <label>{$t('Confirm new password')}<input type="password" bind:value={confirmation} required minlength="12" maxlength="256" autocomplete="new-password" disabled={busy}/></label>
        <p>{$t('Use a password between 12 and 256 characters.')}</p>
      {/if}
      <button type="submit" disabled={busy}>{$t(busy ? 'Please wait…' : recovery && stage === 'request' ? 'Send reset code' : recovery ? 'Reset password' : 'Change password')}</button>
      {#if recovery && stage === 'confirm'}<button type="button" class="secondary" disabled={busy} on:click={() => {stage = 'request'; code = password = confirmation = ''; notice = error = '';}}>{$t('Request a new code')}</button>{/if}
    </form>
  {/if}
  {#if notice}<p class="notice" role="status">{$t(notice)}</p>{/if}
  {#if error}<p class="error" role="alert">{$t(error)}</p>{/if}
</section>

<style>
  .password-card{background:#fff;border:1px solid var(--v7-line,#dce4df);border-radius:18px;padding:24px;max-width:640px;color:var(--v7-ink,#25372e)}
  h2{font-size:22px;margin:0 0 12px;letter-spacing:-.03em}p{font-size:14px;line-height:1.65;color:var(--v7-muted,#59675f)}
  form{display:grid;gap:16px;margin-top:20px}label{display:grid;gap:7px;font-size:14px;font-weight:600}input{box-sizing:border-box;width:100%;min-height:44px;border:1px solid #b5c5bc;border-radius:10px;padding:12px;font:inherit;background:#fff;color:inherit}
  button{min-height:44px;padding:12px 18px;background:var(--v7-accent,#087e5f);color:#fff;border:1px solid var(--v7-accent,#087e5f);border-radius:10px;font:inherit;font-weight:600;cursor:pointer}.secondary{background:#fff;color:inherit;border-color:#b5c5bc}
  button:disabled{opacity:.5;cursor:wait}input:focus-visible,button:focus-visible{outline:3px solid var(--v7-focus,#6ec5a9);outline-offset:3px}.identity{overflow-wrap:anywhere;font-weight:600}.notice{background:#eef9f3;padding:14px;border-radius:10px}.error{color:#a13728;background:#fff5f3;padding:14px;border-radius:10px}
  @media(max-width:640px){.password-card{padding:20px}}
</style>
