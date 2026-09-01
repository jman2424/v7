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

  type CatalogItem = {
    sku: string;
    name: string;
    price: number;
    unit: string;
    tags: string[];
    in_stock: boolean;
  };

  type CatalogCategory = {
    id: string;
    name: string;
    items: CatalogItem[];
  };

  type Catalog = {
    version: number | string;
    currency?: string;
    categories: CatalogCategory[];
  };

  type Faq = {
    q: string;
    a: string;
    tags: string[];
  };

  type DeliveryRule = {
    area: string;
    fee: number;
    min_order: number;
    eta_hours: string;
    eta_min: number;
  };

  type DeliveryException = {
    date: string;
    note: string;
  };

  type Delivery = {
    mode: 'zones' | 'areas';
    rules: DeliveryRule[];
    click_and_collect: boolean;
    notes: string;
    exceptions: DeliveryException[];
  };

  type Profile = {
    name: string;
    about: string;
    email: string;
    phone: string;
    website: string;
    halal_certified: boolean;
    certifications: string[];
    social: Record<string, string>;
  };

  type BranchHours = Record<'mon' | 'tue' | 'wed' | 'thu' | 'fri' | 'sat' | 'sun', string>;

  type Branch = {
    id: string;
    name: string;
    address: string;
    postcode: string;
    phone: string;
    lat: number;
    lon: number;
    hours: BranchHours;
  };

  type AgentSettings = {
    tone: {
      style: 'friendly' | 'professional' | 'concise';
      max_sentences: number;
    };
  };

  let user: User | null = null;
  let csrf = '';
  let widget: Widget = { chat_title: '', greeting: '', avatar: '', allowed_origins: [] };
  let catalog: Catalog = { version: 1, currency: 'GBP', categories: [] };
  let faqs: Faq[] = [];
  let delivery: Delivery = { mode: 'zones', rules: [], click_and_collect: true, notes: '', exceptions: [] };
  let profile: Profile = { name: '', about: '', email: '', phone: '', website: '', halal_certified: false, certifications: [], social: {} };
  let branches: Branch[] = [];
  let agentSettings: AgentSettings = { tone: { style: 'friendly', max_sentences: 2 } };
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
  let catalogStatus = '';
  let catalogError = false;
  let faqStatus = '';
  let faqError = false;
  let deliveryStatus = '';
  let deliveryError = false;
  let profileStatus = '';
  let profileError = false;
  let branchesStatus = '';
  let branchesError = false;
  let agentStatus = '';
  let agentError = false;

  $: isPlatform = Boolean(user?.roles?.some((role) => role === 'platform_admin' || role === 'admin'));

  function apiPath(path: string) {
    return `/api${path}`;
  }

  async function readJson(response: Response) {
    return response.json().catch(() => ({}));
  }

  function stringList(value: unknown) {
    return Array.isArray(value) ? value.map((item) => String(item).trim()).filter(Boolean) : [];
  }

  function normalizeCatalog(value: unknown): Catalog {
    const source = value && typeof value === 'object' ? value as Record<string, unknown> : {};
    const categories = Array.isArray(source.categories) ? source.categories : [];
    return {
      version: typeof source.version === 'number' || typeof source.version === 'string' ? source.version : 1,
      currency: typeof source.currency === 'string' ? source.currency : 'GBP',
      categories: categories.filter((category): category is Record<string, unknown> => Boolean(category && typeof category === 'object')).map((category) => ({
        id: String(category.id || ''),
        name: String(category.name || ''),
        items: Array.isArray(category.items) ? category.items.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object')).map((item) => ({
          sku: String(item.sku || ''),
          name: String(item.name || ''),
          price: Number(item.price || 0),
          unit: String(item.unit || 'each'),
          tags: stringList(item.tags),
          in_stock: item.in_stock !== false
        })) : []
      }))
    };
  }

  function normalizeFaqs(value: unknown): Faq[] {
    if (!Array.isArray(value)) return [];
    return value.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object')).map((item) => ({
      q: String(item.q || ''),
      a: String(item.a || ''),
      tags: stringList(item.tags)
    }));
  }

  function normalizeDelivery(value: unknown): Delivery {
    const source = value && typeof value === 'object' ? value as Record<string, unknown> : {};
    const zones = Array.isArray(source.zones) ? source.zones : [];
    const areas = Array.isArray(source.areas) ? source.areas : [];
    const mode: Delivery['mode'] = zones.length > 0 || !Array.isArray(source.areas) ? 'zones' : 'areas';
    const rawRules = mode === 'zones' ? zones : areas;
    return {
      mode,
      rules: rawRules.filter((rule): rule is Record<string, unknown> => Boolean(rule && typeof rule === 'object')).map((rule) => ({
        area: String(mode === 'zones' ? rule.area || '' : rule.postcode_prefix || ''),
        fee: Number(rule.fee || 0),
        min_order: Number(rule.min_order || 0),
        eta_hours: String(rule.eta_hours || ''),
        eta_min: Number(rule.eta_min || 0)
      })),
      click_and_collect: source.click_and_collect !== false,
      notes: String(source.notes || ''),
      exceptions: Array.isArray(source.exceptions) ? source.exceptions.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object')).map((item) => ({
        date: String(item.date || ''),
        note: String(item.note || '')
      })) : []
    };
  }

  function normalizeProfile(value: unknown): Profile {
    const source = value && typeof value === 'object' ? value as Record<string, unknown> : {};
    const socialSource = source.social && typeof source.social === 'object' ? source.social as Record<string, unknown> : {};
    const social = Object.fromEntries(Object.entries(socialSource).filter(([, item]) => typeof item === 'string').map(([key, item]) => [key, String(item)]));
    return {
      name: String(source.name || ''), about: String(source.about || ''), email: String(source.email || ''), phone: String(source.phone || ''), website: String(source.website || ''),
      halal_certified: source.halal_certified === true, certifications: stringList(source.certifications), social
    };
  }

  function emptyHours(): BranchHours {
    return { mon: '', tue: '', wed: '', thu: '', fri: '', sat: '', sun: '' };
  }

  function expandHours(value: unknown): BranchHours {
    const source = value && typeof value === 'object' ? value as Record<string, unknown> : {};
    const hours = emptyHours();
    const days: Array<keyof BranchHours> = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
    for (const day of days) hours[day] = typeof source[day] === 'string' ? source[day] : '';
    for (const [key, raw] of Object.entries(source)) {
      if (typeof raw !== 'string' || !key.includes('-')) continue;
      const [first, last] = key.toLowerCase().split('-', 2) as [keyof BranchHours, keyof BranchHours];
      const start = days.indexOf(first);
      const end = days.indexOf(last);
      if (start >= 0 && end >= start) for (let index = start; index <= end; index += 1) if (!hours[days[index]]) hours[days[index]] = raw;
    }
    if (typeof source.daily === 'string') for (const day of days) if (!hours[day]) hours[day] = source.daily;
    return hours;
  }

  function normalizeBranches(value: unknown): Branch[] {
    if (!Array.isArray(value)) return [];
    return value.filter((branch): branch is Record<string, unknown> => Boolean(branch && typeof branch === 'object')).map((branch) => ({
      id: String(branch.id || ''), name: String(branch.name || ''), address: String(branch.address || ''), postcode: String(branch.postcode || ''), phone: String(branch.phone || ''),
      lat: Number(branch.lat || 0), lon: Number(branch.lon || 0), hours: expandHours(branch.hours)
    }));
  }

  function normalizeAgentSettings(value: unknown): AgentSettings {
    const source = value && typeof value === 'object' ? value as Record<string, unknown> : {};
    const tone = source.tone && typeof source.tone === 'object' ? source.tone as Record<string, unknown> : {};
    const style = ['friendly', 'professional', 'concise'].includes(String(tone.style)) ? String(tone.style) as AgentSettings['tone']['style'] : 'friendly';
    const max = Number(tone.max_sentences || 2);
    return { tone: { style, max_sentences: Number.isInteger(max) && max >= 1 && max <= 4 ? max : 2 } };
  }

  async function loadTenantWorkspace(selectedTenant = tenant) {
    const encodedTenant = encodeURIComponent(selectedTenant);
    const responses = await Promise.all([
      fetch(apiPath(`/admin/api/widget?tenant=${encodedTenant}`), { headers: { Accept: 'application/json' }, credentials: 'same-origin' }),
      fetch(apiPath(`/admin/api/catalog?tenant=${encodedTenant}`), { headers: { Accept: 'application/json' }, credentials: 'same-origin' }),
      fetch(apiPath(`/admin/api/faq?tenant=${encodedTenant}`), { headers: { Accept: 'application/json' }, credentials: 'same-origin' }),
      fetch(apiPath(`/admin/api/delivery?tenant=${encodedTenant}`), { headers: { Accept: 'application/json' }, credentials: 'same-origin' }),
      fetch(apiPath(`/admin/api/profile?tenant=${encodedTenant}`), { headers: { Accept: 'application/json' }, credentials: 'same-origin' }),
      fetch(apiPath(`/admin/api/branches?tenant=${encodedTenant}`), { headers: { Accept: 'application/json' }, credentials: 'same-origin' }),
      fetch(apiPath(`/admin/api/agent-settings?tenant=${encodedTenant}`), { headers: { Accept: 'application/json' }, credentials: 'same-origin' })
    ]);
    const [widgetData, catalogData, faqData, deliveryData, profileData, branchesData, agentData] = await Promise.all(responses.map(readJson));
    if (responses.some((response) => !response.ok)) {
      const failed = [widgetData, catalogData, faqData, deliveryData, profileData, branchesData, agentData].find((data, index) => !responses[index].ok);
      throw new Error(failed?.error || 'Could not load this tenant workspace.');
    }
    tenant = widgetData.tenant;
    widget = widgetData.widget;
    originText = (widget.allowed_origins || []).join('\n');
    snippet = widgetData.embed?.snippet || '';
    catalog = normalizeCatalog(catalogData);
    faqs = normalizeFaqs(faqData);
    delivery = normalizeDelivery(deliveryData);
    profile = normalizeProfile(profileData);
    branches = normalizeBranches(branchesData);
    agentSettings = normalizeAgentSettings(agentData);
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
    await loadTenantWorkspace(tenant);
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
    await loadTenantWorkspace(tenant);
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
    catalogStatus = '';
    faqStatus = '';
    deliveryStatus = '';
    profileStatus = '';
    branchesStatus = '';
    agentStatus = '';
    await loadTenantWorkspace(nextTenant);
  }

  function slug(value: string) {
    return value.toLowerCase().trim().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '') || 'new_category';
  }

  function addCategory() {
    const number = catalog.categories.length + 1;
    catalog = { ...catalog, categories: [...catalog.categories, { id: `category_${number}`, name: `New category ${number}`, items: [] }] };
  }

  function removeCategory(index: number) {
    catalog = { ...catalog, categories: catalog.categories.filter((_, current) => current !== index) };
  }

  function addProduct(categoryIndex: number) {
    const categories = catalog.categories.map((category, index) => index === categoryIndex ? {
      ...category,
      items: [...category.items, { sku: 'NEW_PRODUCT', name: 'New product', price: 0, unit: 'each', tags: [], in_stock: true }]
    } : category);
    catalog = { ...catalog, categories };
  }

  function removeProduct(categoryIndex: number, itemIndex: number) {
    const categories = catalog.categories.map((category, index) => index === categoryIndex ? {
      ...category,
      items: category.items.filter((_, current) => current !== itemIndex)
    } : category);
    catalog = { ...catalog, categories };
  }

  function addFaq() {
    faqs = [...faqs, { q: 'New question', a: 'Add a helpful answer.', tags: [] }];
  }

  function removeFaq(index: number) {
    faqs = faqs.filter((_, current) => current !== index);
  }

  function addDeliveryRule() {
    delivery = {
      ...delivery,
      rules: [...delivery.rules, { area: '', fee: 0, min_order: 0, eta_hours: 'Next-day', eta_min: 60 }]
    };
  }

  function removeDeliveryRule(index: number) {
    delivery = { ...delivery, rules: delivery.rules.filter((_, current) => current !== index) };
  }

  function addException() {
    delivery = { ...delivery, exceptions: [...delivery.exceptions, { date: '', note: '' }] };
  }

  function removeException(index: number) {
    delivery = { ...delivery, exceptions: delivery.exceptions.filter((_, current) => current !== index) };
  }

  async function saveCatalog() {
    catalogStatus = 'Saving...';
    catalogError = false;
    const categories = catalog.categories.map((category) => ({
      id: category.id.trim() || slug(category.name),
      name: category.name.trim(),
      items: category.items.map((item) => ({
        sku: item.sku.trim(), name: item.name.trim(), price: Number(item.price), unit: item.unit.trim() || 'each',
        tags: item.tags.map((tag) => tag.trim()).filter(Boolean), in_stock: Boolean(item.in_stock)
      }))
    }));
    if (!categories.length || categories.some((category) => !category.name || !category.items.length || category.items.some((item) => !item.sku || !item.name || !Number.isFinite(item.price) || item.price < 0))) {
      catalogStatus = 'Each category needs a name and at least one complete product.';
      catalogError = true;
      return;
    }
    const response = await fetch(apiPath(`/admin/api/catalog?tenant=${encodeURIComponent(tenant)}`), {
      method: 'PUT', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }, credentials: 'same-origin',
      body: JSON.stringify({ version: catalog.version || 1, currency: (catalog.currency || 'GBP').toUpperCase(), categories })
    });
    const data = await readJson(response);
    if (!response.ok) {
      catalogStatus = data.detail || data.error || 'Could not save catalog.';
      catalogError = true;
      return;
    }
    catalog = { ...catalog, categories };
    catalogStatus = 'Catalog saved. New conversations use these products.';
  }

  async function saveFaqs() {
    faqStatus = 'Saving...';
    faqError = false;
    const payload = faqs.map((faq) => ({ q: faq.q.trim(), a: faq.a.trim(), tags: faq.tags.map((tag) => tag.trim()).filter(Boolean) }));
    if (payload.some((faq) => !faq.q || !faq.a)) {
      faqStatus = 'Every FAQ needs both a question and answer.';
      faqError = true;
      return;
    }
    const response = await fetch(apiPath(`/admin/api/faq?tenant=${encodeURIComponent(tenant)}`), {
      method: 'PUT', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }, credentials: 'same-origin', body: JSON.stringify(payload)
    });
    const data = await readJson(response);
    if (!response.ok) {
      faqStatus = data.detail || data.error || 'Could not save FAQs.';
      faqError = true;
      return;
    }
    faqs = payload;
    faqStatus = 'FAQs saved. The assistant can use the new answers now.';
  }

  async function saveDelivery() {
    deliveryStatus = 'Saving...';
    deliveryError = false;
    const rules = delivery.rules.map((rule) => ({ ...rule, area: rule.area.trim(), fee: Number(rule.fee), min_order: Number(rule.min_order), eta_hours: rule.eta_hours.trim(), eta_min: Number(rule.eta_min) }));
    if (rules.some((rule) => !rule.area || !Number.isFinite(rule.fee) || rule.fee < 0 || !Number.isFinite(rule.min_order) || rule.min_order < 0 || (delivery.mode === 'zones' && !rule.eta_hours) || (delivery.mode === 'areas' && (!Number.isFinite(rule.eta_min) || rule.eta_min < 0)))) {
      deliveryStatus = 'Complete each delivery rule with a coverage area, fee, minimum order, and ETA.';
      deliveryError = true;
      return;
    }
    const exceptions = delivery.exceptions.map((item) => ({ date: item.date, note: item.note.trim() })).filter((item) => item.date || item.note);
    if (exceptions.some((item) => !item.date || !item.note)) {
      deliveryStatus = 'Each delivery exception needs both a date and note.';
      deliveryError = true;
      return;
    }
    const base = { click_and_collect: delivery.click_and_collect, notes: delivery.notes.trim(), exceptions };
    const payload = delivery.mode === 'zones'
      ? { ...base, zones: rules.map(({ area, fee, min_order, eta_hours }) => ({ area, fee, min_order, eta_hours })) }
      : { ...base, areas: rules.map(({ area, fee, min_order, eta_min }) => ({ postcode_prefix: area, fee, min_order, eta_min })) };
    const response = await fetch(apiPath(`/admin/api/delivery?tenant=${encodeURIComponent(tenant)}`), {
      method: 'PUT', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }, credentials: 'same-origin', body: JSON.stringify(payload)
    });
    const data = await readJson(response);
    if (!response.ok) {
      deliveryStatus = data.detail || data.error || 'Could not save delivery settings.';
      deliveryError = true;
      return;
    }
    deliveryStatus = 'Delivery settings saved. New conversations use these rules.';
  }

  function addBranch() {
    const number = branches.length + 1;
    branches = [...branches, { id: `branch_${number}`, name: `New branch ${number}`, address: '', postcode: '', phone: '', lat: 0, lon: 0, hours: emptyHours() }];
  }

  function removeBranch(index: number) {
    branches = branches.filter((_, current) => current !== index);
  }

  async function saveProfile() {
    profileStatus = 'Saving...';
    profileError = false;
    const payload = {
      name: profile.name.trim(), about: profile.about.trim(), email: profile.email.trim(), phone: profile.phone.trim(), website: profile.website.trim(),
      halal_certified: Boolean(profile.halal_certified), certifications: profile.certifications.map((item) => item.trim()).filter(Boolean),
      social: Object.fromEntries(Object.entries(profile.social).map(([key, value]) => [key, value.trim()]).filter(([, value]) => Boolean(value)))
    };
    if (!payload.name) {
      profileStatus = 'Business name is required.';
      profileError = true;
      return;
    }
    const response = await fetch(apiPath(`/admin/api/profile?tenant=${encodeURIComponent(tenant)}`), {
      method: 'PUT', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }, credentials: 'same-origin', body: JSON.stringify(payload)
    });
    const data = await readJson(response);
    if (!response.ok) {
      profileStatus = data.detail || data.error || 'Could not save business profile.';
      profileError = true;
      return;
    }
    profile = { ...profile, ...payload };
    profileStatus = 'Business profile saved.';
  }

  async function saveBranches() {
    branchesStatus = 'Saving...';
    branchesError = false;
    const payload = branches.map((branch) => ({
      id: branch.id.trim() || slug(branch.name), name: branch.name.trim(), address: branch.address.trim(), postcode: branch.postcode.trim(), phone: branch.phone.trim(),
      lat: Number(branch.lat), lon: Number(branch.lon), hours: Object.fromEntries(Object.entries(branch.hours).map(([day, hours]) => [day, hours.trim()]).filter(([, hours]) => Boolean(hours)))
    }));
    if (payload.some((branch) => !branch.id || !branch.name || !branch.postcode || !Number.isFinite(branch.lat) || branch.lat < -90 || branch.lat > 90 || !Number.isFinite(branch.lon) || branch.lon < -180 || branch.lon > 180)) {
      branchesStatus = 'Each branch needs a name, postcode, and valid latitude and longitude.';
      branchesError = true;
      return;
    }
    const response = await fetch(apiPath(`/admin/api/branches?tenant=${encodeURIComponent(tenant)}`), {
      method: 'PUT', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }, credentials: 'same-origin', body: JSON.stringify(payload)
    });
    const data = await readJson(response);
    if (!response.ok) {
      branchesStatus = data.detail || data.error || 'Could not save branches.';
      branchesError = true;
      return;
    }
    branches = normalizeBranches(payload);
    branchesStatus = 'Branches and opening hours saved.';
  }

  async function saveAgentSettings() {
    agentStatus = 'Saving...';
    agentError = false;
    const response = await fetch(apiPath(`/admin/api/agent-settings?tenant=${encodeURIComponent(tenant)}`), {
      method: 'PUT', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }, credentials: 'same-origin', body: JSON.stringify(agentSettings)
    });
    const data = await readJson(response);
    if (!response.ok) {
      agentStatus = data.error || 'Could not save agent settings.';
      agentError = true;
      return;
    }
    agentSettings = normalizeAgentSettings({ tone: data.tone });
    agentStatus = 'Agent tone saved. New replies use this style.';
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
        <a href="#catalog">Catalog</a>
        <a href="#faqs">FAQs</a>
        <a href="#delivery">Delivery</a>
        <a href="#profile">Business profile</a>
        <a href="#branches">Branches</a>
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

      <section id="catalog" class="surface workspace-section" aria-labelledby="catalog-heading">
        <div class="surface-head"><div><p class="eyebrow">Sales knowledge</p><h2 id="catalog-heading">Product catalog</h2></div><span class="count-label">{catalog.categories.length} categories</span></div>
        <div class="catalog-toolbar">
          <label>Currency<input class="currency" bind:value={catalog.currency} maxlength="3" aria-label="Catalog currency" /></label>
          <button class="secondary" type="button" on:click={addCategory}>Add category</button>
        </div>
        {#each catalog.categories as category, categoryIndex}
          <section class="editor-group" aria-label={`Category ${category.name || categoryIndex + 1}`}>
            <div class="group-heading">
              <div class="category-fields"><label>Category name<input bind:value={category.name} required /></label><label>Category key<input bind:value={category.id} required /></label></div>
              <button class="icon-button danger" type="button" title="Remove category" aria-label={`Remove ${category.name || 'category'}`} on:click={() => removeCategory(categoryIndex)}>Remove</button>
            </div>
            <div class="product-table" role="region" aria-label={`${category.name || 'Category'} products`}>
              <div class="product-table-head" aria-hidden="true"><span>Product</span><span>SKU</span><span>Price</span><span>Unit</span><span>Tags</span><span>Stock</span><span></span></div>
              {#each category.items as item, itemIndex}
                <div class="product-row">
                  <input bind:value={item.name} aria-label="Product name" required />
                  <input bind:value={item.sku} aria-label="Product SKU" required />
                  <input bind:value={item.price} type="number" min="0" step="0.01" aria-label="Product price" required />
                  <input bind:value={item.unit} aria-label="Product unit" required />
                  <input value={item.tags.join(', ')} on:input={(event) => (item.tags = event.currentTarget.value.split(',').map((tag) => tag.trim()).filter(Boolean))} aria-label="Product tags" placeholder="gift, summer" />
                  <label class="stock-toggle"><input bind:checked={item.in_stock} type="checkbox" /><span>{item.in_stock ? 'In stock' : 'Out'}</span></label>
                  <button class="icon-button danger" type="button" title="Remove product" aria-label={`Remove ${item.name || 'product'}`} on:click={() => removeProduct(categoryIndex, itemIndex)}>Remove</button>
                </div>
              {/each}
            </div>
            <button class="add-row" type="button" on:click={() => addProduct(categoryIndex)}>Add product</button>
          </section>
        {/each}
        <div class="section-footer"><span class:error={catalogError} class="form-status">{catalogStatus}</span><button class="primary" type="button" on:click={saveCatalog}>Save catalog</button></div>
      </section>

      <div class="management-grid">
        <section id="faqs" class="surface workspace-section" aria-labelledby="faq-heading">
          <div class="surface-head"><div><p class="eyebrow">Sales knowledge</p><h2 id="faq-heading">Frequently asked questions</h2></div><button class="secondary" type="button" on:click={addFaq}>Add FAQ</button></div>
          <div class="faq-list">
            {#each faqs as faq, index}
              <div class="faq-editor">
                <label>Question<input bind:value={faq.q} required /></label>
                <label>Answer<textarea bind:value={faq.a} required></textarea></label>
                <div class="row-actions"><label>Topics<input value={faq.tags.join(', ')} on:input={(event) => (faq.tags = event.currentTarget.value.split(',').map((tag) => tag.trim()).filter(Boolean))} placeholder="delivery, opening hours" /></label><button class="icon-button danger" type="button" title="Remove FAQ" aria-label={`Remove FAQ ${index + 1}`} on:click={() => removeFaq(index)}>Remove</button></div>
              </div>
            {:else}
              <p class="empty-state">No FAQs yet. Add the answers customers ask for most.</p>
            {/each}
          </div>
          <div class="section-footer"><span class:error={faqError} class="form-status">{faqStatus}</span><button class="primary" type="button" on:click={saveFaqs}>Save FAQs</button></div>
        </section>

        <section id="delivery" class="surface workspace-section" aria-labelledby="delivery-heading">
          <div class="surface-head"><div><p class="eyebrow">Sales fulfillment</p><h2 id="delivery-heading">Delivery settings</h2></div><button class="secondary" type="button" on:click={addDeliveryRule}>Add delivery area</button></div>
          <div class="delivery-content">
            <label>Delivery notes<textarea bind:value={delivery.notes} placeholder="Tell customers about free delivery, ordering cutoffs, or collection."></textarea></label>
            <label class="collection-toggle"><input bind:checked={delivery.click_and_collect} type="checkbox" /><span>Click and collect is available</span></label>
            <p class="field-note">This tenant currently uses {delivery.mode === 'zones' ? 'postcode zones' : 'postcode prefixes'}. Existing delivery data stays in that format.</p>
            {#each delivery.rules as rule, index}
              <div class="delivery-rule">
                <label>Coverage<input bind:value={rule.area} placeholder={delivery.mode === 'zones' ? 'E1-E4' : 'E1'} required /></label>
                <label>Delivery fee<input bind:value={rule.fee} type="number" min="0" step="0.01" required /></label>
                <label>Minimum order<input bind:value={rule.min_order} type="number" min="0" step="0.01" required /></label>
                {#if delivery.mode === 'zones'}
                  <label>Customer ETA<input bind:value={rule.eta_hours} placeholder="Same-day before 5pm" required /></label>
                {:else}
                  <label>ETA minutes<input bind:value={rule.eta_min} type="number" min="0" step="1" required /></label>
                {/if}
                <button class="icon-button danger" type="button" title="Remove delivery area" aria-label={`Remove delivery area ${index + 1}`} on:click={() => removeDeliveryRule(index)}>Remove</button>
              </div>
            {:else}
              <p class="empty-state">No delivery areas have been added.</p>
            {/each}
            <div class="exception-heading"><h3>Service exceptions</h3><button class="add-row" type="button" on:click={addException}>Add exception</button></div>
            {#each delivery.exceptions as exception, index}
              <div class="exception-row"><label>Date<input bind:value={exception.date} type="date" required /></label><label>Customer message<input bind:value={exception.note} required /></label><button class="icon-button danger" type="button" title="Remove exception" aria-label={`Remove exception ${index + 1}`} on:click={() => removeException(index)}>Remove</button></div>
            {/each}
          </div>
          <div class="section-footer"><span class:error={deliveryError} class="form-status">{deliveryStatus}</span><button class="primary" type="button" on:click={saveDelivery}>Save delivery settings</button></div>
        </section>
      </div>

      <div class="management-grid business-grid">
        <section id="profile" class="surface workspace-section" aria-labelledby="profile-heading">
          <div class="surface-head"><div><p class="eyebrow">Business knowledge</p><h2 id="profile-heading">Business profile</h2></div></div>
          <form class="profile-form" on:submit|preventDefault={saveProfile}>
            <label>Business name<input bind:value={profile.name} maxlength="120" required /></label>
            <label>About the business<textarea bind:value={profile.about} maxlength="1200" placeholder="What do you sell and why do customers choose you?"></textarea></label>
            <div class="two-fields"><label>Customer email<input bind:value={profile.email} type="email" /></label><label>Phone<input bind:value={profile.phone} type="tel" /></label></div>
            <label>Website<input bind:value={profile.website} type="url" placeholder="https://www.yourcompany.com" /></label>
            <label>Certifications<input value={profile.certifications.join(', ')} on:input={(event) => (profile.certifications = event.currentTarget.value.split(',').map((item) => item.trim()).filter(Boolean))} placeholder="B Corp, ISO 9001" /></label>
            <label class="collection-toggle"><input bind:checked={profile.halal_certified} type="checkbox" /><span>Halal-certified business</span></label>
            <div class="two-fields"><label>Instagram<input bind:value={profile.social.instagram} type="url" placeholder="https://instagram.com/yourcompany" /></label><label>Facebook<input bind:value={profile.social.facebook} type="url" placeholder="https://facebook.com/yourcompany" /></label></div>
            <div class="section-footer profile-footer"><span class:error={profileError} class="form-status">{profileStatus}</span><button class="primary" type="submit">Save profile</button></div>
          </form>
        </section>

        <section class="surface workspace-section" aria-labelledby="tone-heading">
          <div class="surface-head"><div><p class="eyebrow">Agent behavior</p><h2 id="tone-heading">Sales tone</h2></div></div>
          <form class="tone-form" on:submit|preventDefault={saveAgentSettings}>
            <label>Conversation style<select bind:value={agentSettings.tone.style}><option value="friendly">Friendly</option><option value="professional">Professional</option><option value="concise">Concise</option></select></label>
            <label>Maximum reply sentences<select bind:value={agentSettings.tone.max_sentences}><option value={1}>1 sentence</option><option value={2}>2 sentences</option><option value={3}>3 sentences</option><option value={4}>4 sentences</option></select></label>
            <p class="field-note">The V7 reply formatter applies this tone and length after grounding the answer in your catalog, FAQ, and delivery data.</p>
            <div class="section-footer profile-footer"><span class:error={agentError} class="form-status">{agentStatus}</span><button class="primary" type="submit">Save agent tone</button></div>
          </form>
        </section>
      </div>

      <section id="branches" class="surface workspace-section" aria-labelledby="branches-heading">
        <div class="surface-head"><div><p class="eyebrow">Locations and handoff</p><h2 id="branches-heading">Branches and opening hours</h2></div><button class="secondary" type="button" on:click={addBranch}>Add branch</button></div>
        <div class="branches-list">
          {#each branches as branch, branchIndex}
            <section class="branch-editor" aria-label={`Branch ${branch.name || branchIndex + 1}`}>
              <div class="branch-heading"><h3>{branch.name || `Branch ${branchIndex + 1}`}</h3><button class="icon-button danger" type="button" title="Remove branch" aria-label={`Remove ${branch.name || 'branch'}`} on:click={() => removeBranch(branchIndex)}>Remove</button></div>
              <div class="branch-fields"><label>Branch name<input bind:value={branch.name} required /></label><label>Branch key<input bind:value={branch.id} required /></label><label>Postcode<input bind:value={branch.postcode} required /></label><label>Phone<input bind:value={branch.phone} type="tel" /></label><label class="wide-field">Street address<input bind:value={branch.address} /></label><label>Latitude<input bind:value={branch.lat} type="number" min="-90" max="90" step="0.0001" required /></label><label>Longitude<input bind:value={branch.lon} type="number" min="-180" max="180" step="0.0001" required /></label></div>
              <div class="hours-grid"><h4>Opening hours</h4>{#each ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as day}<label>{day.toUpperCase()}<input bind:value={branch.hours[day as keyof BranchHours]} placeholder="09:00-18:00" /></label>{/each}</div>
            </section>
          {:else}
            <p class="empty-state branches-empty">No branches yet. Add a location so the assistant can direct customers to the right place.</p>
          {/each}
        </div>
        <div class="section-footer"><span class:error={branchesError} class="form-status">{branchesStatus}</span><button class="primary" type="button" on:click={saveBranches}>Save branches</button></div>
      </section>
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
  .workspace-section { margin-top: 20px; scroll-margin-top: 18px; }
  .count-label { padding: 5px 8px; color: #526172; background: #f2f4f7; border: 1px solid #d8dee8; border-radius: 99px; font-size: 12px; font-weight: 700; white-space: nowrap; }
  .catalog-toolbar { display: flex; align-items: end; justify-content: space-between; gap: 16px; padding: 18px 20px; border-bottom: 1px solid #e2e7ee; }
  .catalog-toolbar label { max-width: 112px; }
  .currency { text-transform: uppercase; }
  .editor-group { padding: 20px; border-bottom: 1px solid #e2e7ee; }
  .group-heading { display: flex; align-items: end; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
  .category-fields { display: grid; grid-template-columns: minmax(180px, 1fr) minmax(120px, .55fr); gap: 12px; width: min(100%, 580px); }
  .product-table { overflow-x: auto; border: 1px solid #e2e7ee; border-radius: 6px; }
  .product-table-head, .product-row { display: grid; grid-template-columns: minmax(190px, 1.4fr) minmax(150px, 1fr) 96px 92px minmax(170px, 1fr) 86px 76px; gap: 8px; align-items: center; min-width: 880px; padding: 9px 10px; }
  .product-table-head { color: #667085; background: #f8fafc; border-bottom: 1px solid #e2e7ee; font-size: 11px; font-weight: 800; letter-spacing: .04em; text-transform: uppercase; }
  .product-row + .product-row { border-top: 1px solid #edf0f4; }
  .product-row input { min-width: 0; }
  .stock-toggle, .collection-toggle { display: flex; grid-template-columns: auto 1fr; align-items: center; gap: 7px; color: #344054; font-size: 12px; white-space: nowrap; }
  .stock-toggle input, .collection-toggle input { width: 16px; min-height: 16px; accent-color: #0b9a5f; }
  .icon-button { min-height: 34px; padding: 0 8px; border: 1px solid #b9c3d2; border-radius: 6px; background: #fff; color: #526172; font-size: 12px; font-weight: 700; }
  .icon-button:hover { background: #f8fafc; }
  .icon-button.danger { color: #b42318; border-color: #f0b5af; }
  .icon-button.danger:hover { background: #fff2f0; }
  .add-row { min-height: 34px; margin-top: 12px; padding: 0; border: 0; color: #087b4c; background: transparent; font-size: 13px; font-weight: 800; }
  .add-row:hover { color: #065f3c; text-decoration: underline; }
  .section-footer { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 18px 20px; }
  .section-footer .form-status { max-width: 68ch; }
  .management-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 20px; align-items: start; }
  .management-grid .workspace-section { min-width: 0; }
  .faq-list, .delivery-content { padding: 20px; }
  .faq-list { display: grid; gap: 16px; }
  .faq-editor { display: grid; gap: 12px; padding-bottom: 16px; border-bottom: 1px solid #e2e7ee; }
  .faq-editor:last-child { padding-bottom: 0; border-bottom: 0; }
  .row-actions { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: end; gap: 12px; }
  .empty-state { margin: 0; padding: 14px 0; color: #667085; font-size: 14px; line-height: 1.5; }
  .delivery-content { display: grid; gap: 16px; }
  .field-note { margin: -4px 0 2px; color: #667085; font-size: 12px; line-height: 1.45; }
  .delivery-rule { display: grid; grid-template-columns: minmax(110px, .85fr) minmax(105px, .7fr) minmax(115px, .8fr) minmax(150px, 1.2fr) auto; align-items: end; gap: 10px; padding: 14px 0; border-top: 1px solid #e2e7ee; }
  .exception-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-top: 4px; border-top: 1px solid #e2e7ee; }
  .exception-heading h3 { margin: 12px 0 0; font-size: 14px; }
  .exception-row { display: grid; grid-template-columns: minmax(130px, .55fr) minmax(0, 1.45fr) auto; align-items: end; gap: 10px; }
  .profile-form, .tone-form { display: grid; gap: 16px; padding: 20px; }
  .two-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
  .profile-footer { padding: 2px 0 0; }
  .branches-list { display: grid; }
  .branch-editor { padding: 20px; border-bottom: 1px solid #e2e7ee; }
  .branch-heading { display: flex; align-items: center; justify-content: space-between; gap: 14px; margin-bottom: 16px; }
  .branch-heading h3 { margin: 0; font-size: 16px; }
  .branch-fields { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
  .wide-field { grid-column: span 2; }
  .hours-grid { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 9px; margin-top: 18px; padding-top: 18px; border-top: 1px solid #e2e7ee; }
  .hours-grid h4 { grid-column: 1 / -1; margin: 0 0 2px; color: #344054; font-size: 14px; }
  .hours-grid label { font-size: 11px; text-transform: uppercase; }
  .hours-grid input { font-size: 12px; text-transform: none; }
  .branches-empty { padding: 20px; }
  @media (max-width: 1050px) { .management-grid { grid-template-columns: 1fr; } .delivery-rule { grid-template-columns: repeat(2, minmax(0, 1fr)); } .delivery-rule .icon-button { width: fit-content; } }
  @media (max-width: 900px) { .content-grid, .operator-panel { grid-template-columns: 1fr; } .tenant-form { grid-template-columns: 1fr; } }
  @media (max-width: 720px) { .app-shell { grid-template-columns: 1fr; } .sidebar { min-height: auto; gap: 16px; padding: 14px; } .side-brand { grid-template-columns: auto 1fr; align-items: baseline; } nav { grid-template-columns: repeat(2, minmax(0, 1fr)); } .account { display: none; } .workspace { padding: 24px 16px 40px; } .workspace-head { align-items: start; flex-direction: column; } .tenant-picker { width: 100%; } .form-footer, .section-footer, .group-heading { align-items: stretch; flex-direction: column; } .form-footer .primary, .section-footer .primary { width: 100%; } .catalog-toolbar { align-items: stretch; flex-direction: column; } .catalog-toolbar label { max-width: none; } .category-fields, .row-actions, .exception-row, .two-fields, .branch-fields { grid-template-columns: 1fr; } .wide-field { grid-column: auto; } .hours-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .row-actions .icon-button, .exception-row .icon-button, .branch-heading .icon-button { width: fit-content; } }
</style>
