<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { t } from './i18n';
  export let csrf: string;
  export let apiPrefix = '';
  let email = '', currentEmail = '', currentPassword = '', code = '';
  let stage: 'request' | 'verify' | 'done' = 'request';
  let loading = true, available = false, busy = false, error = '', notice = '';
  let controller: AbortController | null = null;
  let disposed = false;
  const known = new Set(['Enter a valid email address.', 'Enter a different email address.',
    'Current password was not accepted.', 'Email changes are unavailable. Contact the platform operator.',
    'This email cannot be used for this account. Choose another address.',
    'This account cannot change its email here. Contact the platform operator.',
    'Your account changed. Sign in again.', 'Please wait before requesting another email change code.',
    'Verification email could not be sent. Try again later.',
    'Email change code is invalid, expired or already used. Start again.',
    'Your session expired. Sign in again.', 'Too many attempts. Please wait and try again.']);
  async function request(path: string, body?: Record<string,string>) {
    controller = new AbortController();
    const response = await fetch(apiPrefix + path, {method:body?'POST':'GET', credentials:'same-origin', signal:controller.signal,
      headers:{Accept:'application/json', ...(body ? {'Content-Type':'application/json','X-CSRF-Token':csrf} : {})},
      ...(body ? {body:JSON.stringify(body)} : {})});
    const data: unknown = await response.json();
    if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('The request could not be completed. Please try again.');
    const result = data as Record<string,unknown>;
    if (!response.ok) throw new Error(response.status===401 ? 'Your session expired. Sign in again.' : response.status===429 ? 'Too many attempts. Please wait and try again.' :
      typeof result.error==='string' && known.has(result.error) ? result.error : 'The request could not be completed. Please try again.');
    return result;
  }
  async function submit() {
    if (busy || disposed) return;
    busy = true; error = notice = '';
    try {
      if (stage === 'request') {
        await request('/auth/account/email', {email,current_password:currentPassword});
        if (disposed) return;
        currentPassword = '';
        stage = 'verify'; notice = 'A verification code was sent to your new email. It expires in 10 minutes.';
      } else {
        await request('/auth/account/email/confirm', {code});
        if (disposed) return;
        code = currentPassword = '';
        stage = 'done'; notice = 'Email updated. Sign in again with your new email, existing password and authenticator.';
      }
    } catch (failure) {
      if (!disposed) error = failure instanceof Error && known.has(failure.message) ? failure.message : 'The request could not be completed. Please try again.';
    } finally { if (!disposed) busy = false; }
  }
  onMount(async () => {
    try {
      const data = await request('/auth/account');
      if (disposed) return;
      available = data.password_change_available === true;
      currentEmail = typeof data.email === 'string' ? data.email : '';
    } catch { if (!disposed) error = 'Account security details could not be loaded.'; }
    finally { if (!disposed) loading = false; }
  });
  onDestroy(() => { disposed = true; controller?.abort(); currentPassword = code = ''; });
</script>

<section class="email-card" aria-labelledby="email-heading">
  <h3 id="email-heading">{$t('Change account email')}</h3>
  <p>{$t('Verify your new address before it becomes your sign-in email. Your password, authenticator and access stay the same; existing sessions and trusted devices are signed out.')}</p>
  {#if currentEmail}<p class="identity"><span>{$t('Current sign-in')}</span> <bdi>{currentEmail}</bdi></p>{/if}
  {#if loading}<p role="status">{$t('Loading…')}</p>
  {:else if stage === 'done'}<button type="button" on:click={() => window.location.reload()}>{$t('Back to sign in')}</button>
  {:else if !available}<p>{$t('This account cannot change its email here. Contact the platform operator.')}</p>
  {:else}
    <form aria-busy={busy} on:submit|preventDefault={submit}>
      {#if stage === 'request'}
        <label>{$t('New email address')}<input type="email" dir="ltr" bind:value={email} required maxlength="254" autocomplete="email" disabled={busy}/></label>
        <label>{$t('Current password')}<input type="password" bind:value={currentPassword} required maxlength="1024" autocomplete="current-password" disabled={busy}/></label>
      {:else}
        <p>{$t('Verify this address')}: <bdi>{email}</bdi></p>
        <label>{$t('Verification code')}<input bind:value={code} dir="ltr" required maxlength="6" pattern="[0-9]{6}" inputmode="numeric" autocomplete="one-time-code" disabled={busy}/></label>
      {/if}
      <button type="submit" disabled={busy}>{$t(busy ? 'Please wait…' : stage === 'request' ? 'Send email verification code' : 'Confirm email change')}</button>
      {#if stage === 'verify'}<button type="button" class="secondary" disabled={busy} on:click={() => {stage='request';code=currentPassword='';notice=error='';}}>{$t('Start again')}</button>{/if}
    </form>
  {/if}
  {#if notice}<p class="notice" role="status">{$t(notice)}</p>{/if}
  {#if error}<p class="error" role="alert">{$t(error)}</p>{/if}
</section>

<style>
  .email-card{padding:24px;background:#fff;border:1px solid var(--v7-line,#dce4df);border-radius:18px;max-width:640px;color:var(--v7-ink,#25372e)}h3{margin:0 0 12px;font-size:20px;letter-spacing:-.03em}p{font-size:14px;line-height:1.65;color:var(--v7-muted,#59675f)}form{display:grid;gap:16px;margin-top:20px}label{display:grid;gap:7px;font-size:14px;font-weight:600}input{box-sizing:border-box;width:100%;min-height:44px;border:1px solid #b5c5bc;border-radius:10px;padding:12px;font:inherit;background:#fff;color:inherit}button{min-height:44px;padding:12px 18px;border:1px solid var(--v7-accent,#087e5f);border-radius:10px;background:var(--v7-accent,#087e5f);color:#fff;font:inherit;font-weight:600;cursor:pointer}.secondary{background:#fff;color:inherit;border-color:#b5c5bc}button:disabled{opacity:.5;cursor:wait}button:focus-visible,input:focus-visible{outline:3px solid var(--v7-focus,#6ec5a9);outline-offset:3px}.identity{display:grid;gap:5px;overflow-wrap:anywhere}.notice{background:#eef9f3;padding:14px;border-radius:10px}.error{color:#a13728;background:#fff5f3;padding:14px;border-radius:10px}@media(max-width:640px){.email-card{padding:20px}}
</style>
