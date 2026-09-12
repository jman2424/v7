<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { base } from '$app/paths';
  export let tenant: string;
  export let apiPrefix = '';
  type Setup = { widget: { allowed_origins: string[] }; embed: { snippet: string; iframe_snippet: string; chat_url: string } };
  type Connection = { meta_configured: boolean; twilio_configured: boolean; ai_configured: boolean };
  const views = [{id:'install',label:'1. Install'}, {id:'test',label:'2. Test & launch'}, {id:'channels',label:'3. More channels'}, {id:'help',label:'Troubleshooting'}];
  const guides: Record<string, {name: string; steps: string[]; url?: string}> = {
    html: {name:'Custom website / HTML', steps:['Open the shared page layout or site-wide footer in your website editor.', 'Paste the floating-widget script once, immediately before the closing body tag. For a framework, use its supported client-side script loader in the shared layout.', 'Publish the site and test on the actual website address. Do not add the script separately on every client-side navigation.']},
    wordpress: {name:'WordPress', steps:['Use your site’s approved header/footer code tool to add the floating-widget script to the site-wide footer. A developer can add it through a child theme instead.', 'For a chat panel on one page, choose Embedded panel below and use a Custom HTML block that permits iframes.', 'WordPress.com requires a plugin-enabled plan for JavaScript and iframe code. If your plan strips the code, use the Direct chat link option.'], url:'https://wordpress.com/support/code/'},
    shopify: {name:'Shopify', steps:['Duplicate your theme before changing its code. In Online Store → Themes, open Edit code for the theme you want to use.', 'In layout/theme.liquid, paste the floating-widget script once before the closing body tag, then save.', 'Preview, then publish the theme. This installs the widget on the storefront, not checkout. Recheck the installation after theme updates.'], url:'https://help.shopify.com/en/manual/online-store/themes/customizing-themes/edit-code/edit-theme-code'},
    wix: {name:'Wix', steps:['For a floating widget, open Custom Code in your site dashboard and add the script to all pages at Body – end. Custom-code availability depends on your site setup.', 'For an inline chat panel, use an HTML iframe embed and the Embedded panel code below. A normal text box will not run the code.', 'Publish and test the real website, not only the editor preview. Approve the exact published domain in Website widget settings.'], url:'https://support.wix.com/en/article/embedding-custom-code-on-your-site'},
    squarespace: {name:'Squarespace', steps:['Open your site’s Code Injection settings and paste the floating-widget script in the Footer field.', 'Save and open the published site outside the editor. Code Injection depends on your plan.', 'If script injection is unavailable, add a normal website button using the Direct chat link below.'], url:'https://support.squarespace.com/hc/en-us/articles/205815908-Using-code-injection'}
  };
  let view = 'install';
  let platform = 'html';
  let format = 'floating';
  let data: Setup | null = null;
  let connection: Connection | null = null;
  let busy = false;
  let error = '';
  let copyStatus = '';
  let website = '';
  let originResult = '';
  let controller: AbortController | undefined;
  $: code = data ? format === 'floating' ? data.embed.snippet : format === 'panel' ? data.embed.iframe_snippet : data.embed.chat_url : '';
  $: if (format) copyStatus = '';
  onMount(() => { void refresh(); });
  onDestroy(() => controller?.abort());

  async function refresh() {
    controller?.abort();
    const request = new AbortController();
    controller = request;
    busy = true; error = ''; data = null; connection = null; originResult = ''; copyStatus = '';
    const timeout = setTimeout(() => request.abort(), 20000);
    try {
      const query = '?tenant=' + encodeURIComponent(tenant);
      const [widget, integrations] = await Promise.all([
        fetch(apiPrefix + '/admin/api/widget' + query, {credentials:'same-origin', signal:request.signal}),
        fetch(apiPrefix + '/admin/api/integrations' + query, {credentials:'same-origin', signal:request.signal})
      ]);
      if (!widget.ok || !integrations.ok) throw new Error(widget.status === 401 || integrations.status === 401 ? 'Your session expired. Sign in again.' : 'Could not load the saved setup. Try refreshing.');
      const [setup, status] = await Promise.all([widget.json(), integrations.json()]);
      if (controller === request && !request.signal.aborted) { data = setup; connection = status; }
    } catch (failure) {
      if (controller === request) error = request.signal.aborted ? 'Loading timed out. Try refreshing.' : failure instanceof Error ? failure.message : 'Unable to load setup.';
    } finally { clearTimeout(timeout); if (controller === request) busy = false; }
  }

  async function copy() {
    try { await navigator.clipboard.writeText(code); copyStatus = format === 'link' ? 'Chat link copied.' : 'Installation code copied.'; }
    catch { copyStatus = 'Copy is unavailable in this browser. Select the text below and copy it manually.'; }
  }

  function checkOrigin() {
    try {
      const url = new URL(website.trim());
      if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) throw new Error();
      const approved = data?.widget.allowed_origins.some(origin => { try { return new URL(origin).origin === url.origin; } catch { return false; } });
      originResult = approved ? `${url.origin} is on this company’s approved list. Now test the widget on the published site.` : `${url.origin} is not approved. Add this exact origin in Website widget settings, save, then refresh this page.`;
    } catch { originResult = 'Enter a full website address, for example https://www.yourcompany.com.'; }
  }
</script>

<section class="implementation" aria-label="Implementation guide">
  <div class="intro"><div><h2>Connect your agent to your website</h2><p>For {tenant}. Follow the steps for your website builder, then test before sharing with customers.</p></div><button on:click={refresh} disabled={busy}>Refresh setup</button></div>
  <nav aria-label="Implementation steps">{#each views as item}<button class:active={view === item.id} aria-pressed={view === item.id} on:click={() => view = item.id}>{item.label}</button>{/each}</nav>
  {#if busy}<p role="status">Loading saved setup…</p>{/if}
  {#if error}<p class="error" role="alert">{error}</p>{/if}
  {#if data && connection}
    {#if view === 'install'}
      <article class="panel"><h3>Start with your business information</h3><p>Add your products or services, prices, FAQs and contact details before launch. The agent uses the saved information for this company; website installation does not automatically import your website or shop inventory.</p><div class="links"><a href={base+'/profile'}>Business profile</a><a href={base+'/catalog'}>Products &amp; services</a><a href={base+'/agent'}>Agent playbook</a></div></article>
      <article class="panel"><div class="heading"><h3>Approve your website</h3><a href={base+'/website'}>Edit website settings</a></div><p>Approve each exact website address that will host the chat. Addresses with and without “www” are different; include both if customers use both.</p>
        <div class="origins">{#each data.widget.allowed_origins as origin}<code>{origin}</code>{:else}<p class="notice">No websites approved yet. Add your website before installing an embedded chat.</p>{/each}</div>
        <form on:submit|preventDefault={checkOrigin}><label for="setup-site">Check a website address<input id="setup-site" type="url" bind:value={website} placeholder="https://www.yourcompany.com" required /></label><button type="submit">Check approval</button></form>
        <p class="hint">This checks the saved domain list only. It does not scan or verify installation on your website.</p>{#if originResult}<p role="status">{originResult}</p>{/if}
      </article>
      <article class="panel"><h3>Add the chat</h3><label>Website platform<select bind:value={platform}>{#each Object.entries(guides) as [key, guide]}<option value={key}>{guide.name}</option>{/each}</select></label>
        <ol>{#each guides[platform].steps as step}<li>{step}</li>{/each}</ol>
        {#if guides[platform].url}<a href={guides[platform].url} target="_blank" rel="noreferrer">Official {guides[platform].name} instructions ↗</a>{/if}
        <div class="code-tools"><label>Installation type<select bind:value={format}><option value="floating">Floating chat button</option><option value="panel">Embedded panel</option><option value="link">Direct chat link</option></select></label><button disabled={!code} on:click={copy}>{format === 'link' ? 'Copy link' : 'Copy code'}</button></div>
        <label>{format === 'link' ? 'Public customer chat link' : 'Company installation code'}<textarea readonly value={code} rows={format === 'panel' ? 5 : 3} spellcheck="false"></textarea></label>
        {#if copyStatus}<p role="status">{copyStatus}</p>{/if}
        <p class="hint">{format === 'floating' ? 'Adds a floating button. Install it once per page.' : format === 'panel' ? 'Place this in an HTML area where the chat should appear. Adjust the height to fit your page.' : 'Use this as the destination of a website button, or share it with customers. No script installation is needed.'} The code contains a public company identifier, never an API key.</p>
      </article>
    {:else if view === 'test'}
      <article class="panel"><h3>Test the agent’s answers</h3><p>Use Test agent for private setup conversations. These do not create sales leads, but AI calls still appear in API usage.</p><ul><li>Ask about a product or service, then ask a follow-up price question.</li><li>Check your hours, locations, policies and delivery conditions where relevant.</li><li>Ask something you have not configured. The agent should ask for clarification or offer human help rather than invent details.</li><li>Try typing and speech in a supported browser.</li></ul><a class="primary" href={base+'/test'} data-sveltekit-reload>Open Test agent</a></article>
      <article class="panel"><h3>Check the published website</h3><ol><li>Open your published website on desktop and mobile. Check that the chat fits without covering essential controls.</li><li>Open and close the widget, send a sample message and check the company name and reply.</li><li>Confirm the expected conversation appears in Conversations. Public chat tests count as customer activity.</li><li>Verify your human contact path. A quote or booking request is not a confirmed booking or payment unless you have connected that workflow.</li></ol><div class="links"><a href={data.embed.chat_url} target="_blank" rel="noreferrer">Open public chat ↗</a><a href={base+'/conversations'}>Conversations</a><a href={base+'/faqs'}>Update answers</a></div></article>
    {:else if view === 'channels'}
      <article class="panel"><h3>Website and AI</h3><p>Website installation is independent of WhatsApp. {connection.ai_configured ? 'An AI provider key is configured; use Test agent to verify responses.' : 'An AI provider key is not configured. Saved-data responses can still work; ask the platform operator to enable AI planning when needed.'}</p><p class="hint">Configuration status is not a live provider connection test.</p><a href={base+'/integrations'}>Open integration settings</a></article>
      <article class="panel"><h3>WhatsApp · optional</h3><p><a href={base+'/whatsapp-qr'}>Create a WhatsApp link and QR code</a> for your website, shop or printed materials.</p><p>{connection.meta_configured ? 'Meta credentials are configured for this company.' : connection.twilio_configured ? 'Twilio credentials are configured for this company.' : 'WhatsApp is awaiting setup. You can launch website chat first.'}</p><ol><li>Choose Meta Cloud API or Twilio with the platform operator.</li><li>Connect the business number and map it to this company on the server.</li><li>Configure the signed incoming-message webhook and delivery-status callback in the provider account.</li><li>Test an incoming message, reply and delivery status before advertising the number.</li></ol><a href={'/admin/integrations?tenant='+encodeURIComponent(tenant)}>WhatsApp routes &amp; status</a><p class="hint">Provider credentials stay on the server. Never paste them into your website or the chat.</p></article>
      <article class="panel"><h3>Bookings, payments and live inventory</h3><p>The agent can explain saved information and collect enquiries. Automatic bookings, payments and inventory updates need their own connected systems and validation. Adding the widget does not enable these integrations by itself.</p></article>
    {:else}
      <article class="panel"><h3>Common setup problems</h3>
        <details><summary>The chat does not appear</summary><p>Check that the code is on the published site, not only in the editor. Use a code-injection area that allows scripts, then clear your site cache. If scripts are unavailable, use a Direct chat link. Some website builders restrict custom code by plan.</p></details>
        <details><summary>The frame is blocked or says Forbidden</summary><p>Check the exact website origin, including https, www and any subdomain. Add it in Website widget settings and save. Your website’s security policy must also allow the V7 host for scripts and frames; ask your developer to add that host without disabling the policy.</p></details>
        <details><summary>The agent uses the wrong company or old information</summary><p>Copy fresh installation code while the correct company is selected. Save your business changes, start a new Test agent conversation and reload the widget. Widget branding may be cached for up to five minutes. Each company needs its own code.</p></details>
        <details><summary>The microphone does not work</summary><p>Use HTTPS and a browser that supports dictation, then allow microphone access when you choose to speak. Embedded speech also depends on the host website’s permissions policy. Typing remains available.</p></details>
        <details><summary>Replies are slow or fail</summary><p>Check Errors &amp; health and retry once. The platform operator should check provider configuration, limits and hosting. A sleeping free hosting instance may take time to start.</p></details>
        <details><summary>There are two chat buttons</summary><p>Remove the extra installation from your theme or code tool. Install one floating widget per company per page. An inline panel and a floating widget are separate installations.</p></details>
        <details><summary>How do I remove the widget?</summary><p>Remove the script or iframe from the website and republish. Remove an unused website from Approved website origins as well. This does not delete the company’s saved conversations.</p></details>
        <div class="links"><a href={base+'/website'}>Website widget settings</a><a href={base+'/errors'}>Errors &amp; health</a></div>
      </article>
    {/if}
  {/if}
</section>

<style>
  .implementation { display:grid; gap:20px; min-width:0; overflow-wrap:anywhere; }
  .intro, .heading, .code-tools, form, .links, nav { display:flex; flex-wrap:wrap; align-items:center; gap:12px; }
  .intro, .heading { justify-content:space-between; } .intro > div { flex:1 1 320px; }
  h2, h3 { margin:0; } h2 { font-size:21px; } h3 { font-size:18px; } p, li { line-height:1.6; color:#526359; }
  .panel { min-width:0; padding:24px; border:1px solid #d9ddd7; background:#fff; border-radius:8px; }
  button, select, input, textarea { box-sizing:border-box; max-width:100%; border:1px solid #bbc4bc; border-radius:6px; background:#fff; color:#26332b; padding:11px 13px; font:inherit; }
  button { min-height:44px; cursor:pointer; font-weight:600; } button:disabled { opacity:.6; cursor:wait; }
  button.active, .primary { background:#007d70; border-color:#007d70; color:#fff; } a { color:#007d70; }
  .primary { display:inline-block; padding:12px 16px; border-radius:6px; text-decoration:none; }
  label { display:grid; gap:8px; font-size:14px; font-weight:600; min-width:0; } form { align-items:end; } form label { flex:1 1 260px; }
  textarea { width:100%; font-family:ui-monospace,monospace; font-size:13px; resize:vertical; overflow-wrap:anywhere; }
  .code-tools { align-items:end; margin:24px 0 16px; } .code-tools label { flex:1 1 220px; }
  .origins { display:flex; gap:8px; flex-wrap:wrap; margin:16px 0; } code { background:#f0f4ef; padding:7px 10px; border-radius:5px; }
  .hint { font-size:13px; } .error { color:#a12622; } .notice { margin:0; }
  ol, ul { padding-left:24px; } li { padding:5px 0 5px 4px; }
  details { border-bottom:1px solid #e4e8e1; padding:16px 0; } summary { cursor:pointer; font-weight:600; line-height:1.5; } details p { margin:12px 0 0; }
  .links { margin-top:18px; } :is(button, a, input, textarea, select, summary):focus-visible { outline:3px solid #8bcdc0; outline-offset:3px; }
  @media(max-width:600px) { .panel { padding:16px; } nav button { flex:1 1 130px; } }
</style>
