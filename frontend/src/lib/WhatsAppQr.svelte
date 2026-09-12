<script lang="ts">
  import { onDestroy } from 'svelte';
  import { base } from '$app/paths';
  export let tenant: string;
  export let csrf: string;
  export let apiPrefix = '';
  let phone = '';
  let message = '';
  let busy = false;
  let error = '';
  let copied = '';
  let result: {link:string;image:string} | null = null;
  let controller: AbortController | undefined;
  onDestroy(() => controller?.abort());
  function clearResult() { result = null; copied = ''; error = ''; }
  async function generate() {
    if (busy) return;
    clearResult(); busy = true;
    controller = new AbortController();
    const timer = setTimeout(() => controller?.abort(), 16000);
    try {
      const response = await fetch(apiPrefix+'/admin/api/whatsapp-qr?tenant='+encodeURIComponent(tenant), {
        method:'POST', credentials:'same-origin', signal:controller.signal,
        headers:{'Content-Type':'application/json','X-CSRF-Token':csrf}, body:JSON.stringify({phone,message})
      });
      const data = await response.json();
      if (!response.ok) throw new Error(response.status === 401 ? 'Your session expired. Sign in again.' : response.status === 403 ? 'Access denied or your session needs refreshing. Reload this page and try again.' : data.error || 'Could not generate the QR code.');
      result = data;
    } catch (failure) {
      error = controller.signal.aborted ? 'Generation timed out. Try again.' : failure instanceof Error ? failure.message : 'Could not generate the QR code.';
    } finally { clearTimeout(timer); busy = false; }
  }
  async function copyLink() {
    if (!result) return;
    try { await navigator.clipboard.writeText(result.link); copied = 'WhatsApp link copied.'; }
    catch { copied = 'Select the link below and copy it manually.'; }
  }
</script>

<section class="qr-page" aria-label="WhatsApp QR creator">
  <article class="panel">
    <h2>Create your WhatsApp QR code</h2>
    <p>For {tenant}. Customers scan the code to open a chat with your business. Use the WhatsApp number you want customers to contact.</p>
    <form on:submit|preventDefault={generate}>
      <label>WhatsApp number<input type="tel" bind:value={phone} on:input={clearResult} placeholder="+44 7700 900123" autocomplete="tel" maxlength="40" required disabled={busy} /><small>Include the country code. For a UK mobile, replace the first 0 with +44.</small></label>
      <label>Suggested first message (optional)<textarea bind:value={message} on:input={clearResult} maxlength="160" rows="3" placeholder="Hi, I would like to find out more." disabled={busy}></textarea><small>Customers can edit this message before sending. {message.length}/160 characters.</small></label>
      <button type="submit" disabled={busy}>{busy ? 'Creating…' : 'Create QR code'}</button>
    </form>
    {#if error}<p class="error" role="alert">{error}</p>{/if}
  </article>
  {#if result}
    <article class="panel result" aria-label="Generated WhatsApp QR code">
      <h2>Ready to download</h2>
      <img src={result.image} alt={'QR code opening WhatsApp for '+phone} width="320" height="320" />
      <div class="actions"><a class="button" href={result.image} download={`${tenant}-whatsapp-qr.svg`}>Download QR (SVG)</a><button class="secondary" on:click={copyLink}>Copy WhatsApp link</button></div>
      <label>WhatsApp destination<input readonly value={result.link} /></label>
      {#if copied}<p role="status">{copied}</p>{/if}
      <p>Scan it with your phone and confirm the correct business opens before printing or sharing. Keep the white border when placing it on a website, poster or business card.</p>
      <p class="hint">The SVG stays sharp when resized. The code contains this number and message directly and has no expiry or scan tracking. Changing the number requires a new code.</p>
    </article>
  {/if}
  <article class="panel">
    <h2>Connecting the agent</h2>
    <p>This creates a WhatsApp link; it does not register the number or enable automatic replies. To let the agent reply, connect that same business number through Meta or Twilio and map it to this company.</p>
    <div class="actions"><a href={'/admin/integrations?tenant='+encodeURIComponent(tenant)}>WhatsApp setup &amp; status</a><a href={base+'/implementation'}>Implementation guide</a></div>
    <p class="hint">The number must have an active WhatsApp account. We generate the QR on this server without sending your number or message to an external QR service. Creating a code does not change your integration settings.</p>
  </article>
</section>

<style>
  .qr-page {display:grid;gap:20px;min-width:0;overflow-wrap:anywhere}
  .panel {padding:24px;background:#fff;border:1px solid #d9ddd7;border-radius:8px;min-width:0}
  h2 {margin:0;font-size:20px} p {color:#526359;line-height:1.6}
  form,label {display:grid;gap:8px} form {gap:20px} label {font-size:14px;font-weight:600;min-width:0}
  input,textarea {box-sizing:border-box;width:100%;min-width:0;padding:12px;border:1px solid #bbc4bc;border-radius:6px;font:inherit;color:#26332b;background:#fff}
  textarea {resize:vertical} small,.hint {font-size:13px;font-weight:400;color:#526359;line-height:1.5}
  button,.button {display:inline-block;justify-self:start;min-height:44px;box-sizing:border-box;padding:12px 16px;border:1px solid #007d70;border-radius:6px;background:#007d70;color:white;font:600 14px system-ui;cursor:pointer;text-decoration:none}
  button:disabled {opacity:.6;cursor:wait} .secondary {background:white;color:#007d70} a {color:#007d70}
  .actions {display:flex;flex-wrap:wrap;align-items:center;gap:16px;margin:16px 0}
  .result img {display:block;width:min(320px,100%);height:auto;margin:20px auto;background:white}
  .error {color:#a12622} :is(button,a,input,textarea):focus-visible {outline:3px solid #8bcdc0;outline-offset:3px}
  @media(max-width:600px) {.panel{padding:16px}}
</style>
