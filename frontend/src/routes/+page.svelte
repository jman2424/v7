<script lang="ts">
  import { onMount } from 'svelte';

  type User = {
    email: string;
    roles: string[];
    tenant: string;
  };

  type Widget = {
    chat_title: string;
    greeting: string;
    avatar: string;
    allowed_origins: string[];
  };

  type Tenant = {
    key: string;
    name: string;
    valid: boolean;
    widget_configured: boolean;
  };

  let user: User | null = null;
  let csrf = '';
  let widget: Widget = { chat_title: '', greeting: '', avatar: '', allowed_origins: [] };
  let snippet = '';
  let tenant = 'EXAMPLE';
  let originText = '';
  let tenants: Tenant[] = [];
  let email = '';
  let password = '';
  let totp = '';
  let loginError = '';
  let formStatus = '';
  let formError = false;
  let loading = true;
  let showCreateTenant = false;
  let newTenantKey = '';
  let newTenantName = '';
  let createStatus = '';

  $: isPlatform = Boolean(user?.roles?.some((role) => role === 'platform_admin' || role === 'admin'));

  function apiPath(path: string) {
    return `/api${path}`;
  }

  async function readJson(response: Response) {
    return response.json().catch(() => ({}));
  }

  async function loadWidget(selectedTenant = tenant) {
    const response = await fetch(apiPath(`/admin/api/widget?tenant=${encodeURIComponent(selectedTenant)}`), {
      headers: { Accept: 'application/json' },
      credentials: 'same-origin'
    });
    const data = await readJson(response);
    if (!response.ok) throw new Error(data.error || 'Could not load widget settings.');
    tenant = data.tenant;
    widget = data.widget;
    originText = (widget.allowed_origins || []).join('\n');
    snippet = data.embed?.snippet || '';
  }

  async function loadTenants() {
    if (!isPlatform) return;
    const response = await fetch(apiPath('/admin/api/tenants'), { credentials: 'same-origin' });
    const data = await readJson(response);
    if (response.ok) tenants = data.tenants || [];
  }

  async function restoreSession() {
    const response = await fetch(apiPath('/auth/session'), { credentials: 'same-origin' });
    if (!response.ok) return;
    const data = await readJson(response);
    user = data.user;
    csrf = data.csrf_token || '';
    tenant = user?.tenant || tenant;
    await loadWidget(tenant);
    await loadTenants();
  }

  async function login() {
    loginError = '';
    const response = await fetch(apiPath('/auth/login'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ email, password, totp, tenant })
    });
    const data = await readJson(response);
    if (!response.ok) {
      loginError = data.error || 'Sign-in failed.';
      return;
    }
    user = data.user;
    csrf = data.csrf_token || '';
    tenant = user?.tenant || tenant;
    await loadWidget(tenant);
    await loadTenants();
  }

  async function saveWidget() {
    formStatus = 'Saving...';
    formError = false;
    const payload = {
      chat_title: widget.chat_title,
      greeting: widget.greeting,
      avatar: widget.avatar,
      allowed_origins: originText.split('\n').map((value) => value.trim()).filter(Boolean)
    };
    const response = await fetch(apiPath(`/admin/api/widget?tenant=${encodeURIComponent(tenant)}`), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
      credentials: 'same-origin',
      body: JSON.stringify(payload)
    });
    const data = await readJson(response);
    if (!response.ok) {
      formStatus = data.error || 'Could not save changes.';
      formError = true;
      return;
    }
    widget = data.widget;
    snippet = data.embed?.snippet || '';
    originText = (widget.allowed_origins || []).join('\n');
    formStatus = 'Saved. New widget loads use these settings.';
    await loadTenants();
  }

  async function copySnippet() {
    await navigator.clipboard.writeText(snippet);
    formStatus = 'Install script copied.';
    formError = false;
  }

  async function createTenant() {
    createStatus = 'Creating tenant...';
    const response = await fetch(apiPath('/admin/api/tenants'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
      credentials: 'same-origin',
      body: JSON.stringify({ key: newTenantKey, name: newTenantName })
    });
    const data = await readJson(response);
    if (!response.ok) {
      createStatus = data.error || 'Could not create tenant.';
      return;
    }
    createStatus = `${data.tenant.name} is ready for configuration.`;
    newTenantKey = '';
    newTenantName = '';
    await loadTenants();
  }

  async function selectTenant(nextTenant: string) {
    formStatus = '';
    await loadWidget(nextTenant);
  }

  onMount(async () => {
    try {
      await restoreSession();
    } finally {
      loading = false;
    }
  });
</script>

<svelte:head>
  <title>V7 Owner Console</title>
  <meta name="description" content="Tenant widget configuration for the V7 AI sales agent." />
</svelte:head>

{#if loading}
  <main class="loading" aria-live="polite">Loading owner console...</main>
{:else if !user}
  <main class="login-shell">
    <form class="login" on:submit|preventDefault={login}>
      <div class="product-mark">V7</div>
      <h1>Owner console</h1>
      <p>Manage the customer-facing sales agent for your business.</p>
      <label>Tenant key<input bind:value={tenant} autocomplete="organization" required /></label>
      <label>Email<input bind:value={email} type="email" autocomplete="username" required /></label>
      <label>Password<input bind:value={password} type="password" autocomplete="current-password" required /></label>
      <label>TOTP code <span>Optional</span><input bind:value={totp} inputmode="numeric" autocomplete="one-time-code" /></label>
      {#if loginError}<div class="notice error">{loginError}</div>{/if}
      <button class="primary" type="submit">Sign in</button>
    </form>
  </main>
{:else}
  <div class="app-shell">
    <aside class="sidebar">
      <div class="side-brand"><span>V7</span><strong>{tenant}</strong></div>
      <nav aria-label="Owner console navigation">
        <a class="active" href="#widget">Widget setup</a>
        <a href="#install">Install script</a>
        {#if isPlatform}<button class="nav-button" type="button" on:click={() => (showCreateTenant = !showCreateTenant)}>Tenants</button>{/if}
      </nav>
      <div class="account"><strong>{user.email}</strong><span>{isPlatform ? 'Platform operator' : 'Business owner'}</span></div>
    </aside>

    <main class="workspace">
      <header class="workspace-head">
        <div><p class="eyebrow">Customer channel</p><h1>Website widget</h1></div>
        {#if isPlatform && tenants.length > 0}
          <label class="tenant-picker">Tenant<select value={tenant} on:change={(event) => selectTenant(event.currentTarget.value)}>{#each tenants as item}<option value={item.key}>{item.name}</option>{/each}</select></label>
        {/if}
      </header>

      {#if showCreateTenant && isPlatform}
        <section class="operator-panel" aria-labelledby="tenant-create-heading">
          <div><p class="eyebrow">Platform operator</p><h2 id="tenant-create-heading">Create a clean tenant</h2><p>The starter workspace has no allowed websites and only an out-of-stock setup item.</p></div>
          <form class="tenant-form" on:submit|preventDefault={createTenant}>
            <label>Tenant key<input bind:value={newTenantKey} placeholder="NORTHSTAR" pattern={'[A-Za-z0-9_-]{1,64}'} required /></label>
            <label>Business name<input bind:value={newTenantName} placeholder="Northstar Homewares" required /></label>
            <button class="primary" type="submit">Create tenant</button>
          </form>
          {#if createStatus}<p class="form-status">{createStatus}</p>{/if}
        </section>
      {/if}

      <div class="content-grid">
        <section id="widget" class="surface setup" aria-labelledby="widget-heading">
          <div class="surface-head"><div><p class="eyebrow">Brand and access</p><h2 id="widget-heading">Widget settings</h2></div><span class="status-dot">Ready</span></div>
          <form class="settings-form" on:submit|preventDefault={saveWidget}>
            <label>Chat title<input bind:value={widget.chat_title} maxlength="80" required /></label>
            <label>Greeting<textarea bind:value={widget.greeting} maxlength="240" required></textarea></label>
            <label>Avatar URL<input bind:value={widget.avatar} type="url" placeholder="https://assets.yourcompany.com/avatar.png" /><small>HTTPS image URL or a relative path hosted by V7.</small></label>
            <label>Approved website origins<textarea bind:value={originText} class="origins" spellcheck="false" placeholder="https://www.yourcompany.com&#10;https://shop.yourcompany.com" required></textarea><small>Use one exact origin per line. HTTPS is required except for localhost development.</small></label>
            <div class="form-footer"><span class:error={formError} class="form-status">{formStatus}</span><button class="primary" type="submit">Save changes</button></div>
          </form>
        </section>

        <section id="install" class="surface install" aria-labelledby="install-heading">
          <div class="surface-head"><div><p class="eyebrow">Website integration</p><h2 id="install-heading">Install script</h2></div><button class="secondary" type="button" on:click={copySnippet}>Copy</button></div>
          <p>Place this once before the closing body tag on an approved website.</p>
          <textarea class="code" readonly value={snippet} aria-label="Website install script"></textarea>
          <div class="allowlist"><h3>Approved origins</h3>{#if widget.allowed_origins.length}{#each widget.allowed_origins as origin}<code>{origin}</code>{/each}{:else}<p>No website is approved yet.</p>{/if}</div>
        </section>
      </div>
    </main>
  </div>
{/if}

<style>
  :global(body) { background: #f4f7fa; }
  .loading, .login-shell { min-height: 100vh; display: grid; place-items: center; color: #5f6d80; }
  .login-shell { padding: 24px; }
  .login { width: min(100%, 390px); display: grid; gap: 16px; padding: 32px; background: #fff; border: 1px solid #d8dee8; border-radius: 8px; box-shadow: 0 14px 32px rgba(15, 23, 42, .08); }
  .product-mark { width: 42px; height: 42px; display: grid; place-items: center; background: #0b9a5f; color: #fff; border-radius: 8px; font-weight: 800; }
  h1, h2, h3, p { margin-top: 0; }
  .login h1 { margin-bottom: -8px; font-size: 25px; letter-spacing: 0; }
  .login p { color: #667085; line-height: 1.5; }
  label { display: grid; gap: 7px; color: #344054; font-size: 13px; font-weight: 700; }
  label span { color: #8b98aa; font-weight: 500; }
  input, textarea, select { width: 100%; min-height: 40px; padding: 9px 10px; border: 1px solid #b9c3d2; border-radius: 6px; color: #172033; background: #fff; }
  textarea { min-height: 84px; resize: vertical; line-height: 1.45; }
  input:focus, textarea:focus, select:focus { outline: 3px solid rgba(11,154,95,.16); border-color: #0b9a5f; }
  .primary, .secondary { min-height: 38px; border-radius: 6px; padding: 0 14px; font-weight: 700; font-size: 14px; }
  .primary { border: 1px solid #0b9a5f; background: #0b9a5f; color: #fff; }
  .primary:hover { background: #087b4c; }
  .secondary { border: 1px solid #b9c3d2; background: #fff; color: #344054; }
  .secondary:hover { background: #f8fafc; }
  .notice { padding: 10px 12px; border-radius: 6px; font-size: 13px; }
  .error { color: #b42318; background: #fff2f0; }
  .app-shell { min-height: 100vh; display: grid; grid-template-columns: 236px minmax(0, 1fr); }
  .sidebar { display: flex; flex-direction: column; gap: 28px; padding: 24px 16px; background: #101c27; color: #f6f8fb; }
  .side-brand { display: grid; gap: 6px; padding: 0 10px; }
  .side-brand span { color: #6be1aa; font-size: 13px; font-weight: 800; letter-spacing: .08em; }
  .side-brand strong { font-size: 17px; overflow-wrap: anywhere; }
  nav { display: grid; gap: 4px; }
  nav a, .nav-button { width: 100%; border: 0; border-radius: 6px; padding: 10px; color: #c6d2e1; background: transparent; text-align: left; text-decoration: none; font-size: 14px; }
  nav a:hover, nav a.active, .nav-button:hover { color: #fff; background: #203143; }
  .account { display: grid; gap: 4px; margin-top: auto; padding: 12px 10px; border-top: 1px solid #2c3d50; font-size: 12px; overflow-wrap: anywhere; }
  .account span { color: #a7b6c8; }
  .workspace { padding: 34px clamp(20px, 5vw, 70px) 56px; }
  .workspace-head { display: flex; align-items: end; justify-content: space-between; gap: 20px; margin-bottom: 28px; }
  .workspace-head h1 { margin-bottom: 0; font-size: 29px; letter-spacing: 0; }
  .eyebrow { margin-bottom: 7px; color: #0b8d57; font-size: 12px; font-weight: 800; letter-spacing: .06em; text-transform: uppercase; }
  .tenant-picker { min-width: 220px; }
  .operator-panel { display: grid; grid-template-columns: minmax(0, 1fr) minmax(360px, .9fr); gap: 24px; padding: 20px; margin-bottom: 20px; background: #eefbf5; border: 1px solid #b9e9d0; border-radius: 8px; }
  .operator-panel h2 { margin-bottom: 8px; font-size: 18px; }
  .operator-panel p:not(.eyebrow) { margin-bottom: 0; color: #526172; line-height: 1.45; }
  .tenant-form { display: grid; grid-template-columns: 1fr 1fr auto; align-items: end; gap: 12px; }
  .content-grid { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(300px, .8fr); gap: 20px; align-items: start; }
  .surface { background: #fff; border: 1px solid #d8dee8; border-radius: 8px; }
  .surface-head { display: flex; align-items: start; justify-content: space-between; gap: 16px; padding: 20px; border-bottom: 1px solid #e2e7ee; }
  .surface-head h2 { margin-bottom: 0; font-size: 17px; }
  .status-dot { padding: 5px 8px; color: #087b4c; background: #ecfdf3; border: 1px solid #abefc6; border-radius: 99px; font-size: 12px; font-weight: 700; }
  .settings-form { display: grid; gap: 18px; padding: 20px; }
  small { color: #667085; font-size: 12px; font-weight: 500; line-height: 1.4; }
  .origins { min-height: 120px; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 12px; }
  .form-footer { display: flex; align-items: center; justify-content: space-between; gap: 14px; min-height: 38px; }
  .form-status { color: #667085; font-size: 13px; line-height: 1.4; }
  .form-status.error { color: #b42318; }
  .install > p { padding: 18px 20px 0; margin-bottom: 12px; color: #667085; font-size: 14px; line-height: 1.5; }
  .code { min-height: 132px; margin: 0 20px; width: calc(100% - 40px); background: #101c27; color: #dbf8e7; border: 0; border-radius: 6px; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 12px; }
  .allowlist { padding: 20px; }
  .allowlist h3 { margin-bottom: 12px; font-size: 14px; }
  .allowlist p { margin-bottom: 0; color: #667085; font-size: 13px; }
  .allowlist code { display: block; margin: 7px 0; padding: 8px; border-left: 3px solid #0b9a5f; background: #f5faf7; color: #344054; font-size: 12px; overflow-wrap: anywhere; }
  @media (max-width: 900px) { .content-grid, .operator-panel { grid-template-columns: 1fr; } .tenant-form { grid-template-columns: 1fr; } }
  @media (max-width: 720px) { .app-shell { grid-template-columns: 1fr; } .sidebar { min-height: auto; gap: 16px; padding: 14px; } .side-brand { grid-template-columns: auto 1fr; align-items: baseline; } nav { grid-template-columns: repeat(2, minmax(0, 1fr)); } .account { display: none; } .workspace { padding: 24px 16px 40px; } .workspace-head { align-items: start; flex-direction: column; } .tenant-picker { width: 100%; } .form-footer { align-items: stretch; flex-direction: column; } .form-footer .primary { width: 100%; } }
</style>
