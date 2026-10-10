<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { base } from '$app/paths';
  import { goto } from '$app/navigation';
  import PlatformOverview from './PlatformOverview.svelte';
  import PlatformLogo from './PlatformLogo.svelte';
  import Subscription from './Subscription.svelte';
  import Conversations from './Conversations.svelte';
  import AgentTest from './AgentTest.svelte';
  import WidgetDesigner from './WidgetDesigner.svelte';
  import type { Widget, PreviewTheme } from './widgetAppearance';
  import WebsiteKnowledge from './WebsiteKnowledge.svelte';
  import ConversionSettings from './ConversionSettings.svelte';
  import ApiUsage from './ApiUsage.svelte';
  import Implementation from './Implementation.svelte';
  import ConnectionSettings from './ConnectionSettings.svelte';
  import WhatsAppQr from './WhatsAppQr.svelte';
  import Statistics from './Statistics.svelte';
  import ErrorsHealth from './ErrorsHealth.svelte';
  import Registration from './Registration.svelte';
  import JoinRequests from './JoinRequests.svelte';
  import AccountSecurity from './AccountSecurity.svelte';
  import PrivacySettings from './PrivacySettings.svelte';
  import AiParameters from './AiParameters.svelte';
  import LanguagePicker from './LanguagePicker.svelte';
  import CookiePreferences from './CookiePreferences.svelte';
  import NavigationIcon from './NavigationIcon.svelte';
  import { initialiseLanguage, t } from './i18n';
  let cookiePreferences: CookiePreferences | undefined;
  let cookiePreferencesOpen = false;
  let signupOpen = false;
  export let section = 'pipeline';
  const sections: Record<string, string> = {subscription:'Subscription',platform:'Platform overview',pipeline:'Sales pipeline',statistics:'Statistics',test:'Website widget',implementation:'Implementation','whatsapp-qr':'WhatsApp QR',usage:'API usage & cost',conversations:'Conversations',agent:'Agent playbook',website:'Website widget',integrations:'Integrations',catalog:'Catalogue',offers:'Offers',faqs:'Questions & answers',delivery:'Delivery',profile:'Business profile',branches:'Branches & hours',team:'Team access',companies:'Companies',errors:'Errors & health',account:'Account & security',privacy:'Privacy & data'};
  $: pageTitle = sections[section] || 'Sales workspace';
  const pageDescriptions: Record<string, string> = {
    platform: 'A clear view of your businesses, activity and setup.',
    companies: 'Manage business workspaces and onboarding.',
    pipeline: 'Prioritise leads and keep your next steps clear.',
    statistics: 'Track customer conversations, interest and recorded outcomes.',
    conversations: 'Review customer conversations and the context behind each enquiry.',
    agent: 'Tailor how your assistant understands customers and guides the next step.',
    test: 'Design your customer chat, test your agent and prepare website installation.',
    catalog: 'Keep the products and services your assistant recommends up to date.',
    offers: 'Manage the offers your assistant can share with customers.',
    faqs: 'Give customers clear answers from your saved business information.',
    delivery: 'Set the delivery and collection information customers need.',
    profile: 'The business details your assistant uses in customer conversations.',
    branches: 'Manage locations, contact details and opening hours.',
    website: 'Design your customer chat, test your agent and prepare website installation.',
    integrations: 'Manage the connections that support your customer channels.',
    implementation: 'Prepare your business information and install your assistant.',
    'whatsapp-qr': 'Manage your WhatsApp connection and customer entry points.',
    usage: 'Review recorded AI usage and estimated costs.',
    subscription: 'Manage subscriptions, payments and invoices.',
    team: 'Control who can access this business workspace.',
    errors: 'Review service health and issues that need attention.',
    account: 'Manage your sign-in and account security.',
    privacy: 'Manage business data and privacy preferences.'
  };
  const navigationGroups: { id: string; label: string; keys: string[] }[] = [
    { id: 'businesses', label: 'Businesses', keys: ['platform', 'companies'] },
    { id: 'activity', label: 'Sales activity', keys: ['pipeline', 'statistics', 'conversations', 'errors'] },
    { id: 'setup', label: 'Agent and channels', keys: ['agent', 'website', 'integrations', 'implementation', 'whatsapp-qr'] },
    { id: 'knowledge', label: 'Business knowledge', keys: ['catalog', 'offers', 'faqs', 'delivery', 'profile', 'branches'] },
    { id: 'billing', label: 'Billing and usage', keys: ['subscription', 'usage'] },
    { id: 'account', label: 'Account and access', keys: ['team', 'account', 'privacy'] }
  ];


  type User = {
    permissions?: string[];
    email: string;
    roles: string[];
    tenant: string;
  };

  const isWidgetSection = (screen: string) => screen === 'website' || screen === 'test';
  let widgetView: 'appearance' | 'test' | 'install' = section === 'test' ? 'test' : 'appearance';
  let widgetSaving = false;
  let widgetSaveSequence = 0;
  let savedWidgetFingerprint = '';
  let previewTheme: PreviewTheme = {};
  let iframeSnippet = '';
  let widgetChatUrl = '';
  let installationFormat = 'floating';
  $: widgetDirty = Boolean(savedWidgetFingerprint && savedWidgetFingerprint !== JSON.stringify({ ...widget, allowed_origins: originText.split('\n').map(value => value.trim()).filter(Boolean) }));
  $: installationCode = installationFormat === 'panel' ? iframeSnippet : installationFormat === 'link' ? widgetChatUrl : snippet;
  $: canEditWidget = Boolean(user?.permissions?.includes('business_settings.write'));

  type Tenant = {
    activation: {active:boolean;status:string};
    key: string;
    name: string;
    valid: boolean;
    widget_configured: boolean;
  };

  type ManagedAccount = {
    permissions: string[];
    id: string;
    email: string;
    roles: string[];
    active: boolean;
  };

  type ManagedRole = 'business_owner' | 'business_staff';

  type CatalogItem = {
    sku: string;
    name: string;
    price: number;
    unit: string;
    tags: string[];
    in_stock: boolean;
    stock_quantity?: number | null;
    low_stock_threshold?: number;
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

  const offerToday = new Date().toISOString().slice(0, 10);
  const previousOffer = (offer: Offer) => offer.archived || Boolean(offer.ends_on && offer.ends_on < offerToday);
  type Offer = {
    archived: boolean;
    deal_type: 'custom' | 'buy_one_get_one' | 'minimum_spend';
    minimum_spend: number;
    discount_type: 'percentage' | 'fixed';
    discount_value: number;
    id: string;
    title: string;
    description: string;
    code: string;
    active: boolean;
    starts_on: string;
    ends_on: string;
    product_skus: string[];
  };

  type DeliveryRule = {
    source: Record<string, unknown>;
    area: string;
    fee: number;
    min_order: number;
    eta_hours: string;
    eta_min: number;
  };

  type DeliveryException = {
    source: Record<string, unknown>;
    date: string;
    note: string;
  };

  type Delivery = {
    source: Record<string, unknown>;
    preservedExceptions: Record<string, unknown>[];
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
    legacyHalalCertified?: boolean;
    certifications: string[];
    social: Record<string, string>;
  };

  type InsightKpis = {
    inbound: number;
    sessions: number;
    leads: number;
    fallbacks: number;
  };

  type InsightLead = {
    lead_id: string;
    name: string | null;
    phone: string | null;
    status: string;
    updated_utc: string;
  };

  type LeadStatus = 'Open' | 'Contacted' | 'Qualified' | 'Won' | 'Lost';

  type InsightItem = {
    label: string;
    count: number;
  };

  type SalesFunnel = {
    total: number;
    active: number;
    open: number;
    contacted: number;
    qualified: number;
    won: number;
    lost: number;
    other: number;
    handoffs: number;
    contacts_captured: number;
  };

  type Insights = {
    kpis: InsightKpis;
    sales_funnel: SalesFunnel;
    leads: InsightLead[];
    top_intents: InsightItem[];
  };

  type BranchHours = Record<'mon' | 'tue' | 'wed' | 'thu' | 'fri' | 'sat' | 'sun', string>;

  type Branch = {
    source: Record<string, unknown>;
    id: string;
    name: string;
    address: string;
    postcode: string;
    phone: string;
    lat: number | null;
    lon: number | null;
    hours: BranchHours;
  };

  type AgentPlaybook = {
    business_model: 'general' | 'retail' | 'appointments' | 'professional_services' | 'project_services' | 'subscriptions' | 'hospitality' | 'property' | 'custom';
    fulfilment_mode: 'auto' | 'delivery' | 'collection' | 'at_location' | 'on_site' | 'remote' | 'hybrid';
    customer_type: 'individuals' | 'businesses' | 'both';
    response_guidance: string;
    business_focus: string;
    ideal_customer: string;
    value_propositions: string[];
    offering_type: 'products' | 'services' | 'mixed';
    primary_goal: 'drive_sales' | 'book_consultation' | 'capture_leads' | 'answer_questions' | 'request_quote' | 'book_appointment' | 'start_subscription';
    qualification_questions: string[];
    handoff_message: string;
  };

  type AgentSettings = {
    tone: {
      style: 'friendly' | 'professional' | 'concise';
      max_sentences: number;
    };
    playbook: AgentPlaybook;
  };

  const agentStarters: Record<Exclude<AgentPlaybook['business_model'], 'general'>, {
    label: string;
    offering_type: AgentPlaybook['offering_type'];
    primary_goal: AgentPlaybook['primary_goal'];
    fulfilment_mode: AgentPlaybook['fulfilment_mode'];
    qualification_questions: string[];
  }> = {
    retail: { label: 'Retail and online shops', offering_type: 'products', primary_goal: 'drive_sales', fulfilment_mode: 'auto', qualification_questions: ['What will you use it for?', 'Do you have a budget in mind?'] },
    appointments: { label: 'Appointments and personal services', offering_type: 'services', primary_goal: 'book_appointment', fulfilment_mode: 'at_location', qualification_questions: ['Which service are you interested in?', 'When would you prefer an appointment?'] },
    professional_services: { label: 'Professional and consulting services', offering_type: 'services', primary_goal: 'book_consultation', fulfilment_mode: 'hybrid', qualification_questions: ['What would you like help with?', 'When do you need the work completed?'] },
    project_services: { label: 'Projects, trades and custom work', offering_type: 'services', primary_goal: 'request_quote', fulfilment_mode: 'on_site', qualification_questions: ['What work do you need?', 'Where would the work take place?', 'When would you like it completed?'] },
    subscriptions: { label: 'Subscriptions and memberships', offering_type: 'services', primary_goal: 'start_subscription', fulfilment_mode: 'remote', qualification_questions: ['What would you like the plan to help you achieve?', 'How many people need access?'] },
    hospitality: { label: 'Hospitality, events and venues', offering_type: 'mixed', primary_goal: 'capture_leads', fulfilment_mode: 'at_location', qualification_questions: ['What occasion are you planning?', 'What date do you have in mind?', 'How many guests are you expecting?'] },
    property: { label: 'Property and viewings', offering_type: 'services', primary_goal: 'book_appointment', fulfilment_mode: 'at_location', qualification_questions: ['Which property or area are you interested in?', 'When would you prefer a viewing?'] },
    custom: { label: 'Custom or combined business model', offering_type: 'mixed', primary_goal: 'answer_questions', fulfilment_mode: 'hybrid', qualification_questions: [] }
  };
  let selectedAgentStarter: keyof typeof agentStarters = 'retail';

  let user: User | null = null;
  let csrf = '';
  let widget: Widget = normalizeWidget({});
  let catalog: Catalog = { version: 1, currency: 'GBP', categories: [] };
  let faqs: Faq[] = [];
  let offers: Offer[] = [];
  let delivery: Delivery = { source: {}, preservedExceptions: [], mode: 'zones', rules: [], click_and_collect: true, notes: '', exceptions: [] };
  let profile: Profile = { name: '', about: '', email: '', phone: '', website: '', certifications: [], social: {} };
  let branches: Branch[] = [];
  let agentSettings: AgentSettings = {
    tone: { style: 'friendly', max_sentences: 2 },
    playbook: { business_model: 'general', fulfilment_mode: 'auto', customer_type: 'both', response_guidance: '', business_focus: '', ideal_customer: '', value_propositions: [], offering_type: 'products', primary_goal: 'drive_sales', qualification_questions: [], handoff_message: '' }
  };
  let snippet = '';
  let tenant = 'EXAMPLE';
  let originText = '';
  let tenants: Tenant[] = [];
  let email = '';
  let password = '';
  let showPassword = false;
  let rememberDevice = false;
  let providers: {id: 'google'|'microsoft'; name:string; configured:boolean}[] = [];
  let oidcNotice = '';
  let totp = '';
  let mfa: {enrollment:boolean;email:string;setup_key?:string;qr_image?:string}|null = null;
  let loginError = '';
  let workspaceError = '';
  let tenantDirectoryError = '';
  let tenantDirectoryBusy = false;
  let tenantDirectorySequence = 0;
  let workspaceBusy = false;
  let workspaceGeneration = 0;
  type WorkspaceRequest = { generation: number; identity: User | null };
  type WorkspaceResource = 'activation' | 'widget' | 'catalog' | 'faq' | 'offers' | 'delivery' | 'profile' | 'branches' | 'agent-settings' | 'accounts' | 'insights';
  const workspaceControllers = new Set<AbortController>();
  const loadedWorkspaceResources = new Set<WorkspaceResource>();
  const pendingWorkspaceResources = new Map<WorkspaceResource, Promise<void>>();
  let workspaceLoadSequence = 0;
  let requestedWorkspaceSection = '';
  let signingIn = false;
  let formStatus = '';
  let formError = false;
  let loading = true;
  let navigationOpen = false;

  let newTenantKey = '';
  let newTenantName = '';
  let createStatus = '';
  let accounts: ManagedAccount[] = [];
  let accountEmail = '';
  let accountPassword = '';
  let accountRole: ManagedRole = 'business_owner';
  let selectedAccountId = '';
  let selectedAccountPassword = '';
  let selectedAccountActive = true;
  let accountStatus = '';
  let accountError = false;
  let catalogStatus = '';
  let catalogError = false;
  let faqStatus = '';
  let faqError = false;
  let offersStatus = '';
  let offersError = false;
  let deliveryStatus = '';
  let deliveryError = false;
  let profileStatus = '';
  let profileError = false;
  let branchesStatus = '';
  let branchesError = false;
  let agentStatus = '';
  let agentError = false;
  let insights: Insights = {
    kpis: { inbound: 0, sessions: 0, leads: 0, fallbacks: 0 },
    sales_funnel: { total: 0, active: 0, open: 0, contacted: 0, qualified: 0, won: 0, lost: 0, other: 0, handoffs: 0, contacts_captured: 0 },
    leads: [],
    top_intents: []
  };
  let activityStatus = '';
  const leadStatuses: LeadStatus[] = ['Open', 'Contacted', 'Qualified', 'Won', 'Lost'];

  $: isPlatform = Boolean(user?.roles?.some((role) => role === 'platform_admin' || role === 'admin'));
  $: isOwner = Boolean(user?.roles?.includes('business_owner'));
  $: canViewCosts = Boolean(user?.permissions?.includes('view_costs'));
  $: canViewSubscriptions = Boolean(user?.permissions?.includes('view_subscriptions'));
  let accountViewCosts=false;
  let accountViewSubscriptions=false;
  let selectedViewCosts=false;
  let selectedViewSubscriptions=false;
  let activation:{active:boolean;status:string}|null=null;
  $: canManageAccounts = hasAccountManagementAccess() && Boolean(user?.permissions?.includes('users.read'));
  $: if (user) accountRole = isPlatform ? 'business_owner' : 'business_staff';
  $: if (!loading && !signingIn && user && section !== requestedWorkspaceSection) void loadWorkspaceSection(section);

  function apiPath(path: string) {
    // The dev server proxies API requests. In production Flask serves this
    // console at /console, so direct same-origin requests retain its session.
    return import.meta.env.DEV ? `/api${path}` : path;
  }

  async function readJson(response: Response) {
    return response.json().catch(() => ({}));
  }

  async function requestJson(path: string, options: RequestInit = {}, activeLoad?: WorkspaceRequest) {
    const controller = new AbortController();
    workspaceControllers.add(controller);
    const timeout = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch(apiPath(path), { ...options, signal: controller.signal });
      const data = await response.json();
      if (controller.signal.aborted) throw new Error('request_cancelled');
      return { response, data };
    } finally {
      clearTimeout(timeout);
      workspaceControllers.delete(controller);
    }
  }

  function stringList(value: unknown) {
    return Array.isArray(value) ? value.map((item) => String(item).trim()).filter(Boolean) : [];
  }

  function normalizeWidget(value: unknown): Widget {
    const source = value && typeof value === 'object' ? value as Record<string, unknown> : {};
    const text = (key: string, fallback = '') => typeof source[key] === 'string' ? source[key] as string : fallback;
    const colour = (key: string, fallback = '') => /^#[0-9a-f]{6}$/i.test(text(key)) ? text(key).toUpperCase() : fallback;
    return { chat_title:text('chat_title'), assistant_name:text('assistant_name'), greeting:text('greeting'),
      avatar:text('avatar'), company_logo_url:text('company_logo_url'), style:text('style','midnight'),
      accent_color:colour('accent_color','#3EEA8C'), background_color:colour('background_color'),
      surface_color:colour('surface_color'), text_color:colour('text_color'), bubble_color:colour('bubble_color'),
      allowed_origins:stringList(source.allowed_origins) };
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
          in_stock: item.in_stock !== false,
          stock_quantity: typeof item.stock_quantity === 'number' ? item.stock_quantity : null,
          low_stock_threshold: typeof item.low_stock_threshold === 'number' ? item.low_stock_threshold : 5
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

  function normalizeOffers(value: unknown): Offer[] {
    if (!Array.isArray(value)) return [];
    return value.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object')).map((item) => ({
      archived: item.archived === true, deal_type: item.deal_type === 'buy_one_get_one' || item.deal_type === 'minimum_spend' ? item.deal_type : 'custom',
      minimum_spend: Number(item.minimum_spend || 0), discount_type: item.discount_type === 'fixed' ? 'fixed' : 'percentage', discount_value: Number(item.discount_value || 0),
      id: String(item.id || ''), title: String(item.title || ''), description: String(item.description || ''), code: String(item.code || ''),
      active: item.active === true, starts_on: String(item.starts_on || ''), ends_on: String(item.ends_on || ''), product_skus: stringList(item.product_skus)
    }));
  }

  function normalizeDelivery(value: unknown): Delivery {
    const source = value && typeof value === 'object' ? value as Record<string, unknown> : {};
    const zones = Array.isArray(source.zones) ? source.zones : [];
    const areas = Array.isArray(source.areas) ? source.areas : [];
    const mode: Delivery['mode'] = zones.length > 0 || !Array.isArray(source.areas) ? 'zones' : 'areas';
    const rawRules = mode === 'zones' ? zones : areas;
    const exceptions = Array.isArray(source.exceptions) ? source.exceptions.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object')) : [];
    return {
      source,
      preservedExceptions: exceptions.filter(item => item.postcode && (!item.date || !item.note)),
      mode,
      rules: rawRules.filter((rule): rule is Record<string, unknown> => Boolean(rule && typeof rule === 'object')).map((rule) => ({
        source: Object.fromEntries(Object.entries(rule).filter(([key]) => !['min', 'eta', 'eta_min', 'eta_hours'].includes(key))),
        area: String(mode === 'zones' ? rule.area || '' : rule.postcode_prefix || ''),
        fee: Number(rule.fee || 0),
        min_order: Number(rule.min_order ?? rule.min ?? 0),
        eta_hours: String(rule.eta_hours ?? (typeof rule.eta === 'string' ? rule.eta : rule.eta_min != null || typeof rule.eta === 'number' ? `${rule.eta_min ?? rule.eta} minutes` : '')),
        eta_min: Number(rule.eta_min ?? (typeof rule.eta === 'number' ? rule.eta : 0))
      })),
      click_and_collect: source.click_and_collect !== false,
      notes: String(source.notes || ''),
      exceptions: exceptions.filter(item => !item.postcode || (item.date && item.note)).map((item) => ({
        source: item,
        date: String(item.date || ''),
        note: String(item.note || '')
      }))
    };
  }

  function normalizeProfile(value: unknown): Profile {
    const source = value && typeof value === 'object' ? value as Record<string, unknown> : {};
    const socialSource = source.social && typeof source.social === 'object' ? source.social as Record<string, unknown> : {};
    const social = Object.fromEntries(Object.entries(socialSource).filter(([, item]) => typeof item === 'string').map(([key, item]) => [key, String(item)]));
    return {
      name: String(source.name || ''), about: String(source.about || ''), email: String(source.email || ''), phone: String(source.phone || ''), website: String(source.website || ''),
      legacyHalalCertified: typeof source.halal_certified === 'boolean' ? source.halal_certified : undefined,
      certifications: stringList(source.certifications), social
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
      source: branch,
      id: String(branch.id || ''), name: String(branch.name || ''), address: String(branch.address || ''), postcode: String(branch.postcode || ''), phone: String(branch.phone || ''),
      lat: branch.lat == null ? null : Number(branch.lat), lon: branch.lon == null ? null : Number(branch.lon), hours: expandHours(branch.hours)
    }));
  }

  function normalizeAgentSettings(value: unknown): AgentSettings {
    const source = value && typeof value === 'object' ? value as Record<string, unknown> : {};
    const tone = source.tone && typeof source.tone === 'object' ? source.tone as Record<string, unknown> : {};
    const playbook = source.playbook && typeof source.playbook === 'object' ? source.playbook as Record<string, unknown> : {};
    const style = ['friendly', 'professional', 'concise'].includes(String(tone.style)) ? String(tone.style) as AgentSettings['tone']['style'] : 'friendly';
    const max = Number(tone.max_sentences || 2);
    const offeringType = ['products', 'services', 'mixed'].includes(String(playbook.offering_type)) ? String(playbook.offering_type) as AgentPlaybook['offering_type'] : 'products';
    const primaryGoal = ['drive_sales', 'book_consultation', 'capture_leads', 'answer_questions', 'request_quote', 'book_appointment', 'start_subscription'].includes(String(playbook.primary_goal)) ? String(playbook.primary_goal) as AgentPlaybook['primary_goal'] : 'drive_sales';
    const businessModel = ['general', ...Object.keys(agentStarters)].includes(String(playbook.business_model)) ? String(playbook.business_model) as AgentPlaybook['business_model'] : 'general';
    const fulfilmentMode = ['auto', 'delivery', 'collection', 'at_location', 'on_site', 'remote', 'hybrid'].includes(String(playbook.fulfilment_mode)) ? String(playbook.fulfilment_mode) as AgentPlaybook['fulfilment_mode'] : 'auto';
    const customerType = ['individuals', 'businesses', 'both'].includes(String(playbook.customer_type)) ? String(playbook.customer_type) as AgentPlaybook['customer_type'] : 'both';
    const qualificationQuestions = Array.isArray(playbook.qualification_questions)
      ? playbook.qualification_questions.map((question) => String(question).trim()).filter(Boolean).slice(0, 4)
      : [];
    const valuePropositions = Array.isArray(playbook.value_propositions)
      ? playbook.value_propositions.map((item) => String(item).trim()).filter(Boolean).slice(0, 5)
      : [];
    return {
      tone: { style, max_sentences: Number.isInteger(max) && max >= 1 && max <= 4 ? max : 2 },
      playbook: {
        business_model: businessModel,
        fulfilment_mode: fulfilmentMode,
        customer_type: customerType,
        response_guidance: String(playbook.response_guidance || ''),
        business_focus: String(playbook.business_focus || ''),
        ideal_customer: String(playbook.ideal_customer || ''),
        value_propositions: valuePropositions,
        offering_type: offeringType,
        primary_goal: primaryGoal,
        qualification_questions: qualificationQuestions,
        handoff_message: String(playbook.handoff_message || '')
      }
    };
  }

  function applyAgentStarter() {
    const starter = agentStarters[selectedAgentStarter];
    const current = agentSettings.playbook;
    agentSettings = {
      ...agentSettings,
      playbook: {
        ...current,
        business_model: selectedAgentStarter,
        offering_type: starter.offering_type,
        primary_goal: starter.primary_goal,
        fulfilment_mode: starter.fulfilment_mode,
        qualification_questions: current.qualification_questions.some((question) => question.trim())
          ? [...current.qualification_questions]
          : [...starter.qualification_questions]
      }
    };
    agentError = false;
    agentStatus = `${starter.label} starter applied. Review the settings and save playbook.`;
  }

  function addQualificationQuestion() {
    if (agentSettings.playbook.qualification_questions.length >= 4) return;
    agentSettings.playbook.qualification_questions = [...agentSettings.playbook.qualification_questions, ''];
  }

  function removeQualificationQuestion(index: number) {
    agentSettings.playbook.qualification_questions = agentSettings.playbook.qualification_questions.filter((_, questionIndex) => questionIndex !== index);
  }

  function addValueProposition() {
    if (agentSettings.playbook.value_propositions.length >= 5) return;
    agentSettings.playbook.value_propositions = [...agentSettings.playbook.value_propositions, ''];
  }

  function removeValueProposition(index: number) {
    agentSettings.playbook.value_propositions = agentSettings.playbook.value_propositions.filter((_, propositionIndex) => propositionIndex !== index);
  }

  function safeCount(value: unknown) {
    const number = Number(value);
    return Number.isFinite(number) && number >= 0 ? Math.trunc(number) : 0;
  }

  function normalizeInsights(value: unknown): Insights {
    const source = value && typeof value === 'object' ? value as Record<string, unknown> : {};
    const kpis = source.kpis && typeof source.kpis === 'object' ? source.kpis as Record<string, unknown> : {};
    const funnel = source.sales_funnel && typeof source.sales_funnel === 'object' ? source.sales_funnel as Record<string, unknown> : {};
    const leads = Array.isArray(source.leads) ? source.leads : [];
    const intents = Array.isArray(source.top_intents) ? source.top_intents : [];
    return {
      kpis: { inbound: safeCount(kpis.inbound), sessions: safeCount(kpis.sessions), leads: safeCount(kpis.leads), fallbacks: safeCount(kpis.fallbacks) },
      sales_funnel: {
        total: safeCount(funnel.total), active: safeCount(funnel.active), open: safeCount(funnel.open), contacted: safeCount(funnel.contacted),
        qualified: safeCount(funnel.qualified), won: safeCount(funnel.won), lost: safeCount(funnel.lost), other: safeCount(funnel.other),
        handoffs: safeCount(funnel.handoffs), contacts_captured: safeCount(funnel.contacts_captured)
      },
      leads: leads.filter((lead): lead is Record<string, unknown> => Boolean(lead && typeof lead === 'object')).map((lead) => ({
        lead_id: String(lead.lead_id || ''), name: typeof lead.name === 'string' && lead.name ? lead.name : null, phone: typeof lead.phone === 'string' && lead.phone ? lead.phone : null,
        status: leadStatuses.includes(String(lead.status) as LeadStatus) ? String(lead.status) : 'Open', updated_utc: String(lead.updated_utc || '')
      })),
      top_intents: intents.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object')).map((item) => ({
        label: String(item.label || 'Unknown'), count: safeCount(item.count)
      }))
    };
  }

  function formatActivityDate(value: string) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? 'Not available' : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(date);
  }

  function clearTenantWorkspace() {
    workspaceGeneration++;
    workspaceLoadSequence++;
    tenantDirectorySequence++;
    tenantDirectoryBusy = false;
    tenantDirectoryError = '';
    for (const controller of workspaceControllers) controller.abort();
    workspaceControllers.clear();
    loadedWorkspaceResources.clear();
    pendingWorkspaceResources.clear();
    workspaceBusy = false;
    requestedWorkspaceSection = section;
    activation = null;
    widget = normalizeWidget({});
    previewTheme = {};
    widgetSaveSequence++; widgetSaving = false; savedWidgetFingerprint = '';
    iframeSnippet = ''; widgetChatUrl = '';
    catalog = normalizeCatalog({}); faqs = []; offers = [];
    delivery = normalizeDelivery({}); profile = normalizeProfile({}); branches = [];
    agentSettings = normalizeAgentSettings({}); snippet = ''; originText = '';
    accounts = []; selectedAccountId = ''; selectedAccountPassword = ''; accountPassword = ''; accountEmail = '';
    selectedAccountActive = true; selectedViewCosts = false; selectedViewSubscriptions = false;
    insights = normalizeInsights({}); activityStatus = '';
    formStatus = ''; createStatus = ''; accountStatus = ''; catalogStatus = ''; faqStatus = '';
    offersStatus = ''; deliveryStatus = ''; profileStatus = ''; branchesStatus = ''; agentStatus = '';
  }

  function workspaceRequest(): WorkspaceRequest {
    return { generation: workspaceGeneration, identity: user };
  }

  function isCurrentWorkspace(request: WorkspaceRequest) {
    return request.generation === workspaceGeneration && request.identity === user;
  }

  function beginWorkspaceLoad() {
    clearTenantWorkspace();
    return workspaceRequest();
  }

  function initialWorkspaceSection() {
    const next = new URLSearchParams(window.location.search).get('next');
    if (next && mayOpenScreen(next)) return next;
    if (user?.roles.some(role => role === 'platform_admin' || role === 'admin') && window.location.pathname.replace(/\/$/, '') === base) return defaultWorkspaceScreen();
    return mayOpenScreen(section) ? section : defaultWorkspaceScreen();
  }

  function sectionResources(screen: string, identity: User | null): WorkspaceResource[] {
    const resources: Partial<Record<string, WorkspaceResource[]>> = {
      pipeline: ['insights'], team: ['accounts'], catalog: ['catalog', 'agent-settings'],
      test: ['widget', 'profile'], website: ['widget', 'profile'], integrations: ['widget'],
      agent: ['agent-settings'], offers: ['offers'], faqs: ['faq'], delivery: ['delivery'],
      profile: ['profile'], branches: ['branches']
    };
    const permissions: Partial<Record<WorkspaceResource, string>> = {
      widget: 'business_settings.read', catalog: 'offerings.read', faq: 'business_settings.read',
      offers: 'offers.read', delivery: 'business_settings.read', profile: 'business_settings.read',
      branches: 'business_settings.read', 'agent-settings': 'business_settings.read',
      accounts: 'users.read', insights: 'analytics.read'
    };
    return (resources[screen] || []).filter(resource =>
      identity?.permissions?.includes(permissions[resource] || '') && (resource !== 'accounts' || hasAccountManagementAccess())
    );
  }

  async function loadWorkspaceResource(resource: WorkspaceResource, selectedTenant: string, activeLoad: WorkspaceRequest) {
    if (!isCurrentWorkspace(activeLoad) || loadedWorkspaceResources.has(resource)) return;
    const pending = pendingWorkspaceResources.get(resource);
    if (pending) return pending;
    const request = (async () => {
      if (resource === 'accounts') { if (!await loadAccounts(selectedTenant, activeLoad)) throw new Error('accounts_unavailable'); }
      else if (resource === 'insights') { if (!await loadInsights(selectedTenant, activeLoad)) throw new Error('insights_unavailable'); }
      else {
        const { response, data } = await requestJson(`/admin/api/${resource}?tenant=${encodeURIComponent(selectedTenant)}`, {
          headers: { Accept: 'application/json' }, credentials: 'same-origin'
        }, activeLoad);
        if (!isCurrentWorkspace(activeLoad)) return;
        if (!response.ok) throw new Error('workspace_unavailable');
        switch (resource) {
          case 'activation': activation = data; break;
          case 'widget':
            widget = normalizeWidget(data.widget);
            previewTheme = data.preview_theme || {};
            originText = widget.allowed_origins.join('\n'); snippet = data.embed?.snippet || '';
            iframeSnippet = data.embed?.iframe_snippet || ''; widgetChatUrl = data.embed?.chat_url || '';
            savedWidgetFingerprint = JSON.stringify(widget); break;
          case 'catalog': catalog = normalizeCatalog(data); break;
          case 'faq': faqs = normalizeFaqs(data); break;
          case 'offers': offers = normalizeOffers(data); break;
          case 'delivery': delivery = normalizeDelivery(data); break;
          case 'profile': profile = normalizeProfile(data); break;
          case 'branches': branches = normalizeBranches(data); break;
          case 'agent-settings': agentSettings = normalizeAgentSettings(data); break;
        }
      }
      if (isCurrentWorkspace(activeLoad)) loadedWorkspaceResources.add(resource);
    })();
    pendingWorkspaceResources.set(resource, request);
    try { await request; }
    finally { if (pendingWorkspaceResources.get(resource) === request) pendingWorkspaceResources.delete(resource); }
  }

  async function loadTenantWorkspace(selectedTenant = tenant, activeLoad = beginWorkspaceLoad(), screen = initialWorkspaceSection()) {
    if (!isCurrentWorkspace(activeLoad)) return;
    tenant = selectedTenant;
    await Promise.all(['activation' as const, ...sectionResources(screen, activeLoad.identity)].map(resource => loadWorkspaceResource(resource, selectedTenant, activeLoad)));
  }

  async function loadWorkspaceSection(screen = section, activeLoad = workspaceRequest()) {
    if (!isCurrentWorkspace(activeLoad) || !mayOpenScreen(screen)) return;
    const sequence = ++workspaceLoadSequence;
    requestedWorkspaceSection = screen;
    workspaceBusy = true;
    workspaceError = '';
    try { await loadTenantWorkspace(tenant, activeLoad, screen); }
    catch { if (isCurrentWorkspace(activeLoad) && sequence === workspaceLoadSequence) workspaceError = 'You are signed in, but this page could not load. Check your connection and try again.'; }
    finally { if (isCurrentWorkspace(activeLoad) && sequence === workspaceLoadSequence) workspaceBusy = false; }
  }

  async function retryWorkspace() {
    await loadWorkspaceSection(section);
  }

  async function loadSignedInWorkspace() {
    workspaceError = '';
    tenants = [];
    const activeLoad = beginWorkspaceLoad();
    // Company navigation is independent of the current page and must not delay it.
    void loadTenants(activeLoad);
    await loadWorkspaceSection(initialWorkspaceSection(), activeLoad);
  }

  async function loadTenants(activeLoad = workspaceRequest()) {
    if (!isCurrentWorkspace(activeLoad)) return;
    const sequence = ++tenantDirectorySequence;
    tenantDirectoryError = '';
    if (!hasAccountManagementAccess()) return;
    tenantDirectoryBusy = true;
    try {
      const { response, data } = await requestJson('/admin/api/tenants', { credentials: 'same-origin' }, activeLoad);
      if (!isCurrentWorkspace(activeLoad) || sequence !== tenantDirectorySequence) return;
      if (!response.ok) throw new Error('company_list_unavailable');
      tenants = data.tenants || [];
    } catch {
      if (isCurrentWorkspace(activeLoad) && sequence === tenantDirectorySequence) tenantDirectoryError = 'The company list could not load. Check your connection and try again.';
    } finally { if (isCurrentWorkspace(activeLoad) && sequence === tenantDirectorySequence) tenantDirectoryBusy = false; }
  }

  async function retryTenantDirectory() {
    if (!tenantDirectoryBusy) await loadTenants();
  }

  function hasAccountManagementAccess() {
    return Boolean(user?.roles?.some((role) => role === 'platform_admin' || role === 'admin' || role === 'business_owner'));
  }

  function mayOpenScreen(key: string) {
    if (!user || !Object.hasOwn(sections, key)) return false;
    const operator = user.roles.some(role => role === 'platform_admin' || role === 'admin');
    const owner = user.roles.includes('business_owner');
    if (key === 'platform') return operator && Boolean(user.permissions?.includes('platform.read'));
    if (key === 'companies') return operator || owner;
    if (key === 'team') return (operator || owner) && Boolean(user.permissions?.includes('users.read'));
    if (key === 'account') return true;
    // Match the permissions required by each section's actual API reads.
    const requiredPermissions: Record<string, string[]> = {
      usage: ['view_costs'], subscription: ['view_subscriptions'],
      pipeline: ['analytics.read'], statistics: ['analytics.read'],
      conversations: ['conversations.read'], catalog: ['offerings.read'], offers: ['offers.read'],
      test: ['business_settings.read'], website: ['business_settings.read'], agent: ['business_settings.read'],
      faqs: ['business_settings.read'], delivery: ['business_settings.read'], profile: ['business_settings.read'],
      branches: ['business_settings.read'], privacy: ['business_settings.read'],
      implementation: ['business_settings.read', 'integrations.read'], integrations: ['business_settings.read', 'integrations.read'],
      'whatsapp-qr': ['integrations.read'], errors: ['errors.read', 'analytics.read'],
    };
    const required = requiredPermissions[key];
    return Boolean(required && required.every(permission => user?.permissions?.includes(permission)));
  }

  function mayReadModelParameters() {
    if (!user) return false;
    if (user.roles.some(role => role === 'platform_admin' || role === 'admin')) return Boolean(user.permissions?.includes('models.read'));
    return user.roles.length === 1 && user.roles[0] === 'business_owner' && Boolean(user.permissions?.includes('business_settings.read'));
  }

  function mayReadConversionSettings() {
    return hasAccountManagementAccess() && Boolean(user?.permissions?.includes('business_settings.read') && user?.permissions?.includes('customers.read'));
  }

  function defaultWorkspaceScreen() {
    return ['platform', 'pipeline', 'statistics', 'conversations', 'catalog', 'offers', 'website', 'integrations', 'implementation', 'whatsapp-qr', 'usage', 'subscription', 'account'].find(mayOpenScreen) || 'account';
  }

  async function loadAccounts(selectedTenant = tenant, activeLoad = workspaceRequest()) {
    try {
    const { response, data } = await requestJson(`/admin/api/accounts?tenant=${encodeURIComponent(selectedTenant)}`, { credentials: 'same-origin' }, activeLoad);
    if (!isCurrentWorkspace(activeLoad)) return;
    accounts = response.ok && Array.isArray(data.accounts) ? data.accounts : [];
    if (!response.ok) { accountStatus = 'Team access could not load. Try refreshing.'; accountError = true; return false; }
    const selected = accounts.find((account) => account.id === selectedAccountId);
    const next = selected || accounts.find((account) => isPlatform || account.roles.includes('business_staff'));
    selectedAccountId = next?.id || '';
    selectedAccountActive = next?.active ?? true;
    selectedViewCosts = next?.permissions?.includes('view_costs') ?? false;
    selectedViewSubscriptions = next?.permissions?.includes('view_subscriptions') ?? false;
    selectedAccountPassword = '';
    return true;
    } catch {
      if (isCurrentWorkspace(activeLoad)) {
        accounts = []; selectedAccountId = '';
        accountStatus = 'Team access could not load. Check your connection and try again.';
        accountError = true;
      }
      return false;
    }
  }

  function selectManagedAccount(accountId: string) {
    selectedAccountId = accountId;
    const selected = accounts.find((account) => account.id === accountId);
    selectedAccountActive = selected?.active ?? true;
    selectedViewCosts = selected?.permissions?.includes('view_costs') ?? false;
    selectedViewSubscriptions = selected?.permissions?.includes('view_subscriptions') ?? false;
    selectedAccountPassword = '';
  }

  async function loadInsights(selectedTenant = tenant, activeLoad = workspaceRequest()) {
    insights = normalizeInsights({});
    activityStatus = 'Loading activity...';
    try {
      const { response, data } = await requestJson(`/admin/api/insights?tenant=${encodeURIComponent(selectedTenant)}&minutes=10080&limit=10`, { credentials: 'same-origin' }, activeLoad);
      if (!isCurrentWorkspace(activeLoad)) return;
      if (!response.ok) { activityStatus = 'Sales activity is currently unavailable. Try refreshing.'; return false; }
      insights = normalizeInsights(data);
      activityStatus = '';
      return true;
    } catch {
      if (isCurrentWorkspace(activeLoad)) activityStatus = 'Sales activity could not load. Check your connection and try refreshing.';
      return false;
    }
  }

  async function updateLeadStatus(leadId: string, status: LeadStatus) {
    const activeLoad = workspaceRequest();
    activityStatus = 'Updating lead...';
    const response = await fetch(apiPath(`/admin/api/leads/${encodeURIComponent(leadId)}?tenant=${encodeURIComponent(tenant)}`), {
      method: 'PUT', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }, credentials: 'same-origin', body: JSON.stringify({ status })
    });
    const data = await readJson(response);
    if (!isCurrentWorkspace(activeLoad)) return;
    if (!response.ok) {
      activityStatus = data.error || 'Could not update this lead.';
      return;
    }
    insights = { ...insights, leads: insights.leads.map((lead) => lead.lead_id === leadId ? { ...lead, status } : lead) };
    activityStatus = 'Lead updated.';
  }

  async function restoreSession() {
    const requestedTenant = new URLSearchParams(window.location.search).get('tenant');
    const validRequestedTenant = requestedTenant && /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(requestedTenant) ? requestedTenant : null;
    if (validRequestedTenant) tenant = validRequestedTenant;
    let sessionResult = await requestJson('/auth/session', { credentials: 'same-origin' });
    if (sessionResult.response.status === 401) sessionResult = await requestJson('/auth/session', { credentials: 'same-origin' });
    const { response, data } = sessionResult;
    if (!response.ok) {
      if (response.status === 401) return;
      throw new Error('session_unavailable');
    }
    user = data.user;
    mfa = data.mfa || null;
    csrf = data.csrf_token || '';
    const configuredTenant = typeof data.login_tenant === 'string' && /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(data.login_tenant) ? data.login_tenant : null;
    tenant = validRequestedTenant || user?.tenant || configuredTenant || tenant;
    if (user) {
      await loadSignedInWorkspace();
    }
  }

  function signInFailure(response: Response, data: {error?: unknown; retry_after?: unknown}, phase: 'password'|'authenticator'|'provider') {
    if (data.error === 'csrf_failed' || response.status === 403) {
      return 'Your sign-in page expired or its cookie was blocked. Reload the page, allow cookies for this site, and try again.';
    }
    if (data.error === 'sign_in_again') return 'This sign-in expired. Start again.';
    if (data.error === 'authenticator_code_reused') return 'That code has already been used. Wait for the next code in your authenticator.';
    if (data.error === 'try_again_later' || response.status === 429) {
      const seconds = typeof data.retry_after === 'number' && Number.isSafeInteger(data.retry_after) && data.retry_after > 0 ? data.retry_after : 60;
      return `Too many sign-in attempts. Try again in ${seconds} seconds.`;
    }
    if (response.status >= 500) return 'Sign-in is temporarily unavailable. Please try again shortly.';
    if (data.error === 'unknown_tenant' || data.error === 'invalid_tenant') return 'Check the company key supplied with your account and try again.';
    if (data.error === 'provider_not_configured') return 'This sign-in provider is awaiting server setup. Use your password instead.';
    if (data.error === 'invalid_credentials' && phase === 'password') return 'Sign-in details were not accepted. Check your company key, email and password.';
    return phase === 'authenticator' ? 'Code not accepted. Check your authenticator and try again.'
      : phase === 'provider' ? 'Could not start provider sign-in. Check the company key or use your password.'
      : 'Could not complete sign-in. Please try again.';
  }

  async function login() {
    if (signingIn) return;
    signingIn = true;
    loginError = '';
    try {
      let session = await requestJson('/auth/session', {credentials:'same-origin'});
      // A revoked cookie is cleared by the first request. Get a fresh anonymous
      // CSRF token before submitting credentials, without retrying the login.
      if (session.response.status === 401) {
        session = await requestJson('/auth/session', {credentials:'same-origin'});
      }
      csrf = session.data.csrf_token || '';
      if (!session.response.ok || !csrf) {
        loginError = 'Could not start a secure sign-in session. Reload the page and allow cookies for this site.';
        return;
      }
      const { response, data } = await requestJson('/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
        credentials: 'same-origin',
        body: JSON.stringify({ email, password, totp, tenant, remember_device: rememberDevice })
      });
      if (response.status === 202 && data.mfa_required) {
        mfa = data.mfa; csrf = data.csrf_token; password = ''; totp = ''; return;
      }
      if (!response.ok) {
        loginError = signInFailure(response, data, 'password');
        return;
      }
      user = data.user;
      csrf = data.csrf_token || '';
      tenant = user?.tenant || tenant;
      await loadSignedInWorkspace();
      await openDefaultWorkspace();
    } catch {
      loginError = 'Could not complete sign-in. Please try again.';
    } finally {
      signingIn = false;
    }
  }

  async function confirmMfa() {
    if (signingIn) return;
    signingIn = true;
    loginError = '';
    try {
      const { response, data } = await requestJson('/auth/mfa/confirm', {method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify({code:totp,remember_device:rememberDevice})});
      if (!response.ok) {
        loginError = signInFailure(response, data, 'authenticator');
        return;
      }
      mfa = null; totp = ''; user = data.user; csrf = data.csrf_token; tenant = user?.tenant || tenant;
      await loadSignedInWorkspace(); await openDefaultWorkspace();
    } catch {loginError = 'Could not complete sign-in. Please try again.';}
    finally {signingIn = false;}
  }

  async function restartLogin() {
    if (signingIn) return;
    signingIn = true;
    loginError = '';
    try {
      const { response } = await requestJson('/auth/logout', {method:'POST',credentials:'same-origin',headers:{'X-CSRF-Token':csrf}});
      if (!response.ok) throw new Error();
      mfa = null; totp = ''; password = ''; await restoreSession();
    } catch {loginError = 'Could not restart sign-in. Please try again.';}
    finally {signingIn = false;}
  }

  async function openDefaultWorkspace() {
    if (!user) return;
    const params = new URLSearchParams(window.location.search);
    const next = params.get('next');
    let destination = next && mayOpenScreen(next) ? next : !mayOpenScreen(section) ? defaultWorkspaceScreen() : null;
    if (!destination && user.roles.some(role=>role==='platform_admin'||role==='admin') && window.location.pathname.replace(/\/$/,'')===base) {
      destination = defaultWorkspaceScreen();
    }
    if (!destination) return;
    params.delete('next'); params.delete('oidc'); params.delete('provider');
    params.set('tenant', tenant);
    const target = base+'/'+destination+'?'+params.toString();
    // A full document load applies the widget page's microphone policy.
    if (isWidgetSection(destination) || isWidgetSection(section)) window.location.replace(target);
    else await goto(target, {replaceState:true});
  }

  async function loadProviders() {
    try {
      const { response, data } = await requestJson('/auth/oidc/providers', {credentials:'same-origin'});
      if (!response.ok) return;
      providers = Array.isArray(data.providers) ? data.providers.filter((item: {id?:string}) => item.id === 'google' || item.id === 'microsoft') : [];
    } catch { providers = []; }
  }

  async function providerLogin(provider: 'google'|'microsoft') {
    if (signingIn) return;
    signingIn = true; loginError = '';
    try {
      let session = await requestJson('/auth/session', {credentials:'same-origin'});
      if (session.response.status === 401) session = await requestJson('/auth/session', {credentials:'same-origin'});
      if (!session.response.ok || !session.data.csrf_token) throw new Error();
      csrf = session.data.csrf_token;
      const { response, data: start } = await requestJson('/auth/oidc/'+provider+'/start', {method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify({intent:'login',tenant})});
      if (!response.ok) {
        loginError = signInFailure(response, start, 'provider');
        signingIn = false;
        return;
      }
      if (typeof start.authorization_url !== 'string') throw new Error();
      const url = new URL(start.authorization_url);
      if (url.protocol !== 'https:' || !['accounts.google.com','login.microsoftonline.com'].includes(url.hostname)) throw new Error();
      window.location.assign(url.href);
    } catch {
      loginError = 'Could not start provider sign-in. Check the company key or use your password.';
      signingIn = false;
    }
  }

  async function openCompanyWorkspace(company: string, screen: string) {
    await selectTenant(company);
    const target = base+'/'+screen+'?tenant='+encodeURIComponent(company);
    if (isWidgetSection(screen) || isWidgetSection(section)) window.location.assign(target);
    else await goto(target);
  }

  async function logout() {
    clearTenantWorkspace();
    try {
      const { response } = await requestJson('/auth/logout', {
        method: 'POST', headers: { 'X-CSRF-Token': csrf }, credentials: 'same-origin'
      });
      if (!response.ok) throw new Error('sign_out_unavailable');
    } catch {
      formStatus = 'Could not sign out. Please refresh and try again.';
      formError = true;
      workspaceError = 'Could not sign out. Refresh to reload your workspace before making changes.';
      return;
    }
    user = null;
    workspaceError = '';
    tenants = [];
    clearTenantWorkspace();
    csrf = '';
    password = '';
    totp = '';
    rememberDevice = false;
    showPassword = false;
    if (isWidgetSection(section)) window.location.replace(base+'/');
    else await goto(base+'/', {replaceState:true});
  }

  async function saveWidget() {
    if (widgetSaving || !user?.permissions?.includes('business_settings.write')) return;
    const activeLoad = workspaceRequest();
    const selectedTenant = tenant;
    const sequence = ++widgetSaveSequence;
    widgetSaving = true;
    formStatus = 'Saving…';
    formError = false;
    const payload = {
      chat_title: widget.chat_title,
      assistant_name: widget.assistant_name,
      greeting: widget.greeting,
      avatar: widget.avatar,
      company_logo_url: widget.company_logo_url,
      style: widget.style,
      accent_color: widget.accent_color,
      background_color: widget.background_color,
      surface_color: widget.surface_color,
      text_color: widget.text_color,
      bubble_color: widget.bubble_color,
      allowed_origins: originText.split('\n').map((value) => value.trim()).filter(Boolean)
    };
    try {
      const { response, data } = await requestJson('/admin/api/widget?tenant='+encodeURIComponent(selectedTenant), {
        method:'PUT', headers:{ 'Content-Type':'application/json', 'X-CSRF-Token':csrf },
        credentials:'same-origin', body:JSON.stringify(payload)
      }, activeLoad);
      if (!isCurrentWorkspace(activeLoad) || sequence !== widgetSaveSequence) return;
      if (!response.ok) {
        formStatus = response.status === 401 ? 'Your session expired. Reload and sign in again.' :
          response.status === 403 ? 'Your account cannot change these widget settings.' :
          response.status === 409 ? 'Settings changed while saving. Refresh the page before trying again.' :
          response.status === 402 ? 'An active subscription is needed to save widget changes.' :
          'Could not save. Check the colour hex values, image URLs and approved website origins.';
        formError = true; return;
      }
      if (!data.widget || typeof data.widget !== 'object') throw new Error('invalid_widget_response');
      widget = normalizeWidget(data.widget);
      previewTheme = data.preview_theme || {};
      snippet = data.embed?.snippet || ''; iframeSnippet = data.embed?.iframe_snippet || ''; widgetChatUrl = data.embed?.chat_url || '';
      originText = widget.allowed_origins.join('\n'); savedWidgetFingerprint = JSON.stringify(widget);
      formStatus = 'Saved. New widget loads use these settings.';
      void loadTenants(activeLoad);
    } catch {
      if (isCurrentWorkspace(activeLoad) && sequence === widgetSaveSequence) {
        formStatus = 'Widget changes could not be saved. Check your connection and try again.'; formError = true;
      }
    } finally { if (isCurrentWorkspace(activeLoad) && sequence === widgetSaveSequence) widgetSaving = false; }
  }

  async function copySnippet() {
    await copyWidgetCode(snippet, 'Install script');
  }

  async function copyWidgetCode(code: string, label: string) {
    const activeLoad = workspaceRequest();
    try {
      await navigator.clipboard.writeText(code);
      if (isCurrentWorkspace(activeLoad)) { formStatus = label+' copied.'; formError = false; }
    } catch {
      if (isCurrentWorkspace(activeLoad)) { formStatus = 'Copy is unavailable. Select the code and copy it manually.'; formError = true; }
    }
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

  async function createAccount() {
    accountStatus = 'Creating access...';
    accountError = false;
    const response = await fetch(apiPath(`/admin/api/accounts?tenant=${encodeURIComponent(tenant)}`), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
      credentials: 'same-origin',
      body: JSON.stringify({ email: accountEmail.trim(), password: accountPassword, roles: [accountRole], permissions: [...(accountViewCosts?['view_costs']:[]),...(accountViewSubscriptions?['view_subscriptions']:[])] })
    });
    const data = await readJson(response);
    if (!response.ok) {
      accountStatus = data.error || 'Could not create access.';
      accountError = true;
      return;
    }
    accountStatus = `${data.account.email} can now sign in for ${tenant} only.`;
    accountEmail = '';
    accountPassword = '';
    accountViewCosts = false;
    accountViewSubscriptions = false;
    await loadAccounts(tenant);
  }

  async function updateAccount() {
    if (!selectedAccountId) return;
    accountStatus = 'Updating access...';
    accountError = false;
    const payload: { active: boolean; password?: string; permissions:string[] } = { active: selectedAccountActive, permissions:[...(selectedViewCosts?['view_costs']:[]),...(selectedViewSubscriptions?['view_subscriptions']:[])] };
    if (selectedAccountPassword) payload.password = selectedAccountPassword;
    const response = await fetch(apiPath(`/admin/api/accounts/${encodeURIComponent(selectedAccountId)}?tenant=${encodeURIComponent(tenant)}`), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
      credentials: 'same-origin',
      body: JSON.stringify(payload)
    });
    const data = await readJson(response);
    if (!response.ok) {
      accountStatus = data.error || 'Could not update access.';
      accountError = true;
      return;
    }
    accountStatus = `${data.account.email} access updated.`;
    selectedAccountPassword = '';
    await loadAccounts(tenant);
  }

  async function selectTenant(nextTenant: string) {
    formStatus = '';
    catalogStatus = '';
    faqStatus = '';
    offersStatus = '';
    deliveryStatus = '';
    profileStatus = '';
    branchesStatus = '';
    agentStatus = '';
    const directoryWasLoading = tenantDirectoryBusy;
    const activeLoad = beginWorkspaceLoad();
    tenant = nextTenant;
    if (directoryWasLoading) void loadTenants(activeLoad);
    await loadWorkspaceSection(section, activeLoad);
    if (!isCurrentWorkspace(activeLoad)) return;
    const url = new URL(window.location.href);
    url.searchParams.set('tenant', nextTenant);
    window.history.replaceState(window.history.state, '', url);
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
      items: [...category.items, { sku: 'NEW_OFFERING', name: 'New offering', price: 0, unit: 'each', tags: [], in_stock: true }]
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

  function addOffer() {

    offers = [...offers, { archived: false, deal_type: 'custom', minimum_spend: 0, discount_type: 'percentage', discount_value: 0, id: `offer_${crypto.randomUUID()}`, title: 'New offer', description: 'Describe the customer benefit and any conditions.', code: '', active: true, starts_on: '', ends_on: '', product_skus: [] }];
  }

  function reuseOffer(offer: Offer) {
    offers = [...offers, {...offer, id: `offer_${crypto.randomUUID()}`, archived: false, active: true, starts_on: '', ends_on: '', product_skus: [...offer.product_skus]}];
    offersStatus = 'Copy added to current offers. Review its dates and terms, then save.';
  }

  function removeOffer(index: number) {
    offers = offers.map((offer, current) => current === index ? {...offer, archived: true, active: false} : offer);
  }

  function addDeliveryRule() {
    delivery = {
      ...delivery,
      rules: [...delivery.rules, { source: {}, area: '', fee: 0, min_order: 0, eta_hours: 'Next-day', eta_min: 60 }]
    };
  }

  function removeDeliveryRule(index: number) {
    delivery = { ...delivery, rules: delivery.rules.filter((_, current) => current !== index) };
  }

  function addException() {
    delivery = { ...delivery, exceptions: [...delivery.exceptions, { source: {}, date: '', note: '' }] };
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
        tags: item.tags.map((tag) => tag.trim()).filter(Boolean),
        stock_quantity: item.stock_quantity ?? null, low_stock_threshold: item.low_stock_threshold ?? 5,
        in_stock: item.stock_quantity == null ? Boolean(item.in_stock) : item.stock_quantity > 0
      }))
    }));
    if (!categories.length || categories.some((category) => !category.name || !category.items.length || category.items.some((item) => !item.sku || !item.name || !Number.isFinite(item.price) || item.price < 0))) {
      catalogStatus = 'Each category needs a name and at least one complete offering.';
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
    catalogStatus = 'Catalogue saved. New conversations use these offerings.';
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

  async function saveOffers() {
    offersStatus = 'Saving...';
    offersError = false;
    const payload = offers.map((offer) => ({
      archived: offer.archived, deal_type: offer.deal_type,
      ...(offer.deal_type === 'minimum_spend' ? {minimum_spend: offer.minimum_spend, discount_type: offer.discount_type, discount_value: offer.discount_value} : {}),
      id: (offer.id.trim() || slug(offer.title)), title: offer.title.trim(), description: offer.description.trim(), code: offer.code.trim(), active: Boolean(offer.active),
      starts_on: offer.starts_on, ends_on: offer.ends_on, product_skus: offer.product_skus.map((sku) => sku.trim()).filter(Boolean)
    }));
    const ids = payload.map((offer) => offer.id);
    if (payload.some((offer) => (offer.deal_type === 'buy_one_get_one' && !offer.product_skus.length) || (offer.deal_type === 'minimum_spend' && (!(Number(offer.minimum_spend) > 0) || !(Number(offer.discount_value) > 0))) || !offer.title || !offer.description || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(offer.id) || (offer.starts_on && offer.ends_on && offer.starts_on > offer.ends_on)) || new Set(ids).size !== ids.length) {
      offersStatus = 'Check unique keys, titles, details, dates and required deal values or eligible products.';
      offersError = true;
      return;
    }
    const response = await fetch(apiPath(`/admin/api/offers?tenant=${encodeURIComponent(tenant)}`), {
      method: 'PUT', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }, credentials: 'same-origin', body: JSON.stringify(payload)
    });
    const data = await readJson(response);
    if (!response.ok) {
      offersStatus = data.detail || data.error || 'Could not save offers.';
      offersError = true;
      return;
    }
    offers = normalizeOffers(payload);
    offersStatus = 'Offers saved. The assistant now uses the active offers only.';
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
    const exceptions = delivery.exceptions.map((item) => ({ ...item.source, date: item.date, note: item.note.trim() })).filter((item) => item.date || item.note);
    if (exceptions.some((item) => !item.date || !item.note)) {
      deliveryStatus = 'Each delivery exception needs both a date and note.';
      deliveryError = true;
      return;
    }
    const base = { ...delivery.source, click_and_collect: delivery.click_and_collect, notes: delivery.notes.trim(), exceptions: [...delivery.preservedExceptions, ...exceptions] };
    const payload = delivery.mode === 'zones'
      ? { ...base, zones: rules.map(({ source, area, fee, min_order, eta_hours }) => ({ ...source, area, fee, min_order, eta_hours })) }
      : { ...base, areas: rules.map(({ source, area, fee, min_order, eta_min }) => ({ ...source, postcode_prefix: area, fee, min_order, eta_min })) };
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
    branches = [...branches, { source: {}, id: `branch_${number}`, name: `New branch ${number}`, address: '', postcode: '', phone: '', lat: null, lon: null, hours: emptyHours() }];
  }

  function removeBranch(index: number) {
    branches = branches.filter((_, current) => current !== index);
  }

  async function saveProfile() {
    profileStatus = 'Saving...';
    profileError = false;
    const payload = {
      name: profile.name.trim(), about: profile.about.trim(), email: profile.email.trim(), phone: profile.phone.trim(), website: profile.website.trim(),
      ...(profile.legacyHalalCertified !== undefined ? { halal_certified: profile.legacyHalalCertified } : {}),
      certifications: profile.certifications.map((item) => item.trim()).filter(Boolean),
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
      ...branch.source,
      id: branch.id.trim() || slug(branch.name), name: branch.name.trim(), address: branch.address.trim(), postcode: branch.postcode.trim(), phone: branch.phone.trim(),
      lat: branch.lat == null ? null : Number(branch.lat), lon: branch.lon == null ? null : Number(branch.lon), hours: Object.fromEntries(Object.entries(branch.hours).map(([day, hours]) => [day, hours.trim()]).filter(([, hours]) => Boolean(hours)))
    }));
    if (payload.some((branch) => !branch.id || !branch.name || !branch.postcode || (branch.lat !== null && (!Number.isFinite(branch.lat) || branch.lat < -90 || branch.lat > 90)) || (branch.lon !== null && (!Number.isFinite(branch.lon) || branch.lon < -180 || branch.lon > 180)))) {
      branchesStatus = 'Each branch needs a name and postcode. If supplied, coordinates must be valid.';
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
    agentSettings = normalizeAgentSettings(data);
    agentStatus = 'Agent playbook saved. New conversations use these settings.';
  }

  onMount(async () => {
    initialiseLanguage();
    const params = new URLSearchParams(window.location.search);
    const notices: Record<string,string> = {
      linked:'Your sign-in provider is linked to this account.',
      mfa_required:'Provider verified. Complete your authenticator check to sign in.',
      signed_in:'You are signed in with your linked provider and remembered device.',
      not_linked:'This provider account is not linked. Sign in with your password, then link it in Account & security.',
      failed:'Provider sign-in could not be completed. Start again or use your password.'
    };
    oidcNotice = notices[params.get('oidc') || ''] || '';
    params.delete('oidc'); params.delete('provider');
    window.history.replaceState(null,'',window.location.pathname+(params.size?'?'+params.toString():''));
    void loadProviders();
    try {
      await restoreSession();
      await openDefaultWorkspace();
    } catch {
      loginError = 'Could not load your sign-in session. Check your connection, reload the page and try again.';
    } finally {
      loading = false;
    }
  });
  onDestroy(() => { workspaceGeneration++; for (const controller of workspaceControllers) controller.abort(); });
</script>

<svelte:head>
  <title>{$t(pageTitle)} · V7</title>
  <meta name="description" content="Tenant widget configuration for the V7 AI sales agent." />
  <link rel="icon" type="image/svg+xml" href="/static/img/logo.svg?v=20261009svg" />
  <link rel="icon" type="image/png" sizes="96x96" href="/static/img/favicon-96.png?v=20261009svg" />
  <link rel="shortcut icon" href="/favicon.ico?v=20261009svg" />
  <link rel="apple-touch-icon" sizes="180x180" href="/static/img/apple-touch-icon.png?v=20261009svg" />
</svelte:head>

{#if loading}
  <main class="loading" aria-live="polite">Loading owner console...</main>
{:else if !user}
  <main class="login-shell">
    <section class="login-intro" aria-labelledby="welcome-title">
      <a class="login-brand" href="/" aria-label="Vertex Seven home"><PlatformLogo size={36} /><span>Vertex <strong>Seven</strong></span></a>
      <p class="eyebrow">{$t('Your business workspace')}</p>
      <h2 id="welcome-title">{$t('Customer conversations, with a clear next step.')}</h2>
      <p>{$t('Products, consultations and customer support.')} {$t('A sales assistant that knows your business.')}</p>
      <div class="intro-features"><span>{$t('Website widget')}</span><span>WhatsApp</span><span>{$t('Sales pipeline')}</span></div>
      <a href="/privacy">{$t('Privacy information')}</a>
    </section>
    <div class="login-content">
    <div class="login-tools"><LanguagePicker /></div>
    {#if signupOpen && !mfa}
      <div><Registration {csrf} apiPrefix={import.meta.env.DEV ? '/api' : ''} on:login={(event) => {tenant = event.detail.tenant; email = event.detail.email; signupOpen = false;}}/><button class="secondary" type="button" on:click={() => signupOpen = false}>{$t("Back to sign in")}</button></div>
    {:else}
    <form class="login" aria-busy={signingIn} on:submit|preventDefault={() => mfa ? confirmMfa() : login()}>
      <div class="login-logo"><PlatformLogo size={32} label="" /><span>Vertex <strong>Seven</strong></span></div>
      <h1>{$t(mfa ? mfa.enrollment ? 'Set up two-factor authentication' : 'Verify your sign-in' : 'Sign in to V7')}</h1>
      {#if oidcNotice}<p class="notice" role="status">{$t(oidcNotice)}</p>{/if}
      {#if mfa}
      <p>{mfa.email} · Every management account requires an authenticator.</p>
      {#if mfa.enrollment}
        <p>Scan this QR code in your authenticator app, then enter its six-digit code. Keep the setup key private.</p>
        <img class="mfa-qr" src={mfa.qr_image} alt="Scan to set up your V7 authenticator"/>
        <details><summary>Enter a setup key instead</summary><code class="mfa-key">{mfa.setup_key}</code></details>
      {/if}
      <label>{$t("Authenticator code")}<input disabled={signingIn} bind:value={totp} inputmode="numeric" pattern={'[0-9]{6}'} maxlength="6" autocomplete="one-time-code" required /></label>
      <button disabled={signingIn} class="secondary" type="button" on:click={restartLogin}>{$t("Start again")}</button>
      {:else}
      <p>{$t('Sign in to manage your business and customer conversations.')}</p>
      <label>{$t("Company key")}<input disabled={signingIn} bind:value={tenant} maxlength="64" autocomplete="organization" required /><span>Use the company key supplied with your account, for example EXAMPLE.</span></label>
      <label>{$t("Email or username")}<input disabled={signingIn} bind:value={email} type="text" maxlength="254" autocomplete="username" autocapitalize="none" spellcheck="false" required /></label>
      <label>{$t('Password')}<span class="password-field"><input id="login-password" disabled={signingIn} bind:value={password} type={showPassword ? 'text' : 'password'} maxlength="1024" autocomplete="current-password" required /><button disabled={signingIn} type="button" aria-controls="login-password" aria-pressed={showPassword} on:click={() => showPassword = !showPassword}>{$t(showPassword ? 'Hide password' : 'Show password')}</button></span></label>
      {/if}
      <label class="remember-choice"><input type="checkbox" disabled={signingIn} bind:checked={rememberDevice}/><span>{$t('Remember this device for 30 days')}<small>{$t('Use only on your own device. You will still need your password or linked provider account.')}</small></span></label>
      {#if loginError}<div role="alert" class="notice error">{loginError}</div>{/if}
      <button disabled={signingIn} class="primary" type="submit">{$t(signingIn ? 'Please wait…' : mfa ? 'Verify and sign in' : 'Continue')}</button>
      {#if !mfa && providers.length}
        <div class="provider-divider"><span>{$t('Or use a linked account')}</span></div>
        <div class="provider-buttons">{#each providers as provider}<button class="secondary" type="button" disabled={signingIn || !provider.configured} on:click={() => providerLogin(provider.id)}>{provider.name}</button>{/each}</div>
        <p class="provider-help">{$t('Link Google or Microsoft in Account & security after signing in.')} {#if providers.some(provider => !provider.configured)}{$t('Some providers are awaiting server setup.')}{/if}</p>
      {/if}
      {#if !mfa}<button disabled={signingIn} class="secondary" type="button" on:click={() => signupOpen = true}>{$t("Create an account or request to join")}</button>{/if}
      <p class="login-policy"><a href="/privacy">{$t('Privacy')}</a> · <a href="/cookies">{$t('Cookies')}</a> · <button class="cookie-login-trigger" type="button" aria-expanded={cookiePreferencesOpen} aria-controls={cookiePreferencesOpen ? 'workspace-cookie-preferences' : undefined} on:click={(event) => cookiePreferences?.showPreferences(event.currentTarget)}>{$t('Cookie preferences')}</button></p>
    </form>
    {/if}
    </div>
  </main>
{:else}
  <a class="skip-link" href="#workspace">{$t('Skip to workspace')}</a>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="side-brand"><PlatformLogo size={32} /><div><strong>Vertex Seven</strong><small>{isPlatform ? 'Platform workspace' : 'Business workspace'}</small></div></div>
      <button class="secondary menu-toggle" type="button" aria-expanded={navigationOpen} aria-controls="console-navigation" on:click={() => navigationOpen = !navigationOpen}>{$t("Menu")}</button>
      <nav id="console-navigation" class:open={navigationOpen} aria-label="Owner console navigation">
        {#each navigationGroups as group}
          {#if group.keys.some(mayOpenScreen)}
            <div class="nav-section" role="group" aria-labelledby={`console-nav-${group.id}`}>
              <h2 class="nav-group" id={`console-nav-${group.id}`}>{$t(isPlatform && group.id === 'businesses' ? 'Platform management' : group.label)}</h2>
              {#each group.keys as key}
                {#if mayOpenScreen(key)}
                  <a class:active={section === key || (key === 'website' && isWidgetSection(section))} aria-current={section === key || (key === 'website' && isWidgetSection(section)) ? 'page' : undefined} href={base+'/'+key+'?tenant='+encodeURIComponent(tenant)} data-sveltekit-reload={isWidgetSection(key) || isWidgetSection(section) ? true : undefined} on:click={() => navigationOpen = false}><NavigationIcon section={key}/><span>{$t(sections[key])}</span></a>
                {/if}
              {/each}
              {#if group.id === 'account'}
                <button class="cookie-nav-trigger" type="button" aria-expanded={cookiePreferencesOpen} aria-controls={cookiePreferencesOpen ? 'workspace-cookie-preferences' : undefined} on:click={(event) => cookiePreferences?.showPreferences(event.currentTarget)}><NavigationIcon section="privacy"/><span>{$t('Cookie preferences')}</span></button>
              {/if}
            </div>
          {/if}
        {/each}
      </nav>
      <div class="account"><span class="account-avatar" aria-hidden="true">{user.email.charAt(0).toUpperCase() || 'V'}</span><div><strong>{user.email}</strong><span>{isPlatform ? 'Platform operator' : user.roles.includes('business_owner') ? 'Business owner' : 'Business staff'}</span></div></div>
    </aside>

    <main id="workspace" class="workspace" tabindex="-1">
      <header class="workspace-head">
        <div class="workspace-title"><p class="eyebrow">{$t(isPlatform ? 'Platform workspace' : 'Business workspace')}</p><h1>{$t(pageTitle)}</h1>{#if pageDescriptions[section]}<p class="page-description">{$t(pageDescriptions[section])}</p>{/if}</div>
        <div class="workspace-actions">
          <LanguagePicker />
        {#if (isPlatform || isOwner) && tenants.length > 0 && !['platform','companies'].includes(section)}
          <label class="tenant-picker">{$t("Company")}<select value={tenant} on:change={(event) => selectTenant(event.currentTarget.value)}>{#each tenants as item}<option value={item.key}>{item.name}</option>{/each}</select></label>
        {:else if !isPlatform}
          <div class="company-scope"><span>{$t("Company")}</span><strong>{tenant}</strong><small>Your account is restricted to this company.</small></div>
        {/if}
          <button class="secondary sign-out" type="button" on:click={logout}>{$t("Sign out")}</button>
        </div>
      </header>

      {#if tenantDirectoryError}
        <div class="workspace-retry notice error"><p role="alert">{tenantDirectoryError}</p><button class="secondary" type="button" disabled={tenantDirectoryBusy} on:click={retryTenantDirectory}>{$t(tenantDirectoryBusy ? 'Please wait…' : 'Retry company list')}</button></div>
      {/if}

      {#if workspaceBusy}
        <div class="workspace-progress" role="status"><span class="loading-indicator" aria-hidden="true"></span><span>Loading {$t(pageTitle).toLowerCase()}…</span></div>
      {:else if workspaceError}
        <div class="workspace-retry notice error"><p role="alert">{workspaceError}</p><button class="secondary" type="button" on:click={retryWorkspace}>Try again</button></div>
      {/if}

      <fieldset class="workspace-content" disabled={workspaceBusy || Boolean(workspaceError)} aria-busy={workspaceBusy}>
      <legend class="sr-only">{$t(pageTitle)}</legend>
      {#if activation && !activation.active}
        <section class="activation-notice" aria-label="Business activation"><span class="activation-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><rect x="5" y="10" width="14" height="11" rx="3"/><path d="M8 10V7a4 4 0 0 1 8 0v3 M12 14v3"/></svg></span><div><strong>Business awaiting activation</strong><p>Business data editing and the agent unlock after Stripe confirms both the platform subscription and the one-time implementation payment.</p></div>{#if canViewSubscriptions}<a href={base+'/subscription?tenant='+encodeURIComponent(tenant)}>Open subscriptions <span aria-hidden="true">↗</span></a>{/if}</section>
      {/if}

      {#if !mayOpenScreen(section)}
        <section class="surface"><div class="surface-body"><h2>{$t('Access restricted')}</h2><p>{$t('This account cannot open this workspace section.')}</p><a href={base+'/'+defaultWorkspaceScreen()+'?tenant='+encodeURIComponent(tenant)}>{$t('Open your workspace')}</a></div></section>
      {:else if !isPlatform && activation && !activation.active && !['subscription','companies','account','privacy'].includes(section)}
        <section class="surface"><div class="surface-body"><h2>Activate your business</h2><p>Complete payment in Subscription to add business data and manage team access.</p></div></section>
      {:else}
      {#if oidcNotice}<p class="notice" role="status">{$t(oidcNotice)}</p>{/if}
      {#if section === 'account'}<AccountSecurity {tenant} {csrf} apiPrefix={import.meta.env.DEV ? '/api' : ''}/>{/if}
      {#if section === 'privacy'}{#key tenant}<PrivacySettings {tenant} {csrf} canEdit={isPlatform || isOwner} apiPrefix={import.meta.env.DEV ? '/api' : ''}/>{/key}{/if}
      {#if section === 'agent' && mayReadModelParameters()}{#key tenant}<AiParameters {tenant} {csrf} apiPrefix={import.meta.env.DEV ? '/api' : ''}/>{/key}{/if}
      {#if section === 'platform'}
        {#if isPlatform}<PlatformOverview apiPrefix={import.meta.env.DEV ? '/api' : ''} on:open={(event)=>openCompanyWorkspace(event.detail.tenant,event.detail.section)}/>
        {:else}<section class="surface"><div class="surface-body"><p>This page is available only to the platform administrator. Your account manages {tenant}.</p><a href={base+'/pipeline'}>Open your company workspace</a></div></section>{/if}
      {/if}

      {#if section === 'subscription'}
        {#if canViewSubscriptions}{#key tenant}<Subscription {tenant} {csrf} {isPlatform} canManageBilling={isPlatform||isOwner} {canViewCosts} apiPrefix={import.meta.env.DEV ? '/api' : ''} on:company={(event)=>selectTenant(event.detail)}/>{/key}
        {:else}<section class="surface"><div class="surface-body"><p>Your business owner must grant permission to view subscriptions.</p></div></section>{/if}
      {/if}

      {#if section === 'conversations'}
        <Conversations {tenant} apiPrefix={import.meta.env.DEV ? '/api' : ''} />
      {/if}
      {#if section === 'usage'}
        {#if canViewCosts}
          {#key tenant}<ApiUsage {tenant} {csrf} {isPlatform} apiPrefix={import.meta.env.DEV ? '/api' : ''} />{/key}
        {:else}
          <section class="surface"><div class="surface-body"><p>Your business owner must grant permission to view API usage and costs.</p></div></section>
        {/if}
      {/if}
      {#if isWidgetSection(section)}
        <section class="widget-workspace" aria-label="Website widget workspace">
          <div class="widget-workspace-intro"><div><p class="eyebrow">Customer experience</p><h2>One place to build, test and install</h2><p>Shape your chat for {tenant}, check your agent's answers and connect your website.</p></div><a href={'/chat_ui?tenant='+encodeURIComponent(tenant)} target="_blank" rel="noopener noreferrer">Open saved widget ↗</a></div>
          <div class="widget-workspace-tabs" role="group" aria-label="Widget workspace views">
            <button class:active={widgetView === 'appearance'} aria-pressed={widgetView === 'appearance'} on:click={() => widgetView = 'appearance'}>Appearance</button>
            <button class:active={widgetView === 'test'} aria-pressed={widgetView === 'test'} on:click={() => widgetView = 'test'}>Test conversation</button>
            <button class:active={widgetView === 'install'} aria-pressed={widgetView === 'install'} on:click={() => widgetView = 'install'}>Website installation</button>
            {#if widgetDirty}<span>Unsaved widget changes</span>{/if}
          </div>
          {#if widgetView === 'appearance'}
            {#key tenant}<WidgetDesigner {tenant} {previewTheme} bind:widget saving={widgetSaving} canEdit={canEditWidget} dirty={widgetDirty} status={formStatus} error={formError} on:save={saveWidget}/>{/key}
          {:else if widgetView === 'test'}
            {#if widgetDirty}<p class="widget-save-notice">Your appearance changes are not saved yet. The agent test uses saved business information. <button on:click={() => widgetView = 'appearance'}>Review appearance</button></p>{/if}
            {#key tenant}<AgentTest {tenant} {csrf} apiPrefix={import.meta.env.DEV ? '/api' : ''} />{/key}
            <details class="widget-extra"><summary>Website knowledge</summary>{#key tenant}<WebsiteKnowledge {tenant} {csrf} canEdit={canEditWidget} profileWebsite={profile.website} apiPrefix={import.meta.env.DEV ? '/api' : ''} />{/key}</details>
            {#if mayReadConversionSettings()}<details class="widget-extra"><summary>Booking, quote and payment paths</summary>{#key tenant}<ConversionSettings {tenant} {csrf} canEdit={canEditWidget} apiPrefix={import.meta.env.DEV ? '/api' : ''} />{/key}</details>{/if}
          {:else}
            <div class="widget-install-grid">
              <section class="surface"><div class="surface-head"><div><p class="eyebrow">Website access</p><h2>Approve your websites</h2><p>Only approved website origins can host this company's chat.</p></div></div><form class="settings-form" on:submit|preventDefault={saveWidget}><label>Approved website origins<textarea bind:value={originText} class="origins" rows="5" disabled={!canEditWidget || widgetSaving} spellcheck="false" placeholder="https://www.yourcompany.com&#10;https://shop.yourcompany.com"></textarea><small>One exact origin per line. HTTPS is required except for local development. Include www and other subdomains separately. Leave blank to block external embedding.</small></label><div class="form-footer"><span class:error={formError} class="form-status" role={formError ? 'alert' : 'status'}>{formStatus}</span><button class="primary" type="submit" disabled={!canEditWidget || widgetSaving}>{widgetSaving ? 'Saving…' : 'Save widget & websites'}</button></div></form></section>
              <section class="surface"><div class="surface-head"><div><p class="eyebrow">Ready to install</p><h2>Add chat to your site</h2><p>Use the saved settings for {tenant}.</p></div></div><div class="surface-body widget-install-tools"><label>Installation type<select bind:value={installationFormat}><option value="floating">Floating chat button</option><option value="panel">Embedded chat panel</option><option value="link">Direct chat link</option></select></label><label>Company installation code<textarea class="code" readonly value={installationCode} rows="6" spellcheck="false"></textarea></label><button class="secondary" on:click={() => copyWidgetCode(installationCode,installationFormat === 'link' ? 'Chat link' : 'Installation code')} disabled={!installationCode}>Copy {installationFormat === 'link' ? 'link' : 'code'}</button><p>{installationFormat === 'floating' ? 'Add this script once before the closing body tag.' : installationFormat === 'panel' ? 'Place this iframe in the part of your page where chat should appear.' : 'Use this URL for a chat button or share it directly with customers.'} Save changes, then reload the installed widget to check them.</p>{#if widgetDirty}<p class="widget-save-notice">Save your widget changes before checking the installed appearance.</p>{/if}{#if mayOpenScreen('implementation')}<a href={base+'/implementation?tenant='+encodeURIComponent(tenant)} data-sveltekit-reload>Website builder instructions and launch checklist ↗</a>{/if}<p class="field-note">Microphone use needs HTTPS, customer permission and a supported browser. Embedded chat also follows the host website's microphone policy. Public chat tests count as customer activity.</p></div></section>
            </div>
          {/if}
        </section>
      {/if}
      {#if section === 'implementation'}
        {#key tenant}<Implementation {tenant} apiPrefix={import.meta.env.DEV ? '/api' : ''} />{/key}
      {/if}

      {#if section === 'statistics'}
        {#key tenant}<Statistics {tenant} {csrf} canRecordSales={isPlatform || user.roles.includes('business_owner')} apiPrefix={import.meta.env.DEV ? '/api' : ''} />{/key}
      {/if}
      {#if section === 'whatsapp-qr'}
        {#key tenant}<WhatsAppQr {tenant} {csrf} apiPrefix={import.meta.env.DEV ? '/api' : ''} />{/key}
      {/if}

      {#if section === 'companies' && (isPlatform || isOwner)}
        <section class="operator-panel" aria-labelledby="tenant-create-heading">
          <div><p class="eyebrow">Business onboarding</p><h2 id="tenant-create-heading">Add a business</h2><p>Fill in its information and configure the agent before launch. Each new business activates automatically after its subscription and implementation are paid. It starts with empty business knowledge and no approved websites. Add only information belonging to this business.</p></div>
          <form class="tenant-form" on:submit|preventDefault={createTenant}>
            <label>Tenant key<input bind:value={newTenantKey} placeholder="NORTHSTAR" pattern={'[A-Za-z0-9_-]{1,64}'} required /></label>
            <label>Business name<input bind:value={newTenantName} placeholder="Northstar Homewares" required /></label>
            <button class="primary" type="submit">Create tenant</button>
          </form>
          {#if createStatus}<p class="form-status">{createStatus}</p>{/if}
        </section>
      {/if}

      {#if section === 'pipeline'}
      <section id="activity" class="surface workspace-section activity" aria-labelledby="activity-heading">
        <div class="surface-head pipeline-head"><div><p class="eyebrow">{$t("Sales pipeline")}</p><h2 id="activity-heading">Follow-up queue</h2></div><button class="secondary" type="button" on:click={() => loadInsights(tenant)}>{$t("Refresh")}</button></div>
        <div class="metric-grid" aria-label="Sales pipeline summary">
          <div><span>Active leads</span><strong>{insights.sales_funnel.active}</strong><small>Current pipeline</small></div>
          <div><span>Qualified</span><strong>{insights.sales_funnel.qualified}</strong><small>Ready for follow-up</small></div>
          <div><span>Won</span><strong>{insights.sales_funnel.won}</strong><small>Recorded outcomes</small></div>
          <div><span>Requested a person</span><strong>{insights.sales_funnel.handoffs}</strong><small>Last 7 days</small></div>
        </div>
        <div class="funnel-strip" aria-label="Current lead stages">
          <div><span>Open</span><strong>{insights.sales_funnel.open}</strong></div>
          <div><span>Contacted</span><strong>{insights.sales_funnel.contacted}</strong></div>
          <div><span>Qualified</span><strong>{insights.sales_funnel.qualified}</strong></div>
          <div><span>Won</span><strong>{insights.sales_funnel.won}</strong></div>
          <div><span>Lost</span><strong>{insights.sales_funnel.lost}</strong></div>
        </div>
        <div class="activity-details">
          <div class="activity-list">
            <div class="list-heading"><h3>Recent leads</h3><span>{insights.sales_funnel.contacts_captured} contacts shared in 7d</span></div>
            {#each insights.leads as lead}
              <div class="lead-row"><div><strong>{lead.name || lead.phone || 'Contact details not supplied'}</strong><span>{lead.name && lead.phone ? lead.phone : `Conversation ${lead.lead_id.slice(-8) || 'pending'}`}</span></div><div><select value={lead.status} disabled={!user.permissions?.includes('customers.read')} aria-label={`Status for ${lead.name || lead.phone || 'lead'}`} on:change={(event) => updateLeadStatus(lead.lead_id, event.currentTarget.value as LeadStatus)}>{#each leadStatuses as status}<option value={status}>{status}</option>{/each}</select><time datetime={lead.updated_utc}>{formatActivityDate(lead.updated_utc)}</time></div></div>
            {:else}
              <p class="empty-state">New customer conversations will appear here.</p>
            {/each}
          </div>
          <div class="activity-list">
            <div class="list-heading"><h3>Conversation topics</h3><span>Last 7 days</span></div>
            {#each insights.top_intents as item}
              <div class="intent-row"><span>{item.label.replaceAll('_', ' ')}</span><strong>{item.count}</strong></div>
            {:else}
              <p class="empty-state">Topics will appear after customer conversations.</p>
            {/each}
          </div>
        </div>
        {#if activityStatus}<p class="activity-status" role="status">{activityStatus}</p>{/if}
      </section>
      {/if}

      {#if canManageAccounts}
        {#if section === 'team'}
      {#key tenant}<JoinRequests {tenant} {csrf} apiPrefix={import.meta.env.DEV ? '/api' : ''}/>{/key}
      <section id="team" class="surface workspace-section" aria-labelledby="team-heading">
          <div class="surface-head"><div><p class="eyebrow">Account access</p><h2 id="team-heading">Team</h2></div><span class="count-label">{accounts.length} accounts</span></div>
          <div class="surface-body"><p>Accounts added here belong to <strong>{tenant}</strong>. Owners can also manage businesses they create. Staff stay within their assigned company. All accounts require authenticator 2FA. {isPlatform ? 'Choose Business owner to create a separate owner login.' : 'You can add staff and grant view permissions for this business.'}</p></div>
          <form class="team-form" on:submit|preventDefault={createAccount}>
            <label>{$t("Email")}<input bind:value={accountEmail} type="email" autocomplete="email" required /></label>
            {#if isPlatform}
              <label>Access level<select bind:value={accountRole}><option value="business_owner">{$t("Business owner")}</option><option value="business_staff">{$t("Business staff")}</option></select></label>
            {:else}
              <label>Access level<input value="Business staff" readonly aria-readonly="true" /></label>
            {/if}
            <label>Temporary password<input bind:value={accountPassword} type="password" minlength="12" maxlength="256" autocomplete="new-password" required /></label>
            {#if accountRole==='business_staff'}<label class="account-active"><input type="checkbox" bind:checked={accountViewCosts}/><span>View API costs</span></label><label class="account-active"><input type="checkbox" bind:checked={accountViewSubscriptions}/><span>View subscriptions (read only)</span></label>{/if}
            <button class="primary" type="submit">Add access</button>
          </form>
          {#if accounts.some((account) => isPlatform || account.roles.includes('business_staff'))}
            <form class="account-control-form" on:submit|preventDefault={updateAccount}>
              <label>Account<select value={selectedAccountId} on:change={(event) => selectManagedAccount(event.currentTarget.value)}>{#each accounts.filter((account) => isPlatform || account.roles.includes('business_staff')) as account}<option value={account.id}>{account.email}</option>{/each}</select></label>
              <label>New password <span>Optional</span><input bind:value={selectedAccountPassword} type="password" minlength="12" maxlength="256" autocomplete="new-password" /></label>
              <label class="account-active"><input bind:checked={selectedAccountActive} type="checkbox" /><span>Account active</span></label>
              {#if accounts.find(account=>account.id===selectedAccountId)?.roles.includes('business_staff')}<label class="account-active"><input type="checkbox" bind:checked={selectedViewCosts}/><span>View API costs</span></label><label class="account-active"><input type="checkbox" bind:checked={selectedViewSubscriptions}/><span>View subscriptions (read only)</span></label>{/if}
              <button class="secondary" type="submit">Update access</button>
            </form>
          {/if}
          <div class="account-list" aria-live="polite">
            {#each accounts as account}
              <div class="account-row"><strong>{account.email}</strong><span>{account.roles.includes('business_owner') ? 'Business owner' : 'Business staff'}</span><span class:account-inactive={!account.active}>{account.active ? 'Active' : 'Inactive'}</span></div>
            {:else}
              <p class="empty-state">No team access has been added for this business.</p>
            {/each}
          </div>
          {#if accountStatus}<p class:error={accountError} class="form-status team-status">{accountStatus}</p>{/if}
        </section>
      {/if}
      {/if}

      <div class="content-grid">
        {#if section === 'integrations'}
      {#key tenant}<ConnectionSettings {tenant} {csrf} apiPrefix={import.meta.env.DEV ? '/api' : ''}/>{/key}
      <section id="install" class="surface install" aria-labelledby="install-heading">
          <div class="surface-head"><div><p class="eyebrow">Website integration</p><h2 id="install-heading">Install script</h2></div><button class="secondary" type="button" on:click={copySnippet} disabled={!snippet}>Copy</button></div>
          <div class="surface-body">
          <p><a href={base+'/implementation'}>Open the step-by-step Implementation guide</a> for your website builder, installation code and launch checks.</p>
          <p>Place this once before the closing body tag on an approved website.</p>
          <p><a href={`${base}/integrations?tenant=${encodeURIComponent(tenant)}`}>WhatsApp setup and connection status</a>. Web chat works while WhatsApp is awaiting setup.</p>
          <textarea class="code" readonly value={snippet} aria-label="Website install script"></textarea>
          {#if formStatus}<p role="status" class:error={formError}>{formStatus}</p>{/if}
          <div class="allowlist"><h3>Approved origins</h3>{#if widget.allowed_origins.length}{#each widget.allowed_origins as origin}<code>{origin}</code>{/each}{:else}<p>No website is approved yet.</p>{/if}</div>
          </div>
        </section>
      {/if}
      </div>

      {#if section === 'catalog'}
      <section id="catalog" class="surface workspace-section" aria-labelledby="catalog-heading">
        <div class="surface-head"><div><p class="eyebrow">Sales knowledge</p><h2 id="catalog-heading">{$t("Catalogue")}</h2></div><span class="count-label">{catalog.categories.length} categories</span></div>
        <div class="catalog-toolbar">
          <label>Currency<input class="currency" bind:value={catalog.currency} maxlength="3" aria-label="Catalog currency" /></label>
          <button class="secondary" type="button" on:click={addCategory}>Add category</button>
        </div>
        {#each catalog.categories as category, categoryIndex}
          <section class="editor-group" aria-label={`Category ${category.name || categoryIndex + 1}`}>
            <div class="group-heading">
              <div class="category-fields"><label>Category name<input bind:value={category.name} required /></label><label>Category key<input bind:value={category.id} required /></label></div>
              <button class="icon-button danger" type="button" title="Remove category" aria-label={`Remove ${category.name || 'category'}`} on:click={() => removeCategory(categoryIndex)}>{$t("Remove")}</button>
            </div>
            <div class="product-table" role="region" aria-label={`${category.name || 'Category'} offerings`}>
              <div class="product-table-head" aria-hidden="true"><span>Offering</span><span>Reference</span><span>{$t("Price")}</span><span>Unit</span><span>Tags</span><span>Availability</span><span></span></div>
              {#each category.items as item, itemIndex}
                <div class="product-row">
                  <input bind:value={item.name} aria-label="Offering name" required />
                  <input bind:value={item.sku} aria-label="Offering reference" required />
                  <input bind:value={item.price} type="number" min="0" step="0.01" aria-label="Offering price" required />
                  <input bind:value={item.unit} aria-label="Offering unit" required />
                  <input value={item.tags.join(', ')} on:input={(event) => (item.tags = event.currentTarget.value.split(',').map((tag) => tag.trim()).filter(Boolean))} aria-label="Offering tags" placeholder="gift, summer" />
                  <label class="stock-toggle"><input checked={item.stock_quantity == null ? item.in_stock : item.stock_quantity > 0} on:change={(event)=>item.in_stock=event.currentTarget.checked} disabled={item.stock_quantity != null} type="checkbox" /><span>{(item.stock_quantity == null ? item.in_stock : item.stock_quantity > 0) ? (agentSettings.playbook.offering_type === 'products' ? 'In stock' : 'Available') : (agentSettings.playbook.offering_type === 'products' ? 'Out' : 'Unavailable')}</span></label>
                  <button class="icon-button danger" type="button" title="Remove offering" aria-label={`Remove ${item.name || 'offering'}`} on:click={() => removeProduct(categoryIndex, itemIndex)}>{$t("Remove")}</button>
                </div>
                <div class="inventory-fields">
                  <label>Stock quantity · {item.name}<input bind:value={item.stock_quantity} type="number" min="0" max="1000000000" step="any" placeholder="Not counted" /></label>
                  <label>Low-stock alert at<input bind:value={item.low_stock_threshold} type="number" min="0" max="1000000000" step="any" placeholder="5" /></label>
                  <p>Use {item.unit || 'catalogue'} units. Leave quantity blank if untracked. A saved quantity of zero marks this offering unavailable.</p>
                </div>
              {/each}
            </div>
            <button class="add-row" type="button" on:click={() => addProduct(categoryIndex)}>Add offering</button>
          </section>
        {/each}
        <div class="section-footer"><span class:error={catalogError} class="form-status">{catalogStatus}</span><button class="primary" type="button" on:click={saveCatalog}>{$t("Save catalog")}</button></div>
      </section>
      {/if}

      {#if section === 'offers'}
      <section id="offers" class="surface workspace-section" aria-labelledby="offers-heading">
        <div class="surface-head"><div><p class="eyebrow">Sales conversion</p><h2 id="offers-heading">Current offers</h2></div><button class="secondary" type="button" on:click={addOffer}>Add offer</button></div>
        <div class="offers-list">
          {#each offers as offer, index}
            {#if !previousOffer(offer)}
            <section class="offer-editor" aria-label={`Offer ${offer.title || index + 1}`}>
              <div class="offer-heading"><h3>{offer.title || `Offer ${index + 1}`}</h3><button class="icon-button danger" type="button" title="Archive offer" aria-label={`Archive ${offer.title || 'offer'}`} on:click={() => removeOffer(index)}>Archive</button></div>
              <div class="offer-fields"><label>Offer title<input bind:value={offer.title} maxlength="120" required /></label><label>Offer key<input bind:value={offer.id} maxlength="64" required /></label><label>Offer code<input bind:value={offer.code} maxlength="64" placeholder="WELCOME10" /></label><label class="offer-toggle"><input bind:checked={offer.active} type="checkbox" /><span>Offer is active</span></label><label>Starts on<input bind:value={offer.starts_on} type="date" /></label><label>Ends on<input bind:value={offer.ends_on} type="date" /></label><label>Deal type<select bind:value={offer.deal_type}><option value="custom">Custom promotion</option><option value="buy_one_get_one">Buy 1 get 1 free</option><option value="minimum_spend">Minimum-spend deal</option></select></label>
                {#if offer.deal_type === 'buy_one_get_one'}<p class="wide-field">Buy one eligible item and receive one of the same item free. Select the eligible catalogue references below.</p>{/if}
                {#if offer.deal_type === 'minimum_spend'}<label>Minimum spend (GBP)<input type="number" min="0.01" max="1000000" step="0.01" bind:value={offer.minimum_spend}/></label><label>Reward<select bind:value={offer.discount_type}><option value="percentage">Percentage off</option><option value="fixed">GBP off</option></select></label><label>Discount value<input type="number" min="0.01" max={offer.discount_type === 'percentage' ? 100 : offer.minimum_spend} step="0.01" bind:value={offer.discount_value}/></label><p class="wide-field">The minimum spend and discount apply to the eligible items, or the whole order when no references are selected.</p>{/if}
                <label class="wide-field">Eligible catalogue references<input value={offer.product_skus.join(', ')} on:input={(event) => (offer.product_skus = event.currentTarget.value.split(',').map((sku) => sku.trim()).filter(Boolean))} placeholder="Leave blank when the offer applies to all offerings" /></label><label class="wide-field">Customer-facing details<textarea bind:value={offer.description} maxlength="600" required></textarea></label></div>
            </section>
            {/if}
          {:else}
            <div class="surface-body"><p class="empty-state">No offers have been added. Add an offer when you are ready to run a promotion.</p></div>
          {/each}
        </div>
        <div class="surface-body"><h3>Previous offers</h3><p>Expired and archived promotions stay here. Archive and save an offer to keep its details. To run it again, create a new offer with a new key.</p>
          {#each offers.filter(previousOffer) as offer}<article class="offer-editor"><h4>{offer.title} · {offer.archived ? 'Archived' : 'Expired'}</h4><p>{offer.description}</p><p>{offer.deal_type === 'buy_one_get_one' ? 'Buy 1 get 1 free (same item)' : offer.deal_type === 'minimum_spend' ? `Spend GBP ${offer.minimum_spend}: ${offer.discount_value}${offer.discount_type === 'percentage' ? '%' : ' GBP'} off` : 'Custom promotion'}</p><p>{offer.starts_on || 'No start date'} – {offer.ends_on || 'No end date'} · {offer.code || 'No code'} · {offer.product_skus.join(', ') || 'All offerings'}</p><button class="secondary" type="button" on:click={() => reuseOffer(offer)}>Reuse as new offer</button>{#if !offer.archived}<button class="secondary" type="button" on:click={() => removeOffer(offers.indexOf(offer))}>Archive expired offer</button>{/if}</article>{:else}<p>No previous offers saved.</p>{/each}
        </div>
        <div class="section-footer"><span class:error={offersError} class="form-status">{offersStatus}</span><button class="primary" type="button" on:click={saveOffers}>{$t("Save offers")}</button></div>
      </section>
      {/if}

      <div class="management-grid">
        {#if section === 'faqs'}
      <section id="faqs" class="surface workspace-section" aria-labelledby="faq-heading">
          <div class="surface-head"><div><p class="eyebrow">Sales knowledge</p><h2 id="faq-heading">Frequently asked questions</h2></div><button class="secondary" type="button" on:click={addFaq}>Add FAQ</button></div>
          <div class="faq-list">
            {#each faqs as faq, index}
              <div class="faq-editor">
                <label>Question<input bind:value={faq.q} required /></label>
                <label>Answer<textarea bind:value={faq.a} required></textarea></label>
                <div class="row-actions"><label>Topics<input value={faq.tags.join(', ')} on:input={(event) => (faq.tags = event.currentTarget.value.split(',').map((tag) => tag.trim()).filter(Boolean))} placeholder="delivery, opening hours" /></label><button class="icon-button danger" type="button" title="Remove FAQ" aria-label={`Remove FAQ ${index + 1}`} on:click={() => removeFaq(index)}>{$t("Remove")}</button></div>
              </div>
            {:else}
              <p class="empty-state">No FAQs yet. Add the answers customers ask for most.</p>
            {/each}
          </div>
          <div class="section-footer"><span class:error={faqError} class="form-status">{faqStatus}</span><button class="primary" type="button" on:click={saveFaqs}>{$t("Save FAQs")}</button></div>
        </section>
      {/if}

        {#if section === 'delivery'}
      <section id="delivery" class="surface workspace-section" aria-labelledby="delivery-heading">
          <div class="surface-head"><div><p class="eyebrow">Sales fulfillment</p><h2 id="delivery-heading">Delivery settings</h2></div><button class="secondary" type="button" on:click={addDeliveryRule}>Add delivery area</button></div>
          <div class="delivery-content">
            <label>Delivery notes<textarea bind:value={delivery.notes} placeholder="Tell customers about free delivery, ordering cutoffs, or collection."></textarea></label>
            <label class="collection-toggle"><input bind:checked={delivery.click_and_collect} type="checkbox" /><span>Click and collect is available</span></label>
            <p class="field-note">Set the postcodes you serve, the delivery charge and when customers can expect their order.</p>
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
                <button class="icon-button danger" type="button" title="Remove delivery area" aria-label={`Remove delivery area ${index + 1}`} on:click={() => removeDeliveryRule(index)}>{$t("Remove")}</button>
              </div>
            {:else}
              <p class="empty-state">No delivery areas have been added.</p>
            {/each}
            <div class="exception-heading"><h3>Service exceptions</h3><button class="add-row" type="button" on:click={addException}>Add exception</button></div>
            {#if delivery.preservedExceptions.length}
              <p class="field-note">{delivery.preservedExceptions.length} postcode-specific delivery exceptions also apply and will be kept when you save.</p>
            {/if}
            {#each delivery.exceptions as exception, index}
              <div class="exception-row"><label>Date<input bind:value={exception.date} type="date" required /></label><label>Customer message{#if exception.source.postcode}<small>Applies to {String(exception.source.postcode)}</small>{/if}<input bind:value={exception.note} required /></label><button class="icon-button danger" type="button" title="Remove exception" aria-label={`Remove exception ${index + 1}`} on:click={() => removeException(index)}>{$t("Remove")}</button></div>
            {/each}
          </div>
          <div class="section-footer"><span class:error={deliveryError} class="form-status">{deliveryStatus}</span><button class="primary" type="button" on:click={saveDelivery}>Save delivery settings</button></div>
        </section>
      {/if}
      </div>

      <div class="management-grid business-grid">
        {#if section === 'profile'}
      <section id="profile" class="surface workspace-section" aria-labelledby="profile-heading">
          <div class="surface-head"><div><p class="eyebrow">Business knowledge</p><h2 id="profile-heading">{$t("Business profile")}</h2></div></div>
          <form class="profile-form" on:submit|preventDefault={saveProfile}>
            <label class="profile-wide">Business name<input bind:value={profile.name} maxlength="120" required /></label>
            <label class="profile-wide">About the business<textarea bind:value={profile.about} maxlength="1200" placeholder="What does your business do, and how do you help customers?"></textarea></label>
            <div class="two-fields"><label>Customer email<input bind:value={profile.email} type="email" /></label><label>{$t("Phone")}<input bind:value={profile.phone} type="tel" /></label></div>
            <label>{$t("Website")}<input bind:value={profile.website} type="url" placeholder="https://www.yourcompany.com" /><small>Save this URL, then import its public pages in Website widget → Test conversation. Add prices, availability and other critical facts to your offerings and business settings.</small></label>
            <label>Certifications<input value={profile.certifications.join(', ')} on:input={(event) => (profile.certifications = event.currentTarget.value.split(',').map((item) => item.trim()).filter(Boolean))} placeholder="B Corp, ISO 9001" /></label>
            <div class="two-fields"><label>Instagram<input bind:value={profile.social.instagram} type="url" placeholder="https://instagram.com/yourcompany" /></label><label>Facebook<input bind:value={profile.social.facebook} type="url" placeholder="https://facebook.com/yourcompany" /></label></div>
            <div class="section-footer profile-footer"><span class:error={profileError} class="form-status">{profileStatus}</span><button class="primary" type="submit">{$t("Save profile")}</button></div>
          </form>
        </section>
      {/if}

        {#if section === 'agent'}
      <section id="agent" class="surface workspace-section" aria-labelledby="agent-heading">
          <div class="surface-head"><div><p class="eyebrow">Agent behavior</p><h2 id="agent-heading">Sales playbook</h2></div></div>
          <form class="agent-form" on:submit|preventDefault={saveAgentSettings}>
            <div class="agent-starter">
              <div><h3>Start with your business model</h3><p>Apply a starter, then tailor every setting. It sets the model, catalogue type, goal and fulfilment. Your written details and guidance stay unchanged; questions are added only when none exist.</p></div>
              <div class="agent-starter-controls"><label>Starter profile<select bind:value={selectedAgentStarter}>{#each Object.entries(agentStarters) as [key, starter]}<option value={key}>{starter.label}</option>{/each}</select></label><button class="secondary" type="button" on:click={applyAgentStarter}>Apply starter</button></div>
              <small>Starters do not add products, prices or business claims. Review your settings and save when ready.</small>
            </div>
            <div class="agent-settings-grid">
              <label>Business model<select bind:value={agentSettings.playbook.business_model}><option value="general">General business</option>{#each Object.entries(agentStarters) as [key, starter]}<option value={key}>{starter.label}</option>{/each}</select></label>
              <label>Customers<select bind:value={agentSettings.playbook.customer_type}><option value="both">Individuals and businesses</option><option value="individuals">Individuals</option><option value="businesses">Businesses</option></select></label>
              <label class="agent-wide">Business focus<textarea bind:value={agentSettings.playbook.business_focus} maxlength="240" placeholder="What do you help customers buy, book, or achieve?"></textarea></label>
              <label class="agent-wide">Ideal customer<textarea bind:value={agentSettings.playbook.ideal_customer} maxlength="240" placeholder="Who do you most want the assistant to help?"></textarea></label>
              <label>Catalogue type<select bind:value={agentSettings.playbook.offering_type}><option value="products">Products</option><option value="services">Services</option><option value="mixed">Products and services</option></select></label>
              <label>Primary conversation goal<select bind:value={agentSettings.playbook.primary_goal}><option value="drive_sales">Drive a sale</option><option value="book_consultation">Arrange a consultation</option><option value="book_appointment">Arrange an appointment or viewing</option><option value="request_quote">Request a quote</option><option value="start_subscription">Explore a subscription or membership</option><option value="capture_leads">Capture a lead</option><option value="answer_questions">Answer questions</option></select></label>
              <label class="agent-wide">How you fulfil customer needs<select bind:value={agentSettings.playbook.fulfilment_mode}><option value="auto">Use configured business information</option><option value="delivery">Delivery</option><option value="collection">Collection</option><option value="at_location">At a business location</option><option value="on_site">At the customer's location</option><option value="remote">Remote or online</option><option value="hybrid">A mix of locations and remote service</option></select><small>This guides the conversation. Prices, availability and service coverage still come from your saved business information.</small></label>
              <label>Conversation style<select bind:value={agentSettings.tone.style}><option value="friendly">Friendly</option><option value="professional">Professional</option><option value="concise">Concise</option></select></label>
              <label>Preferred reply length<select bind:value={agentSettings.tone.max_sentences}><option value={1}>1 sentence</option><option value={2}>2 sentences</option><option value={3}>3 sentences</option><option value={4}>4 sentences</option></select><small>Business answers and delivery conditions stay complete when they need more detail.</small></label>
            </div>
            <label>Response guidance<textarea bind:value={agentSettings.playbook.response_guidance} maxlength="600" placeholder="For example: use plain language, explain trade-offs and ask one relevant question at a time."></textarea><small>Set how the assistant explains and qualifies. Add customer-facing facts in your catalogue, FAQs and business profile. Guidance cannot override security or confirm an action that has not happened.</small></label>
            <div class="qualification-editor">
              <div class="qualification-heading"><h3>Why customers choose you</h3><button class="secondary" type="button" on:click={addValueProposition} disabled={agentSettings.playbook.value_propositions.length >= 5}>Add point</button></div>
              {#each agentSettings.playbook.value_propositions as proposition, propositionIndex}
                <div class="qualification-row"><label>{`Point ${propositionIndex + 1}`}<input bind:value={agentSettings.playbook.value_propositions[propositionIndex]} maxlength="160" placeholder="A real customer benefit or differentiator" /></label><button class="icon-button danger" type="button" title="Remove point" aria-label={`Remove point ${propositionIndex + 1}`} on:click={() => removeValueProposition(propositionIndex)}>{$t("Remove")}</button></div>
              {:else}
                <p class="empty-state">No differentiators added.</p>
              {/each}
            </div>
            <div class="qualification-editor">
              <div class="qualification-heading"><h3>Qualification questions</h3><button class="secondary" type="button" on:click={addQualificationQuestion} disabled={agentSettings.playbook.qualification_questions.length >= 4}>Add question</button></div>
              {#each agentSettings.playbook.qualification_questions as question, questionIndex}
                <div class="qualification-row"><label>{`Question ${questionIndex + 1}`}<input bind:value={agentSettings.playbook.qualification_questions[questionIndex]} maxlength="180" placeholder="What should the assistant learn next?" /></label><button class="icon-button danger" type="button" title="Remove question" aria-label={`Remove question ${questionIndex + 1}`} on:click={() => removeQualificationQuestion(questionIndex)}>{$t("Remove")}</button></div>
              {:else}
                <p class="empty-state">No qualification questions added.</p>
              {/each}
            </div>
            <label>Handoff message<textarea bind:value={agentSettings.playbook.handoff_message} maxlength="360" placeholder="What should the assistant say before it asks for contact details?"></textarea></label>
            <div class="section-footer profile-footer"><span class:error={agentError} class="form-status">{agentStatus}</span><button class="primary" type="submit">Save playbook</button></div>
          </form>
        </section>
      {/if}
      </div>

      {#if section === 'branches'}
      <section id="branches" class="surface workspace-section" aria-labelledby="branches-heading">
        <div class="surface-head"><div><p class="eyebrow">Locations and handoff</p><h2 id="branches-heading">Branches and opening hours</h2></div><button class="secondary" type="button" on:click={addBranch}>Add branch</button></div>
        <div class="branches-list">
          {#each branches as branch, branchIndex}
            <section class="branch-editor" aria-label={`Branch ${branch.name || branchIndex + 1}`}>
              <div class="branch-heading"><h3>{branch.name || `Branch ${branchIndex + 1}`}</h3><button class="icon-button danger" type="button" title="Remove branch" aria-label={`Remove ${branch.name || 'branch'}`} on:click={() => removeBranch(branchIndex)}>{$t("Remove")}</button></div>
              <div class="branch-fields"><label>Branch name<input bind:value={branch.name} required /></label><label>Branch key<input bind:value={branch.id} required /></label><label>Postcode<input bind:value={branch.postcode} required /></label><label>{$t("Phone")}<input bind:value={branch.phone} type="tel" /></label><label class="wide-field">Street address<input bind:value={branch.address} /></label><label>Latitude (optional)<input bind:value={branch.lat} type="number" min="-90" max="90" step="0.0001" /></label><label>Longitude (optional)<input bind:value={branch.lon} type="number" min="-180" max="180" step="0.0001" /></label></div>
              <div class="hours-grid"><h4>{$t("Opening hours")}</h4>{#each ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as day}<label>{day.toUpperCase()}<input bind:value={branch.hours[day as keyof BranchHours]} placeholder="09:00-18:00" /></label>{/each}</div>
            </section>
          {:else}
            <p class="empty-state branches-empty">No branches yet. Add a location so the assistant can direct customers to the right place.</p>
          {/each}
        </div>
        <div class="section-footer"><span class:error={branchesError} class="form-status">{branchesStatus}</span><button class="primary" type="button" on:click={saveBranches}>{$t("Save branches")}</button></div>
      </section>
      {/if}

      {#if section === 'companies' && (isPlatform || isOwner)}
        <section class="surface workspace-section"><div class="surface-head"><h2>Your companies</h2></div>
          {#each tenants as company}<div class="company-row"><strong>{company.name}</strong><span>{company.activation?.active?'Active':'Awaiting subscription and implementation payments'}</span><button class="secondary" type="button" on:click={() => openCompanyWorkspace(company.key,'profile')}>Manage {company.key}</button></div>{/each}
        </section>
      {/if}
      {#if section === 'errors'}
        <ErrorsHealth {tenant} apiPrefix={import.meta.env.DEV ? '/api' : ''}/>
      {/if}
      {/if}
      </fieldset>
    </main>
  </div>
{/if}

<CookiePreferences bind:this={cookiePreferences} bind:open={cookiePreferencesOpen} />

<style>
  .sidebar,.login-intro {--v7-focus:var(--v7-tint-line)}
  .mfa-qr{display:block;width:240px;max-width:100%;height:auto;margin:auto;background:white}.mfa-key{display:block;overflow-wrap:anywhere;margin:12px 0}
  .activation-notice {display:flex;align-items:center;gap:14px;padding:16px 20px;margin-bottom:20px;border:1px solid var(--v7-tint-line);border-radius:16px;background:var(--v7-tint);color:var(--v7-brand)}
  .activation-notice>div {flex:1;min-width:0}.activation-notice strong {font-size:12px;font-weight:700}.activation-notice p {margin:5px 0 0;font-size:11px;line-height:1.6;color:var(--v7-muted)}
  .activation-icon {display:grid;place-items:center;width:35px;height:35px;border:1px solid var(--v7-tint-line);border-radius:10px;background:var(--v7-tint);flex:none}.activation-icon svg {width:19px;height:19px;fill:none;stroke:var(--v7-brand);stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}
  .activation-notice a {display:flex;align-items:center;gap:10px;padding:10px 12px;min-height:44px;border:1px solid var(--v7-tint-line);border-radius:10px;font-size:11px;font-weight:700;color:var(--v7-brand);text-decoration:none;flex:none;background:#fff}.activation-notice a:hover {background:var(--v7-tint)}.activation-notice a:focus-visible {outline:3px solid var(--v7-focus);outline-offset:3px}
  @media(max-width:650px){.activation-notice{flex-wrap:wrap;align-items:flex-start;padding:15px}.activation-notice>div{flex-basis:calc(100% - 50px)}.activation-notice a{margin-inline-start:49px;min-height:40px}}
  .nav-section { display:grid; gap:4px; min-width:0; }
  .nav-group { margin:18px 12px 6px; font-size:10px; font-weight:750; letter-spacing:.11em; text-transform:uppercase; color:var(--v7-control-line); grid-column:1/-1; }
  .nav-section:first-child .nav-group { margin-top:0; }
  .cookie-nav-trigger {width:100%;min-height:44px;border:0;border-radius:10px;padding:10px 12px;background:transparent;color:var(--v7-line);text-align:start;font:inherit;font-size:14px;cursor:pointer}
  .cookie-nav-trigger:hover {background:#ffffff14;color:#fff}
  .cookie-login-trigger {min-height:44px;padding:0;border:0;background:transparent;color:var(--v7-accent);font:inherit;cursor:pointer}
  .cookie-login-trigger:hover {text-decoration:underline;text-underline-offset:3px}
  .cookie-nav-trigger:focus-visible,.cookie-login-trigger:focus-visible {outline:3px solid var(--v7-focus);outline-offset:3px}
  .workspace-content { min-width:0; padding:0; margin:0; border:0; }
  .workspace-progress,.workspace-retry { display:flex; align-items:center; justify-content:space-between; gap:14px; margin-bottom:20px; padding:14px 18px; border:1px solid var(--v7-line); border-radius:12px; }
  .workspace-progress { justify-content:flex-start; color:var(--v7-brand); background:var(--v7-soft); font-size:13px; }
  .workspace-retry p { margin:0; font-size:13px; line-height:1.6; }
  .workspace-retry button { flex-shrink:0; }
  .loading-indicator { width:16px; height:16px; flex-shrink:0; border:2px solid var(--v7-tint-line); border-top-color:var(--v7-accent); border-radius:50%; animation:workspace-spin .8s linear infinite; }
  .sr-only { position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip-path:inset(50%); white-space:nowrap; border:0; }
  @keyframes workspace-spin { to { transform:rotate(360deg); } }
  .company-scope{display:grid;gap:4px;max-width:100%;overflow-wrap:anywhere}.company-scope span{font-size:12px;color:var(--v7-muted)}.company-scope small{font-size:12px;color:var(--v7-muted)}
  .inventory-fields{display:flex;flex-wrap:wrap;gap:16px;padding:12px 16px 20px;border-bottom:1px solid var(--v7-line);align-items:end}.inventory-fields label{flex:1 1 180px;min-width:0}.inventory-fields p{flex:2 1 250px;font-size:13px;color:var(--v7-muted);margin:0;line-height:1.5}

  :global(body) { background: var(--v7-canvas); }
  .loading, .login-shell { min-height: 100vh; display: grid; place-items: center; color: var(--v7-muted); }
  .login-shell { padding: 24px; }
  .login { width: min(100%, 390px); display: grid; gap: 16px; padding: 32px; background: #fff; border: 1px solid var(--v7-line); border-radius: 8px; box-shadow: 0 16px 40px #2f353917; }
  h1, h2, h3, p { margin-top: 0; }
  .login h1 { margin-bottom: -8px; font-size: 25px; letter-spacing: 0; }
  .login p { color: var(--v7-muted); line-height: 1.5; }
  label { display: grid; min-width: 0; gap: 7px; color: var(--v7-ink); font-size: 13px; font-weight: 700; }
  label span { color: var(--v7-muted); font-weight: 500; }
  input, textarea, select { width: 100%; min-width: 0; max-width: 100%; min-height: 40px; padding: 9px 10px; border: 1px solid var(--v7-control-line); border-radius: 6px; color: var(--v7-ink); background: #fff; font-weight: 400; }
  textarea { min-height: 84px; resize: vertical; line-height: 1.45; }
  input:focus, textarea:focus, select:focus { outline: 3px solid var(--v7-focus-ring); border-color: var(--v7-accent); }
  .primary, .secondary { min-height: 38px; border-radius: 6px; padding: 0 14px; font-weight: 700; font-size: 14px; }
  .primary { border: 1px solid var(--v7-accent); background: var(--v7-accent); color: #fff; }
  .primary:hover { background: var(--v7-accent-hover); }
  .secondary { border: 1px solid var(--v7-control-line); background: #fff; color: var(--v7-ink); }
  .secondary:hover { background: var(--v7-soft); }
  .notice { padding: 10px 12px; border-radius: 6px; font-size: 13px; }
  .error { color: #b42318; background: #fff2f0; }
  .app-shell { min-height: 100vh; display: grid; grid-template-columns: 248px minmax(0, 1fr); }
  .sidebar { position: sticky; top: 0; height: 100dvh; overflow-y: auto; display: flex; flex-direction: column; gap: 24px; padding: 24px 16px; background: var(--v7-brand); color: var(--v7-canvas); }
  .menu-toggle { display: none; }
  .side-brand { display: grid; gap: 6px; padding: 0 10px 18px; border-bottom: 1px solid var(--v7-line); }
  .side-brand strong { font-size: 17px; overflow-wrap: anywhere; }
  .side-brand small { color: var(--v7-control-line); font-size: 12px; font-weight: 500; }
  nav { display: grid; gap: 4px; }
  nav a { width: 100%; border: 0; border-radius: 6px; padding: 10px; color: var(--v7-line); background: transparent; text-align: left; text-decoration: none; font-size: 14px; }
  nav a:hover, nav a.active { color: #fff; background: var(--v7-charcoal); }
  .account { display: grid; gap: 4px; margin-top: auto; padding: 14px 10px 0; border-top: 1px solid var(--v7-line); font-size: 12px; overflow-wrap: anywhere; }
  .account span { color: var(--v7-control-line); }
  .workspace { min-width: 0; width: 100%; padding: 28px clamp(16px, 3vw, 48px) 48px; }
  .workspace-head { display: flex; flex-wrap: wrap; align-items: end; justify-content: space-between; gap: 20px; margin-bottom: 24px; }
  .workspace-head h1 { margin-bottom: 0; font-size: 30px; letter-spacing: 0; }
  .workspace-actions { display: flex; flex-wrap: wrap; max-width: 100%; align-items: end; gap: 10px; }
  .sign-out { white-space: nowrap; }
  .eyebrow { margin-bottom: 7px; color: var(--v7-accent); font-size: 12px; font-weight: 800; letter-spacing: .06em; text-transform: uppercase; }
  .tenant-picker { min-width: 220px; }
  .operator-panel { display: grid; grid-template-columns: minmax(0, 1fr) minmax(360px, .9fr); gap: 24px; padding: 20px; margin-bottom: 20px; background: var(--v7-tint); border: 1px solid var(--v7-tint-line); border-radius: 8px; }
  .operator-panel h2 { margin-bottom: 8px; font-size: 18px; }
  .operator-panel p:not(.eyebrow) { margin-bottom: 0; color: var(--v7-muted); line-height: 1.45; }
  .tenant-form { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); align-items: end; gap: 12px; }
  .team-form, .account-control-form { display: grid; grid-template-columns: minmax(220px, 1.2fr) minmax(150px, .7fr) minmax(220px, 1fr) auto; align-items: end; gap: 12px; padding: 20px; border-bottom: 1px solid var(--v7-line); }
  .account-control-form { grid-template-columns: minmax(220px, 1.2fr) minmax(220px, 1fr) minmax(130px, .6fr) auto; background: var(--v7-canvas); }
  .account-active { display: flex; grid-template-columns: auto 1fr; align-items: center; align-self: end; min-height: 40px; gap: 8px; white-space: nowrap; }
  .account-active input { width: 16px; min-height: 16px; accent-color: var(--v7-accent); }
  .account-list { display: grid; }
  .account-row { display: grid; grid-template-columns: minmax(0, 1fr) 160px 90px; gap: 12px; align-items: center; padding: 14px 20px; border-bottom: 1px solid var(--v7-line); color: var(--v7-muted); font-size: 13px; }
  .account-row strong { color: var(--v7-ink); overflow-wrap: anywhere; }
  .account-inactive { color: #b42318; }
  .team-status { display: block; margin: 14px 20px 20px; }
  .content-grid { display: grid; grid-template-columns: minmax(0, 1fr); gap: 20px; align-items: start; }
  .surface { min-width: 0; background: #fff; border: 1px solid var(--v7-line); border-radius: 8px; overflow-wrap: anywhere; }
  .surface-head { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 16px; padding: 20px; border-bottom: 1px solid var(--v7-line); }
  .surface-head h2 { margin-bottom: 0; font-size: 17px; }
  .settings-form { display: grid; gap: 18px; padding: 20px; }
  small { color: var(--v7-muted); font-size: 12px; font-weight: 500; line-height: 1.4; }
  .origins { min-height: 120px; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 12px; }
  .form-footer { display: flex; align-items: center; justify-content: space-between; gap: 14px; min-height: 38px; }
  .form-status { color: var(--v7-muted); font-size: 13px; line-height: 1.4; }
  .form-status.error { color: #b42318; }
  .install .surface-body > p { margin: 0 0 16px; color: var(--v7-muted); font-size: 14px; line-height: 1.5; }
  .code { min-height: 132px; margin: 0; width: 100%; background: var(--v7-charcoal); color: var(--v7-tint); border: 0; border-radius: 6px; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 12px; }
  .allowlist { padding: 20px 0 0; }
  .allowlist h3 { margin-bottom: 12px; font-size: 14px; }
  .allowlist p { margin-bottom: 0; color: var(--v7-muted); font-size: 13px; }
  .allowlist code { display: block; margin: 7px 0; padding: 8px; border-left: 3px solid var(--v7-accent); background: var(--v7-tint); color: var(--v7-ink); font-size: 12px; overflow-wrap: anywhere; }
  .workspace-section { scroll-margin-top: 18px; }
  .pipeline-head { background: var(--v7-canvas); }
  .metric-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); border-bottom: 1px solid var(--v7-line); }
  .metric-grid > div { display: grid; gap: 6px; min-height: 116px; align-content: center; padding: 20px; }
  .metric-grid > div + div { border-left: 1px solid var(--v7-line); }
  .metric-grid span, .lead-row span, .lead-row time { color: var(--v7-muted); font-size: 12px; }
  .metric-grid strong { color: var(--v7-ink); font-size: 31px; line-height: 1; }
  .metric-grid small { color: var(--v7-muted); font-size: 11px; font-weight: 600; }
  .funnel-strip { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); padding: 14px 20px; background: var(--v7-soft); border-bottom: 1px solid var(--v7-line); }
  .funnel-strip > div { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; padding: 5px 12px; }
  .funnel-strip > div + div { border-left: 1px solid var(--v7-line); }
  .funnel-strip span { color: var(--v7-muted); font-size: 12px; }
  .funnel-strip strong { color: var(--v7-ink); font-size: 17px; }
  .activity-details { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(260px, .9fr); }
  .activity-list { min-width: 0; padding: 20px; }
  .activity-list + .activity-list { border-left: 1px solid var(--v7-line); }
  .list-heading { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
  .list-heading h3 { margin: 0; color: var(--v7-ink); font-size: 14px; }
  .list-heading span { color: var(--v7-muted); font-size: 11px; font-weight: 700; }
  .lead-row { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 13px 0; border-top: 1px solid var(--v7-line); }
  .lead-row > div { display: grid; gap: 4px; min-width: 0; }
  .lead-row > div:last-child { text-align: right; }
  .lead-row select { min-width: 116px; min-height: 32px; font-size: 12px; }
  .lead-row strong { color: var(--v7-ink); font-size: 13px; overflow-wrap: anywhere; }
  .intent-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 13px 0; border-top: 1px solid var(--v7-line); color: var(--v7-muted); font-size: 13px; text-transform: capitalize; }
  .intent-row strong { color: var(--v7-ink); }
  .activity-status { margin: 0; padding: 0 20px 20px; color: var(--v7-muted); font-size: 13px; }
  .count-label { padding: 5px 8px; color: var(--v7-muted); background: var(--v7-soft); border: 1px solid var(--v7-line); border-radius: 99px; font-size: 12px; font-weight: 700; white-space: nowrap; }
  .catalog-toolbar { display: flex; align-items: end; justify-content: space-between; gap: 16px; padding: 18px 20px; border-bottom: 1px solid var(--v7-line); }
  .catalog-toolbar label { max-width: 112px; }
  .currency { text-transform: uppercase; }
  .editor-group { padding: 20px; border-bottom: 1px solid var(--v7-line); }
  .group-heading { display: flex; align-items: end; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
  .category-fields { display: grid; grid-template-columns: minmax(180px, 1fr) minmax(120px, .55fr); gap: 12px; width: min(100%, 580px); }
  .product-table { overflow-x: auto; border: 1px solid var(--v7-line); border-radius: 6px; }
  .product-table-head, .product-row { display: grid; grid-template-columns: minmax(190px, 1.4fr) minmax(150px, 1fr) 96px 92px minmax(170px, 1fr) 86px 76px; gap: 8px; align-items: center; min-width: 880px; padding: 9px 10px; }
  .product-table-head { color: var(--v7-muted); background: var(--v7-canvas); border-bottom: 1px solid var(--v7-line); font-size: 11px; font-weight: 800; letter-spacing: .04em; text-transform: uppercase; }
  .product-row input { min-width: 0; }
  .stock-toggle, .collection-toggle { display: flex; grid-template-columns: auto 1fr; align-items: center; gap: 7px; color: var(--v7-ink); font-size: 12px; white-space: nowrap; }
  .stock-toggle input, .collection-toggle input { width: 16px; min-height: 16px; accent-color: var(--v7-accent); }
  .icon-button { min-height: 34px; padding: 0 8px; border: 1px solid var(--v7-control-line); border-radius: 6px; background: #fff; color: var(--v7-muted); font-size: 12px; font-weight: 700; }
  .icon-button:hover { background: var(--v7-canvas); }
  .icon-button.danger { color: #b42318; border-color: #f0b5af; }
  .icon-button.danger:hover { background: #fff2f0; }
  .add-row { min-height: 34px; margin-top: 12px; padding: 0; border: 0; color: var(--v7-accent-hover); background: transparent; font-size: 13px; font-weight: 800; }
  .add-row:hover { color: var(--v7-accent-hover); text-decoration: underline; }
  .section-footer { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 18px; padding: 18px 20px; }
  .section-footer .form-status { max-width: 68ch; }
  .management-grid { display: grid; grid-template-columns: minmax(0, 1fr); gap: 20px; align-items: start; }
  .management-grid .workspace-section { min-width: 0; }
  .faq-list, .delivery-content { padding: 20px; }
  .faq-list { display: grid; gap: 16px; }
  .faq-editor { display: grid; gap: 12px; padding-bottom: 16px; border-bottom: 1px solid var(--v7-line); }
  .faq-editor:last-child { padding-bottom: 0; border-bottom: 0; }
  .offers-list { display: grid; }
  .offer-editor { padding: 20px; border-bottom: 1px solid var(--v7-line); }
  .offer-heading { display: flex; align-items: center; justify-content: space-between; gap: 14px; margin-bottom: 16px; }
  .offer-heading h3 { margin: 0; font-size: 16px; }
  .offer-fields { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
  .offer-toggle { display: flex; grid-template-columns: auto 1fr; align-items: center; align-self: end; min-height: 40px; gap: 7px; color: var(--v7-ink); font-size: 12px; white-space: nowrap; }
  .offer-toggle input { width: 16px; min-height: 16px; accent-color: var(--v7-accent); }
  .surface-body { padding: 20px; }
  .surface-body > :last-child { margin-bottom: 0; }
  .surface-body > .empty-state { padding: 0; }
  .row-actions { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: end; gap: 12px; }
  .empty-state { margin: 0; padding: 14px 0; color: var(--v7-muted); font-size: 14px; line-height: 1.5; }
  .delivery-content { display: grid; grid-template-columns: minmax(0, 1fr); gap: 16px; }
  .field-note { margin: -4px 0 2px; color: var(--v7-muted); font-size: 12px; line-height: 1.45; }
  .delivery-rule { display: grid; grid-template-columns: minmax(0, .85fr) minmax(0, .7fr) minmax(0, .8fr) minmax(0, 1.2fr) auto; align-items: end; gap: 12px; padding: 16px 0; border-top: 1px solid var(--v7-line); }
  .exception-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-top: 4px; border-top: 1px solid var(--v7-line); }
  .exception-heading h3 { margin: 12px 0 0; font-size: 14px; }
  .exception-row { display: grid; grid-template-columns: minmax(130px, .55fr) minmax(0, 1.45fr) auto; align-items: end; gap: 10px; }
  .profile-form, .agent-form { display: grid; gap: 16px; padding: 20px; }
  .profile-form { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .profile-wide, .profile-form > .two-fields, .profile-footer { grid-column: 1 / -1; }
  .agent-settings-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
  .agent-starter { display: grid; gap: 12px; padding: 18px; border: 1px solid var(--v7-tint-line); border-radius: 14px; background: var(--v7-tint); }
  .agent-starter h3 { margin: 0; color: var(--v7-brand); font-size: 16px; }
  .agent-starter p { margin: 6px 0 0; color: var(--v7-muted); font-size: 14px; line-height: 1.5; }
  .agent-starter-controls { display: flex; align-items: end; gap: 12px; }
  .agent-starter-controls label { flex: 1; min-width: 0; }
  .agent-starter-controls button { flex-shrink: 0; }
  .agent-starter small { color: var(--v7-muted); }
  @media (max-width: 720px) { .agent-starter-controls { align-items: stretch; flex-direction: column; } }
  .agent-wide { grid-column: 1 / -1; }
  .qualification-editor { display: grid; gap: 12px; padding-top: 16px; border-top: 1px solid var(--v7-line); }
  .qualification-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
  .qualification-heading h3 { margin: 0; color: var(--v7-ink); font-size: 14px; }
  .qualification-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: end; gap: 12px; }
  .two-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
  .profile-footer { padding: 2px 0 0; }
  .branches-list { display: grid; }
  .branch-editor { padding: 20px; border-bottom: 1px solid var(--v7-line); }
  .branch-heading { display: flex; align-items: center; justify-content: space-between; gap: 14px; margin-bottom: 16px; }
  .branch-heading h3 { margin: 0; font-size: 16px; }
  .branch-fields { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
  .wide-field { grid-column: span 2; }
  .hours-grid { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 9px; margin-top: 18px; padding-top: 18px; border-top: 1px solid var(--v7-line); }
  .hours-grid h4 { grid-column: 1 / -1; margin: 0 0 2px; color: var(--v7-ink); font-size: 14px; }
  .hours-grid label { font-size: 11px; text-transform: uppercase; }
  .hours-grid input { font-size: 12px; text-transform: none; }
  .branches-empty { padding: 20px; }
  @media (max-width: 1050px) { .management-grid { grid-template-columns: 1fr; } .delivery-rule { grid-template-columns: repeat(2, minmax(0, 1fr)); } .delivery-rule .icon-button { width: fit-content; } }
  @media (max-width: 900px) { .content-grid, .operator-panel, .activity-details { grid-template-columns: 1fr; } .tenant-form, .team-form, .account-control-form { grid-template-columns: 1fr; } .activity-list + .activity-list { border-top: 1px solid var(--v7-line); border-left: 0; } }
  @media (max-width: 720px) { .app-shell { grid-template-columns: 1fr; } .sidebar { min-height: auto; gap: 16px; padding: 14px; } .side-brand { grid-template-columns: auto 1fr; align-items: baseline; padding-bottom: 0; border-bottom: 0; } .side-brand small { grid-column: 2; } nav { grid-template-columns: repeat(2, minmax(0, 1fr)); } .account { display: none; } .workspace { padding: 24px 16px 40px; } .workspace-head { align-items: start; flex-direction: column; } .workspace-actions { width: 100%; align-items: end; } .tenant-picker { flex: 1; min-width: 0; width: auto; } .form-footer, .section-footer, .group-heading, .qualification-heading { align-items: stretch; flex-direction: column; } .form-footer .primary, .section-footer .primary { width: 100%; } .catalog-toolbar { align-items: stretch; flex-direction: column; } .catalog-toolbar label { max-width: none; } .category-fields, .row-actions, .exception-row, .two-fields, .branch-fields, .offer-fields, .account-row, .agent-settings-grid, .qualification-row { grid-template-columns: 1fr; } .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .metric-grid > div:nth-child(3) { border-left: 0; border-top: 1px solid var(--v7-line); } .metric-grid > div:nth-child(4) { border-top: 1px solid var(--v7-line); } .funnel-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); padding: 10px; } .funnel-strip > div:nth-child(odd) { border-left: 0; } .funnel-strip > div:last-child { grid-column: span 2; } .lead-row { align-items: start; flex-direction: column; } .lead-row > div:last-child { text-align: left; } .wide-field { grid-column: auto; } .hours-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .row-actions .icon-button, .exception-row .icon-button, .branch-heading .icon-button, .offer-heading .icon-button, .qualification-row .icon-button { width: fit-content; } }
  @media (max-width: 1180px) {
    .team-form, .account-control-form { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .hours-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  }
  @media (max-width: 720px) {
    .app-shell { grid-template-rows: auto 1fr; }
    .sidebar { position: static; height: auto; display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 12px; }
    .menu-toggle { display: block; align-self: center; }
    nav { display: none; grid-column: 1 / -1; }
    nav.open { display: grid; }
    .profile-form, .team-form, .account-control-form { grid-template-columns: minmax(0, 1fr); }
    .hours-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .surface-head, .exception-heading, .branch-heading, .offer-heading { flex-wrap: wrap; }
    .collection-toggle, .offer-toggle { white-space: normal; }
    .form-footer { flex-wrap: wrap; }
  }
  @media (max-width: 420px) { .delivery-rule { grid-template-columns: minmax(0, 1fr); } }
  .widget-workspace {display:grid;gap:20px;min-width:0}
  .widget-workspace-intro {display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:16px;padding:20px 22px;border:1px solid var(--v7-line);border-radius:12px;background:#fff}
  .widget-workspace-intro h2 {margin:6px 0 8px;font-size:20px;letter-spacing:-.025em}
  .widget-workspace-intro p {margin:0;font-size:12px;color:var(--v7-muted);line-height:1.6}
  .widget-workspace-intro .eyebrow {font-size:10px;color:var(--v7-accent);font-weight:700;text-transform:uppercase;letter-spacing:.08em}
  .widget-workspace-intro a,.widget-install-tools a {display:inline-flex;align-items:center;min-height:44px;font-size:12px;color:var(--v7-accent);text-underline-offset:3px}
  .widget-workspace-tabs {display:flex;align-items:center;gap:6px;flex-wrap:wrap;padding:5px;border:1px solid var(--v7-line);border-radius:10px;background:#fff}
  .widget-workspace-tabs button {min-height:44px;border:1px solid transparent;border-radius:7px;background:transparent;padding:10px 15px;font-size:12px;font-weight:600;color:var(--v7-muted)}
  .widget-workspace-tabs button.active {color:var(--v7-accent);background:var(--v7-soft);border-color:var(--v7-line)}
  .widget-workspace-tabs>span {margin-inline-start:auto;padding:8px 12px;font-size:11px;color:var(--v7-muted)}
  .widget-extra {padding:6px 16px;border:1px solid var(--v7-line);border-radius:10px;background:#fff}
  .widget-extra summary {min-height:44px;align-content:center;font-size:13px;font-weight:600;cursor:pointer}
  .widget-extra :global(section) {margin-bottom:10px}
  .widget-install-grid {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px;align-items:start;min-width:0}
  .widget-install-grid .surface {min-width:0}.widget-install-grid .surface-head p:last-child {margin:7px 0 0;font-size:12px;color:var(--v7-muted);line-height:1.6}
  .widget-install-tools {display:grid;gap:18px}.widget-install-tools p {margin:0;font-size:12px;line-height:1.65;color:var(--v7-muted)}.widget-install-tools .code {width:100%;min-height:150px}
  .widget-save-notice {display:flex;align-items:center;flex-wrap:wrap;gap:12px;margin:0;padding:12px 16px;border:1px solid var(--v7-line);border-radius:8px;background:var(--v7-soft);font-size:12px;line-height:1.6}
  .widget-save-notice button {padding:8px 10px;min-height:44px;border:1px solid var(--v7-control-line);background:#fff;border-radius:7px;font-size:11px}
  @media(max-width:900px){.widget-install-grid {grid-template-columns:1fr}}
  @media(max-width:600px){.widget-workspace-intro {padding:16px}.widget-workspace-tabs>span {width:100%;margin-inline-start:0}.widget-workspace-tabs button {padding:10px;font-size:11px}.widget-install-grid .form-footer {align-items:start;flex-direction:column}.widget-install-grid .form-footer button {width:100%}}
  .company-row { display:flex; flex-wrap:wrap; gap:16px; align-items:center; padding:16px; border-bottom:1px solid var(--v7-line); }
  .login-shell {grid-template-columns:minmax(0,1fr) minmax(380px,1fr);place-items:stretch;padding:0;background:var(--v7-canvas)}
  .login-intro {display:flex;flex-direction:column;justify-content:center;padding:40px clamp(24px,4vw,64px);background:linear-gradient(90deg,#143c30ed,#143c30c9),url('/static/img/vertex-seven-banner.svg?v=20261009svg');background-size:cover,auto 135%;background-position:center,right center;background-repeat:no-repeat;color:#fff;min-width:0}
  .login-brand,.login-logo {display:flex;align-items:center;gap:10px;font-size:18px;line-height:1.2;letter-spacing:-.025em}
  .login-brand {margin-bottom:40px;text-decoration:none;color:#fff;width:fit-content}
  .login-brand strong,.login-logo strong {font-weight:700}
  .login-logo {color:var(--v7-ink)}
  .login-logo strong {color:var(--v7-accent)}
  .login-intro .eyebrow {color:var(--v7-tint-line);margin-bottom:20px}
  .login-intro h2 {font-size:clamp(32px,3.5vw,50px);line-height:1.15;letter-spacing:-.035em;max-width:520px;margin-bottom:24px;color:#fff}
  .login-intro p:not(.eyebrow) {font-size:16px;line-height:1.7;color:var(--v7-line);max-width:480px}
  .login-intro > a:last-child {font-size:13px;color:var(--v7-line);margin-top:32px}
  .intro-features {display:flex;gap:10px;flex-wrap:wrap;margin-top:16px;font-size:12px}
  .intro-features span {padding:9px 12px;border:1px solid var(--v7-control-line);border-radius:99px}
  .login-content {width:100%;max-width:620px;justify-self:center;align-self:center;padding:36px clamp(24px,5vw,64px)}
  .login-tools {display:flex;justify-content:flex-end;margin-bottom:20px}
  .login {width:100%;padding:32px;border-color:var(--v7-line);border-radius:20px;box-shadow:0 16px 60px #2f35390a;gap:16px}
  .login h1 {font-size:27px;line-height:1.25;letter-spacing:-.025em;margin-bottom:0}
  .login p {font-size:13px;margin-bottom:0;line-height:1.6;color:var(--v7-muted)}
  .password-field {display:flex;position:relative}
  .password-field input {padding-inline-end:124px}
  .password-field button {position:absolute;inset-inline-end:6px;top:6px;bottom:6px;min-height:30px;padding:4px 8px;border:0;border-radius:6px;background:var(--v7-soft);color:var(--v7-accent);font-size:11px;max-width:118px}
  .remember-choice {display:flex;align-items:flex-start;gap:10px;font-size:13px;line-height:1.5;font-weight:600}
  .remember-choice input {width:17px;min-height:17px;margin:2px 0 0;flex-shrink:0}
  .remember-choice span {color:var(--v7-ink)}
  .remember-choice small {display:block;margin-top:4px;font-size:11px;font-weight:400;color:var(--v7-muted)}
  .provider-divider {display:flex;align-items:center;gap:10px;font-size:11px;color:var(--v7-muted);margin:2px 0}
  .provider-divider::before,.provider-divider::after {content:'';height:1px;flex:1;background:var(--v7-line)}
  .provider-buttons {display:grid;grid-template-columns:1fr 1fr;gap:10px}
  .login .provider-help,.login .login-policy {font-size:11px;line-height:1.5}
  .login-policy a {color:var(--v7-accent)}
  .app-shell {grid-template-columns:238px minmax(0,1fr)}
  .sidebar {background:var(--v7-brand);padding:22px 14px 16px;gap:20px;overflow:hidden}
  .side-brand {display:flex;align-items:center;gap:12px;flex:none;padding:0 10px 20px;border-color:#ffffff19}
  .side-brand > div {display:grid;gap:3px;min-width:0}
  .side-brand strong {font-size:16px;font-weight:650;letter-spacing:-.02em;color:#fff}
  .side-brand small {color:var(--v7-control-line);font-size:11px;letter-spacing:0}
  nav {flex:1;min-height:0;overflow-y:auto;align-content:start;gap:18px;padding:0 3px;scrollbar-width:thin;scrollbar-color:#ffffff2b transparent}
  .nav-section {gap:2px}
  .nav-group {margin:0 10px 6px;color:var(--v7-control-line);font-size:10px;font-weight:650;letter-spacing:.08em}
  nav a,.cookie-nav-trigger {display:flex;align-items:center;gap:11px;border-radius:7px;padding:10px;color:var(--v7-line);min-height:40px;font-size:12px;line-height:1.4;transition:background-color .15s}
  nav a span,.cookie-nav-trigger span {min-width:0}
  nav a:hover,.cookie-nav-trigger:hover {background:#ffffff0d;color:white}
  nav a.active {background:#ffffff12;color:#fff;font-weight:650;box-shadow:inset 3px 0 var(--v7-tint-line)}
  .account {display:flex;align-items:center;gap:10px;flex:none;margin-top:0;padding:16px 10px 0;border-color:#ffffff19}
  .account-avatar {display:grid;place-items:center;width:32px;height:32px;flex:none;border-radius:8px;background:#ffffff12;color:var(--v7-tint-line);font-size:12px;font-weight:650}
  .account > div {display:grid;gap:3px;min-width:0}
  .account strong {font-size:11px;font-weight:600;color:var(--v7-soft)}
  .account > div span {color:var(--v7-control-line);font-size:10px}
  .workspace {padding:28px clamp(20px,2.6vw,40px) 48px;background:var(--v7-canvas);min-width:0}
  .workspace-head {align-items:center;padding-bottom:22px;border-bottom:1px solid var(--v7-line);margin-bottom:24px;gap:18px}
  .workspace-title {min-width:0;flex:1 1 340px}
  .workspace-head h1 {font-size:28px;line-height:1.2;letter-spacing:-.035em;color:var(--v7-ink);font-weight:650}
  .workspace-head .eyebrow {color:var(--v7-muted);letter-spacing:.08em;font-size:10px;font-weight:650;margin-bottom:8px}
  .page-description {margin:8px 0 0;color:var(--v7-muted);font-size:13px;line-height:1.55;max-width:620px}
  .workspace-actions {flex-wrap:wrap;justify-content:flex-end;align-items:center;gap:12px}
  .workspace-actions :global(.language-picker) {display:grid;gap:5px;align-items:start;color:var(--v7-muted);font-size:11px;line-height:1.5;font-weight:600}
  .workspace-actions :global(.language-picker select) {border-color:var(--v7-control-line);border-radius:7px;min-height:40px;font-size:12px;color:var(--v7-ink);padding:8px 10px}
  .tenant-picker {min-width:160px;font-size:11px;color:var(--v7-muted);gap:5px;font-weight:600}
  .tenant-picker select {min-height:40px;font-size:12px}
  .sign-out {margin-top:21px;min-height:40px;font-size:12px}
  .surface {border-color:var(--v7-line);border-radius:var(--v7-radius);box-shadow:var(--v7-card-shadow);margin-bottom:20px}
  .workspace :global(.panel) {border-color:var(--v7-line);border-radius:var(--v7-radius);box-shadow:var(--v7-card-shadow)}
  .surface-head {background:#fff;padding:20px 22px;border-color:var(--v7-line);border-radius:var(--v7-radius) var(--v7-radius) 0 0}
  .surface-head h2 {color:var(--v7-ink);font-size:18px;letter-spacing:-.02em;font-weight:650}
  .surface-head .eyebrow {font-size:10px;font-weight:650;letter-spacing:.08em;margin-bottom:5px}
  .primary {background:var(--v7-accent);border-color:var(--v7-accent);min-height:44px;border-radius:7px;font-weight:600;font-size:13px}
  .primary:hover {background:var(--v7-accent-hover);border-color:var(--v7-accent-hover)}
  .secondary {color:var(--v7-ink);border-color:var(--v7-control-line);min-height:44px;border-radius:7px;font-weight:600;font-size:13px}
  .secondary:hover {background:var(--v7-soft)}
  input,textarea,select {color:var(--v7-ink);border-color:var(--v7-control-line);border-radius:7px;min-height:44px;font-size:13px}
  input:focus,textarea:focus,select:focus {border-color:var(--v7-accent);outline:2px solid var(--v7-focus-ring);outline-offset:1px}
  label {font-size:12px;font-weight:600;color:var(--v7-ink)}
  small,.field-note,.form-status {color:var(--v7-muted);line-height:1.6}
  .eyebrow {color:var(--v7-accent)}
  .notice {background:var(--v7-soft);color:var(--v7-brand);border:1px solid var(--v7-tint-line);padding:12px;border-radius:8px}
  .notice.error {background:#fff2f0;color:#a61b2b;border-color:#f1c5c6}
  .skip-link {position:fixed;inset-inline-start:16px;top:12px;z-index:100;transform:translateY(-200%);padding:12px 18px;background:var(--v7-soft);color:var(--v7-brand);border:1px solid var(--v7-control-line);border-radius:8px;font-weight:600}
  .skip-link:focus {transform:translateY(0)}
  .metric-grid {padding:0;gap:0;border-bottom:1px solid var(--v7-line)}
  .metric-grid > div {min-height:120px;padding:22px;border:0;border-radius:0;background:#fff;gap:8px}
  .metric-grid > div + div {border-left:1px solid var(--v7-line)}
  .metric-grid strong {font-size:32px;color:var(--v7-ink);font-variant-numeric:tabular-nums;letter-spacing:-.04em;font-weight:650}
  .metric-grid small,.list-heading span {color:var(--v7-muted)}
  .funnel-strip {margin:18px 22px 0;padding:10px 8px;border:1px solid var(--v7-line);border-radius:8px;background:var(--v7-canvas)}
  .count-label {padding:6px 10px;background:var(--v7-soft);border-color:var(--v7-line);color:var(--v7-brand)}
  .operator-panel {padding:22px;border-radius:var(--v7-radius);background:#fff;border-color:var(--v7-line)}
  .operator-panel p:not(.eyebrow) {color:var(--v7-muted);line-height:1.6}
  .account-row strong {color:var(--v7-ink)}
  .account-row:nth-child(even),.company-row:nth-child(odd) {background:var(--v7-soft)}
  .company-row {padding:18px 22px}
  .company-row:last-child {border-bottom:0;border-radius:0 0 var(--v7-radius) var(--v7-radius)}
  .company-row strong {flex:1 1 180px}
  .company-row span {color:var(--v7-muted);font-size:13px}
  .editor-group,.offer-editor,.branch-editor {padding:22px}
  .product-table {border-radius:8px;border-color:var(--v7-line)}
  .product-table-head {background:var(--v7-canvas);color:var(--v7-muted);padding:12px}
  .inventory-fields {background:var(--v7-soft)}
  .icon-button,.add-row {min-height:44px}
  .section-footer {padding:18px 22px;background:var(--v7-soft);border-radius:0 0 var(--v7-radius) var(--v7-radius)}
  .profile-footer {padding:0;background:transparent}
  .empty-state {padding:22px 16px;line-height:1.6;border:1px dashed var(--v7-line);border-radius:8px;background:var(--v7-soft);font-size:13px}
  .settings-form,.profile-form,.agent-form,.team-form,.account-control-form {gap:18px}
  .activity-list {padding:22px}
  .lead-row select {min-height:40px}
  .agent-starter {padding:18px;border-radius:10px;background:var(--v7-soft);border-color:var(--v7-tint-line)}
  .activation-notice {padding:14px 16px;gap:12px;border-color:var(--v7-line);border-radius:10px;background:#fff}
  .activation-icon {border:0;border-radius:8px;background:var(--v7-soft)}
  .activation-icon svg {stroke:var(--v7-accent)}
  .activation-notice strong {font-size:12px;color:var(--v7-ink);font-weight:650}
  .activation-notice p {font-size:12px;line-height:1.5;margin-top:3px}
  .activation-notice a {font-size:12px;font-weight:600;border-color:var(--v7-control-line);border-radius:7px;color:var(--v7-accent);padding:8px 12px}
  .activation-notice a:hover {background:var(--v7-soft)}
  .login {border-color:var(--v7-line);border-radius:var(--v7-radius);box-shadow:0 6px 24px #2f353906}
  .password-field button,.login-policy a {color:var(--v7-accent)}
  .login-intro .eyebrow {color:var(--v7-tint-line)}
  :global(body) {background:var(--v7-canvas)}
  @media(max-width:900px){.login-shell{grid-template-columns:1fr}.login-intro{order:2;padding:28px}.login-brand{margin-bottom:40px}.login-intro h2{font-size:28px;max-width:650px}.login-intro> a:last-child{display:none}.login-content{order:1;padding:28px;max-width:600px}}
  @media(max-width:1100px){.workspace-title{flex-basis:100%}.workspace-actions{justify-content:flex-start}}
  @media(max-width:720px){.app-shell{grid-template-columns:1fr}.sidebar{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:0;position:relative;height:auto;overflow:visible;padding:16px}.side-brand{padding:0;border:0;gap:10px;grid-template-columns:none}.side-brand small{grid-column:auto}.menu-toggle{justify-self:end;margin-top:0;color:var(--v7-soft);background:#ffffff10;border-color:#ffffff26;border-radius:7px;min-height:44px}.workspace{padding:22px 16px 40px}.workspace-head{gap:16px;padding-bottom:20px}.workspace-title{flex-basis:auto}.workspace-head h1{font-size:25px}.workspace-actions{justify-content:flex-start;align-items:end;gap:12px}.tenant-picker{min-width:0;flex:1 1 130px}.sign-out{margin-top:0}.page-description{font-size:12px}.login{padding:24px}.account{display:none}}
  @media(max-width:720px){.surface-head,.editor-group,.offer-editor,.branch-editor,.activity-list,.operator-panel{padding:18px}.metric-grid{padding:0;gap:0}.metric-grid>div{min-height:112px;padding:18px}.metric-grid strong{font-size:29px}.metric-grid>div:nth-child(3){border-inline-start:0;border-top:1px solid var(--v7-line)}.metric-grid>div:nth-child(4){border-top:1px solid var(--v7-line)}.funnel-strip{margin:16px 18px 0}.workspace-actions .sign-out{margin-inline-start:auto}.section-footer{padding:18px}.account-active{white-space:normal}.provider-buttons{grid-template-columns:1fr}}
  @media(max-width:720px){nav{grid-column:1/-1;flex:none;overflow:visible;gap:14px;padding:0}nav.open{grid-template-columns:1fr;margin-top:16px}.nav-section{grid-template-columns:repeat(2,minmax(0,1fr));gap:4px}.nav-group{margin:4px 8px}.nav-section:first-child .nav-group{margin-top:4px}.nav-section a,.cookie-nav-trigger{min-height:44px;font-size:12px;gap:8px}.workspace-retry{align-items:flex-start;flex-direction:column}}
</style>
