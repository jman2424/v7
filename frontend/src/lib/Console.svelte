<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { base } from './consoleBase';
  import { goto } from '$app/navigation';
  import SectionSearch from './SectionSearch.svelte';
  import PlatformLogo from './PlatformLogo.svelte';
  import {subscriptionCreditAlerts} from './subscription-format';
  import Conversations from './Conversations.svelte';
  import type { Widget, PreviewTheme } from './widgetAppearance';
  import LanguagePicker from './LanguagePicker.svelte';
  import CookiePreferences from './CookiePreferences.svelte';
  import NavigationIcon from './NavigationIcon.svelte';
  import WorkspaceNav from './WorkspaceNav.svelte';
  import WorkspaceHome from './WorkspaceHome.svelte';
  import OfferingPicker from './OfferingPicker.svelte';
  import DraftGuard from './DraftGuard.svelte';
  import {hasUnsavedDrafts} from './draftNavigation';
  import ConfirmDialog from './ConfirmDialog.svelte';
  import BillingOverview from './BillingOverview.svelte';
  import {workspaces,platformWorkspace,workspaceDefinitions,legacyLocation,resolveWorkspace,workspaceAllowed,workspaceHref,sectionHref,type Workspace} from './workspaceArchitecture';
  import { initialiseLanguage, t } from './i18n';
  let cookiePreferences: CookiePreferences | undefined;
  let cookiePreferencesOpen = false;
  let signupOpen = false;
  let passwordResetOpen = false;
  export let section = 'home';
  export let workspace = '';
  export let workspaceView = '';
  export let workspacePanel = '';
  let navigationCollapsed=false;
  let primaryWorkspaces:Workspace[]=[];
  $: activeWorkspace=workspace||legacyLocation(section).workspace;
  $: activeView=workspaceView||legacyLocation(section).view;
  $: platformMode=activeWorkspace==='platform'&&isPlatform;
  $: workspaceDefinition=workspaceDefinitions.find(item=>item.id===activeWorkspace)||workspaces[0];
  $: viewDefinition=workspaceDefinition.views.find(item=>item.id===activeView)||workspaceDefinition.views[0];
  $: deliveryVisible=agentSettings.playbook.offering_type!=='services'||['delivery','collection'].includes(agentSettings.playbook.fulfilment_mode);
  $: availableViews=user?workspaceDefinition.views.filter(item=>mayOpenScreen(item.section)&&(item.section!=='delivery'||deliveryVisible)):[];
  $: primaryWorkspaces=!user?[]:platformMode
    ? platformWorkspace.views.filter(item=>!item.hidden&&mayOpenScreen(item.section)).map(item=>({id:item.id,label:item.label,description:'',icon:item.section,views:[item]}))
    : workspaces.map(item=>({...item,views:item.views.filter(view=>mayOpenScreen(view.section))})).filter(item=>item.views.some(view=>!view.hidden));
  $: businessName=tenants.find(item=>item.key===tenant)?.name||profile.name||$t('Your business');
  const sections: Record<string, string> = {subscription:'Subscription',platform:'Platform overview',pipeline:'Sales pipeline',statistics:'Statistics',test:'Website widget',implementation:'Implementation','whatsapp-qr':'WhatsApp',usage:'API usage & cost',conversations:'Conversations',agent:'Agent playbook',website:'Website widget',integrations:'Integrations',catalog:'Catalogue',offers:'Offers',faqs:'Questions & answers',delivery:'Delivery',profile:'Business profile',branches:'Branches & hours',team:'Team access',companies:'Companies',errors:'Errors & health',account:'Account & security',privacy:'Privacy & data',budget:'AI Budget','provider-funding':'AI Provider Funding'};
  $: pageTitle = sections[section] || 'Sales workspace';
  sections.operations = 'Business hub';
  sections.applications = 'Business Applications';
  sections.application = 'My application';
  sections.home='Home';sections.phone='Phone';sections.email='Email';sections.cookies='Cookie Preferences';
  sections['billing-overview']='Billing';sections.spending='AI Spending';
  const pageDescriptions: Record<string, string> = {
    operations: 'Manage email and phone handling, review replies and confirm business actions.',
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
    'whatsapp-qr': 'Connect your number, understand the costs and prepare your customer chat.',
    usage: 'Review recorded AI usage and estimated costs.',
    budget: 'Manage your AI balance, funding, spending limits and alerts.',
    'provider-funding': 'Review provider funding, payment costs and financial safeguards.',
    subscription: 'Manage subscriptions, payments and invoices.',
    team: 'Control who can access this business workspace.',
    errors: 'Review service health and issues that need attention.',
    account: 'Manage your sign-in and account security.',
    privacy: 'Manage business data and privacy preferences.'
  };
  type User = {
    permissions?: string[];
    email: string;
    roles: string[];
    tenant: string;
  };

  const isWidgetSection = (screen: string) => screen === 'website' || screen === 'test';
  let widgetView: 'appearance' | 'test' | 'install' = section === 'test' ? 'test' : 'appearance';
  $: if(workspacePanel==='test'||workspacePanel==='install')widgetView=workspacePanel;
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
    deal_type: 'custom' | 'buy_one_get_one' | 'minimum_spend' | 'signup_discount';
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
  let providerController:AbortController|undefined;
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
  const pendingWorkspaceMutations = new Map<string, WorkspaceRequest>();
  let workspaceLoadSequence = 0;
  let requestedWorkspaceSection = '';
  let signingIn = false;
  let formStatus = '';
  let formError = false;
  let loading = true;
  const sectionKeywords:Record<string,string>={
    operations:'business hub email phone calls inbox approvals drafts workflows actions',
    budget:'AI funds balance spending alerts automatic recharge credit',
    'provider-funding':'provider finance reserve OpenAI costs margins',
    subscription:'billing plans payment invoices cancel change plan',usage:'API AI models memory tokens credit costs',
    website:'widget branding colours embed agent test',integrations:'MCP API OpenAI connections',
    faqs:'FAQ knowledge answers support',account:'login password authenticator 2FA security',
    team:'staff users permissions access',catalog:'products services prices stock',
    branches:'locations opening times hours',conversations:'chat history messages customers',
    implementation:'setup install onboarding',agent:'tone behaviour sales playbook',
  };
  function searchableSections(){return [...new Set((platformMode?[platformWorkspace]:workspaces).flatMap(group=>group.views.map(view=>view.section)))].filter(mayOpenScreen);}
  $: sectionSearchItems=user?searchableSections().map(key=>({
    key,label:$t(sections[key]),description:$t(pageDescriptions[key]||''),keywords:sectionKeywords[key]||'',
    href:platformMode?workspaceHref(base,'platform',platformWorkspace.views.find(view=>view.section===key)?.id||'overview',tenant):sectionHref(base,key,tenant),reload:isWidgetSection(key)
  })):[];

  let companyQuery='';
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
  let referralSaved = false;
  let accountError = false;
  $: editorWritePermission=({catalog:'offerings.write',offers:'offers.write',faqs:'business_settings.write',profile:'business_settings.write',branches:'business_settings.write',delivery:'business_settings.write',agent:'business_settings.write'} as Record<string,string>)[section]||'';
  $: canEditCurrent=!editorWritePermission||Boolean(user?.permissions?.includes(editorWritePermission));
  let catalogQuery='',faqQuery='',salesQuery='',salesStage='all';
  let commonQuestionsOpen=false,advancedAiOpen=false;
  let messagePanel='history',approvalsOpened=false;
  $: if(workspacePanel==='approvals'){messagePanel='approvals';approvalsOpened=true;}
  const matches=(query:string,...values:unknown[])=>!query.trim()||values.join(' ').toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());
  $: visibleLeadCount=insights.leads.filter(lead=>(salesStage==='all'||lead.status===salesStage)&&matches(salesQuery,lead.name,lead.phone)).length;
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
  let insightsAvailable=false,insightsBusy=false;
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
  let draftConfirmation:ConfirmDialog;
  let savedBusinessDrafts:Record<string,string>={};
  $: businessDrafts={catalog,faq:faqs,offers,delivery,profile,branches,'agent-settings':agentSettings};
  $: dirtyResources=Object.entries(businessDrafts).filter(([key,value])=>savedBusinessDrafts[key]&&savedBusinessDrafts[key]!==JSON.stringify(value)).map(([key])=>key);
  $: currentDraftKey=({catalog:'catalog',faqs:'faq',offers:'offers',delivery:'delivery',profile:'profile',branches:'branches',agent:'agent-settings'} as Record<string,string>)[section]||'';
  function rememberDraft(key:string,value:unknown){savedBusinessDrafts={...savedBusinessDrafts,[key]:JSON.stringify(value)};}
  async function discardDraft(){
    if(!savedBusinessDrafts[currentDraftKey]||!await draftConfirmation.ask())return;
    const value=JSON.parse(savedBusinessDrafts[currentDraftKey]);
    switch(currentDraftKey){case 'catalog':catalog=value;break;case 'faq':faqs=value;break;case 'offers':offers=value;break;case 'delivery':delivery=value;break;case 'profile':profile=value;break;case 'branches':branches=value;break;case 'agent-settings':agentSettings=value;break;}
  }
  let activation:{active:boolean;status:string;usage_credit_alerts?:{code:string;message:string}[]}|null=null;
  $: usageCreditAlerts=subscriptionCreditAlerts(activation?.usage_credit_alerts||[]);
  $: usageCreditWarning=(code:string)=>$t(code==='low_credit'?'Your available AI credit is low. Top up to keep paid AI responses available.':code==='financial_review_required'?'Paid AI is paused pending a credit or usage review. Contact your platform administrator. Saved business knowledge remains available.':code==='pricing_unavailable'?'Paid AI is paused because model pricing or the exchange rate cannot be verified safely. Contact your platform administrator.':'Paid AI is paused until sufficient usage credit is available. Saved business knowledge remains available.');
  $: canManageAccounts = hasAccountManagementAccess() && Boolean(user?.permissions?.includes('users.read'));
  $: if (user) accountRole = isPlatform ? 'business_owner' : 'business_staff';
  $: if (!loading && !signingIn && user && section !== requestedWorkspaceSection) void loadWorkspaceSection(section);

  function apiPath(path: string) {
    // The dev server proxies API requests. In production Flask serves this
    // console at /console, so direct same-origin requests retain its session.
    return import.meta.env.DEV ? `/api${path}` : path;
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

  async function mutateWorkspace(path: string, options: RequestInit, failed: (message: string) => void) {
    if (pendingWorkspaceMutations.has(path)) return null;
    const activeLoad = workspaceRequest();
    const selectedTenant = tenant;
    pendingWorkspaceMutations.set(path, activeLoad);
    try {
      const result = await requestJson(path, options, activeLoad);
      if (!isCurrentWorkspace(activeLoad)) return null;
      return { ...result, activeLoad, selectedTenant };
    } catch {
      // A timed-out or cancelled write can still complete on the server.
      if (isCurrentWorkspace(activeLoad)) failed('The update could not be confirmed. Reload to check the latest data before trying again.');
      return null;
    } finally {
      if (pendingWorkspaceMutations.get(path) === activeLoad) pendingWorkspaceMutations.delete(path);
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
      archived: item.archived === true, deal_type: item.deal_type === 'buy_one_get_one' || item.deal_type === 'minimum_spend' || item.deal_type === 'signup_discount' ? item.deal_type : 'custom',
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
    savedBusinessDrafts={};
    pendingWorkspaceResources.clear();
    pendingWorkspaceMutations.clear();
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
    insights = normalizeInsights({}); insightsAvailable=false;insightsBusy=false;activityStatus = '';
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
    const params=new URLSearchParams(window.location.search);
    const next=params.get('next');
    const destination=next?resolveWorkspace(next,params.get('view')||'').section:'';
    if (destination && mayOpenScreen(destination)) return destination;
    if (user && window.location.pathname.replace(/\/$/, '') === base) return defaultWorkspaceScreen();
    return mayOpenScreen(section) ? section : defaultWorkspaceScreen();
  }

  function sectionResources(screen: string, identity: User | null): WorkspaceResource[] {
    const resources: Partial<Record<string, WorkspaceResource[]>> = {
      home: ['insights'], pipeline: ['insights'], team: ['accounts'], catalog: ['catalog', 'agent-settings'],
      test: ['widget', 'profile'], website: ['widget', 'profile'], integrations: ['widget'],
      agent: ['agent-settings'], offers: ['offers','catalog'], faqs: ['faq'], delivery: ['delivery'],
      profile: ['profile','agent-settings'], branches: ['branches']
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
          case 'catalog': catalog = normalizeCatalog(data); rememberDraft('catalog',catalog); break;
          case 'faq': faqs = normalizeFaqs(data); rememberDraft('faq',faqs); break;
          case 'offers': offers = normalizeOffers(data); rememberDraft('offers',offers); break;
          case 'delivery': delivery = normalizeDelivery(data); rememberDraft('delivery',delivery); break;
          case 'profile': profile = normalizeProfile(data); rememberDraft('profile',profile); break;
          case 'branches': branches = normalizeBranches(data); rememberDraft('branches',branches); break;
          case 'agent-settings': agentSettings = normalizeAgentSettings(data); rememberDraft('agent-settings',agentSettings); break;
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
    if(key==='home'||key==='cookies')return true;
    if(key==='billing-overview')return Boolean(user.permissions?.includes('view_costs')||user.permissions?.includes('view_subscriptions'));
    if(key==='spending')return Boolean(user.permissions?.includes('view_costs'));
    if(key==='phone'||key==='email')return (operator||owner)&&Boolean(user.permissions?.includes('customers.read')&&user.permissions?.includes('integrations.read'));
    if (key === 'platform') return operator && Boolean(user.permissions?.includes('platform.read'));
    if (key === 'provider-funding') return operator;
    if (key === 'budget') return Boolean(user.permissions?.includes('view_costs'));
    if (key === 'usage' && !operator) return false;
    if (key === 'companies') return operator || owner;
    if (key === 'applications') return operator;
    if (key === 'application') return operator || owner;
    if (key === 'team') return (operator || owner) && Boolean(user.permissions?.includes('users.read'));
    if (key === 'operations') return (operator || owner) && Boolean(user.permissions?.includes('customers.read') && user.permissions?.includes('integrations.read'));
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
    return (isPlatform?['platform','home']:['home','account']).find(mayOpenScreen)||'account';
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
    if(insightsBusy||!isCurrentWorkspace(activeLoad))return false;
    insightsBusy=true;insightsAvailable=false;
    insights = normalizeInsights({});
    activityStatus = 'Loading activity...';
    try {
      const { response, data } = await requestJson(`/admin/api/insights?tenant=${encodeURIComponent(selectedTenant)}&minutes=10080&limit=50`, { credentials: 'same-origin' }, activeLoad);
      if (!isCurrentWorkspace(activeLoad)) return;
      if (!response.ok) { activityStatus = 'Sales activity is currently unavailable. Try refreshing.'; return false; }
      insights = normalizeInsights(data);
      insightsAvailable=true;
      activityStatus = '';
      return true;
    } catch {
      if (isCurrentWorkspace(activeLoad)) activityStatus = 'Sales activity could not load. Check your connection and try refreshing.';
      return false;
    } finally {if(isCurrentWorkspace(activeLoad))insightsBusy=false;}
  }

  async function updateLeadStatus(leadId: string, status: LeadStatus) {
    activityStatus = 'Updating lead...';
    const result = await mutateWorkspace(`/admin/api/leads/${encodeURIComponent(leadId)}?tenant=${encodeURIComponent(tenant)}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }, credentials: 'same-origin', body: JSON.stringify({ status })
    }, message => { activityStatus = message; });
    if (!result || !isCurrentWorkspace(result.activeLoad)) return;
    const { response, data } = result;
    if (!response.ok) {
      activityStatus = data.error || 'Could not update this lead.';
      return;
    }
    insights = { ...insights, leads: insights.leads.map((lead) => lead.lead_id === leadId ? { ...lead, status } : lead) };
    const refreshed=await loadInsights(tenant,result.activeLoad);
    if(isCurrentWorkspace(result.activeLoad))activityStatus=refreshed?'Lead updated.':'Lead status was saved. Refresh sales activity to load the latest totals.';
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
    if (data.error === 'unknown_tenant' || data.error === 'invalid_tenant') return 'Your account workspace could not be opened. Contact the business owner or try signing in again.';
    if (data.error === 'provider_not_configured') return 'This sign-in provider is awaiting server setup. Use your password instead.';
    if (data.error === 'invalid_credentials' && phase === 'password') return 'Sign-in details were not accepted. Check your email and password.';
    return phase === 'authenticator' ? 'Code not accepted. Check your authenticator and try again.'
      : phase === 'provider' ? 'Could not start provider sign-in. Try again or use your password.'
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
        body: JSON.stringify({ email, password, totp, remember_device: rememberDevice })
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
    const referral = params.get('ref') || '';
    referralSaved = /^V7-[A-Fa-f0-9]{32}$/.test(referral);
    const next = params.get('next');
    const requested=next?resolveWorkspace(next,params.get('view')||'',params.get('panel')||''):null;
    let destination = requested && mayOpenScreen(requested.section) ? requested.section : !mayOpenScreen(section) ? defaultWorkspaceScreen() : null;
    if (!destination && window.location.pathname.replace(/\/$/,'')===base) {
      destination = defaultWorkspaceScreen();
    }
    if (!destination) return;
    params.delete('next'); params.delete('oidc'); params.delete('provider');
    params.set('tenant', tenant);
    const location=requested&&requested.section===destination?requested:legacyLocation(destination);
    params.set('view',location.view);
    if(location.panel)params.set('panel',location.panel);else params.delete('panel');
    const target = base+'/'+location.workspace+'?'+params.toString();
    // A full document load applies the widget page's microphone policy.
    if (isWidgetSection(destination) || isWidgetSection(section)) window.location.replace(target);
    else await goto(target, {replaceState:true});
  }

  async function loadProviders() {
    // Provider metadata is global, not part of the current tenant's draft/read lifecycle.
    providerController?.abort();
    const controller=new AbortController();providerController=controller;
    const timeout=setTimeout(()=>controller.abort(),20000);
    try {
      const response=await fetch(apiPath('/auth/oidc/providers'),{credentials:'same-origin',signal:controller.signal});
      if(!response.ok||controller.signal.aborted)return;
      const data=await response.json();
      if(controller.signal.aborted)return;
      providers=Array.isArray(data.providers)?data.providers.filter((item:{id?:string})=>item.id==='google'):[];
    } catch { if(!controller.signal.aborted)providers=[]; }
    finally {clearTimeout(timeout);}
  }

  async function providerLogin(provider: 'google'|'microsoft') {
    if (signingIn) return;
    signingIn = true; loginError = '';
    try {
      let session = await requestJson('/auth/session', {credentials:'same-origin'});
      if (session.response.status === 401) session = await requestJson('/auth/session', {credentials:'same-origin'});
      if (!session.response.ok || !session.data.csrf_token) throw new Error();
      csrf = session.data.csrf_token;
      const { response, data: start } = await requestJson('/auth/oidc/'+provider+'/start', {method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify({intent:'login'})});
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
    if(tenant!==company)return;
    const target = platformMode&&screen==='operations'?workspaceHref(base,'platform','channel-access',company):sectionHref(base,screen,company);
    if (isWidgetSection(screen) || isWidgetSection(section)) window.location.assign(target);
    else await goto(target);
  }

  async function logout() {
    if((dirtyResources.length||widgetDirty||hasUnsavedDrafts())&&!await draftConfirmation.ask())return;
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
    const result = await mutateWorkspace('/admin/api/tenants', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
      credentials: 'same-origin',
      body: JSON.stringify({ key: newTenantKey, name: newTenantName })
    }, message => { createStatus = message; });
    if (!result || !isCurrentWorkspace(result.activeLoad)) return;
    const { response, data } = result;
    if (!response.ok) {
      createStatus = data.error || 'Could not create tenant.';
      return;
    }
    createStatus = `${data.tenant.name} is ready for configuration.`;
    newTenantKey = '';
    newTenantName = '';
    await loadTenants(result.activeLoad);
  }

  async function createAccount() {
    accountStatus = 'Creating access...';
    accountError = false;
    const result = await mutateWorkspace(`/admin/api/accounts?tenant=${encodeURIComponent(tenant)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
      credentials: 'same-origin',
      body: JSON.stringify({ email: accountEmail.trim(), password: accountPassword, roles: [accountRole], ...(accountRole === 'business_staff' ? {permissions: [...(accountViewCosts?['view_costs']:[]),...(accountViewSubscriptions?['view_subscriptions']:[])]} : {}) })
    }, message => { accountStatus = message; accountError = true; });
    if (!result || !isCurrentWorkspace(result.activeLoad)) return;
    const { response, data } = result;
    if (!response.ok) {
      accountStatus = data.error || 'Could not create access.';
      accountError = true;
      return;
    }
    accountStatus = `${data.account.email} can now sign in for ${result.selectedTenant} only.`;
    accountEmail = '';
    accountPassword = '';
    accountViewCosts = false;
    accountViewSubscriptions = false;
    await loadAccounts(result.selectedTenant, result.activeLoad);
  }

  async function updateAccount() {
    if (!selectedAccountId) return;
    accountStatus = 'Updating access...';
    accountError = false;
    const selected = accounts.find(account => account.id === selectedAccountId);
    if (!selected) return;
    const payload: { active: boolean; password?: string; permissions?:string[] } = { active: selectedAccountActive };
    if (selected.roles.includes('business_staff') && !selected.roles.includes('business_owner')) payload.permissions = [...(selectedViewCosts?['view_costs']:[]),...(selectedViewSubscriptions?['view_subscriptions']:[])];
    if (selectedAccountPassword) payload.password = selectedAccountPassword;
    const result = await mutateWorkspace(`/admin/api/accounts/${encodeURIComponent(selectedAccountId)}?tenant=${encodeURIComponent(tenant)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
      credentials: 'same-origin',
      body: JSON.stringify(payload)
    }, message => { accountStatus = message; accountError = true; });
    if (!result || !isCurrentWorkspace(result.activeLoad)) return;
    const { response, data } = result;
    if (!response.ok) {
      accountStatus = data.error || 'Could not update access.';
      accountError = true;
      return;
    }
    accountStatus = `${data.account.email} access updated.`;
    selectedAccountPassword = '';
    await loadAccounts(result.selectedTenant, result.activeLoad);
  }

  async function restoreOwnerAccount() {
    const selected = accounts.find(account => account.id === selectedAccountId);
    if (!isPlatform || !selected || selected.roles.length !== 1 || selected.roles[0] !== 'business_owner') return;
    accountStatus = 'Restoring business-owner access...';
    accountError = false;
    const result = await mutateWorkspace(`/admin/api/accounts/${encodeURIComponent(selectedAccountId)}?tenant=${encodeURIComponent(tenant)}`, {
      method: 'PUT', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
      body: JSON.stringify({ restore_owner_access: true })
    }, message => { accountStatus = message; accountError = true; });
    if (!result || !isCurrentWorkspace(result.activeLoad)) return;
    if (!result.response.ok) {
      accountStatus = result.data.error || 'Could not restore access.';
      accountError = true;
      return;
    }
    accountStatus = `${selected.email} has standard owner access for ${result.selectedTenant}. They must sign in again.`;
    await loadAccounts(result.selectedTenant, result.activeLoad);
  }

  async function selectTenant(nextTenant: string) {
    if(nextTenant===tenant)return;
    if((dirtyResources.length||widgetDirty||hasUnsavedDrafts())&&!await draftConfirmation.ask())return;
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
    catalog = { ...catalog, categories: [...catalog.categories, { id: `category_${crypto.randomUUID()}`, name: `New category ${number}`, items: [] }] };
  }

  function removeCategory(index: number) {
    catalog = { ...catalog, categories: catalog.categories.filter((_, current) => current !== index) };
  }

  function addProduct(categoryIndex: number) {
    const categories = catalog.categories.map((category, index) => index === categoryIndex ? {
      ...category,
      items: [...category.items, { sku: 'OFFER_'+crypto.randomUUID().replaceAll('-','').slice(0,12).toUpperCase(), name: 'New offering', price: 0, unit: 'each', tags: [], in_stock: true }]
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
    offers = [...offers, {...offer, id: `offer_${crypto.randomUUID()}`, archived: false, active: offer.deal_type !== 'signup_discount', starts_on: '', ends_on: '', product_skus: [...offer.product_skus]}];
    offersStatus = 'Copy added to current offers. Review its dates and terms, then save.';
  }

  function removeOffer(index: number) {
    offers = offers.map((offer, current) => current === index ? {...offer, archived: true, active: false} : offer);
  }

  function changeOfferType(offer: Offer, dealType: Offer['deal_type']) {
    offer.deal_type = dealType;
    if (dealType === 'signup_discount') offer.active = false;
  }

  function validSignupDiscount(offer: Offer) {
    const value = Number(offer.discount_value);
    return Number.isFinite(value) && value > 0 && value <= (offer.discount_type === 'percentage' ? 100 : 1000000)
      && Math.abs(value * 100 - Math.round(value * 100)) < 0.000001;
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
    const submitted = JSON.stringify(catalog);
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
    const result = await mutateWorkspace(`/admin/api/catalog?tenant=${encodeURIComponent(tenant)}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }, credentials: 'same-origin',
      body: JSON.stringify({ version: catalog.version || 1, currency: (catalog.currency || 'GBP').toUpperCase(), categories })
    }, message => { catalogStatus = message; catalogError = true; });
    if (!result || !isCurrentWorkspace(result.activeLoad)) return;
    const { response, data } = result;
    if (!response.ok) {
      catalogStatus = data.detail || data.error || 'Could not save catalog.';
      catalogError = true;
      return;
    }
    rememberDraft('catalog',JSON.parse(submitted));
    if (submitted === JSON.stringify(catalog)) {
      catalog = { ...catalog, categories };
      rememberDraft('catalog',catalog);
      catalogStatus = 'Catalogue saved. New conversations use these offerings.';
    } else catalogStatus = 'Submitted catalogue saved. You have unsaved edits.';
  }

  async function saveFaqs() {
    const submitted = JSON.stringify(faqs);
    faqStatus = 'Saving...';
    faqError = false;
    const payload = faqs.map((faq) => ({ q: faq.q.trim(), a: faq.a.trim(), tags: faq.tags.map((tag) => tag.trim()).filter(Boolean) }));
    if (payload.some((faq) => !faq.q || !faq.a)) {
      faqStatus = 'Every FAQ needs both a question and answer.';
      faqError = true;
      return;
    }
    const result = await mutateWorkspace(`/admin/api/faq?tenant=${encodeURIComponent(tenant)}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }, credentials: 'same-origin', body: JSON.stringify(payload)
    }, message => { faqStatus = message; faqError = true; });
    if (!result || !isCurrentWorkspace(result.activeLoad)) return;
    const { response, data } = result;
    if (!response.ok) {
      faqStatus = data.detail || data.error || 'Could not save FAQs.';
      faqError = true;
      return;
    }
    rememberDraft('faq',JSON.parse(submitted));
    if (submitted === JSON.stringify(faqs)) {
      faqs = payload;
      rememberDraft('faq',faqs);
      faqStatus = 'FAQs saved. The assistant can use the new answers now.';
    } else faqStatus = 'Submitted FAQs saved. You have unsaved edits.';
  }

  async function saveOffers() {
    const submitted = JSON.stringify(offers);
    offersStatus = 'Saving...';
    offersError = false;
    const payload = offers.map((offer) => ({
      archived: offer.archived, deal_type: offer.deal_type,
      ...(offer.deal_type === 'minimum_spend' ? {minimum_spend: offer.minimum_spend} : {}),
      ...(offer.deal_type === 'minimum_spend' || offer.deal_type === 'signup_discount' ? {discount_type: offer.discount_type, discount_value: offer.discount_value} : {}),
      id: (offer.id.trim() || slug(offer.title)), title: offer.title.trim(), description: offer.description.trim(), code: offer.code.trim(), active: Boolean(offer.active),
      starts_on: offer.starts_on, ends_on: offer.ends_on, product_skus: offer.product_skus.map((sku) => sku.trim()).filter(Boolean)
    }));
    const ids = payload.map((offer) => offer.id);
    if (offers.some((offer) => offer.deal_type === 'signup_discount' && !validSignupDiscount(offer)) || payload.some((offer) => (offer.deal_type === 'buy_one_get_one' && !offer.product_skus.length) || (offer.deal_type === 'minimum_spend' && (!(Number(offer.minimum_spend) > 0) || !(Number(offer.discount_value) > 0))) || !offer.title || !offer.description || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(offer.id) || (offer.starts_on && offer.ends_on && offer.starts_on > offer.ends_on)) || new Set(ids).size !== ids.length) {
      offersStatus = 'Check unique keys, titles, details, dates and required deal values or eligible products.';
      offersError = true;
      return;
    }
    const result = await mutateWorkspace(`/admin/api/offers?tenant=${encodeURIComponent(tenant)}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }, credentials: 'same-origin', body: JSON.stringify(payload)
    }, message => { offersStatus = message; offersError = true; });
    if (!result || !isCurrentWorkspace(result.activeLoad)) return;
    const { response, data } = result;
    if (!response.ok) {
      offersStatus = data.detail || data.error || 'Could not save offers.';
      offersError = true;
      return;
    }
    rememberDraft('offers',JSON.parse(submitted));
    if (submitted === JSON.stringify(offers)) {
      offers = normalizeOffers(payload);
      rememberDraft('offers',offers);
      offersStatus = 'Offers saved. The assistant now uses the active offers only.';
    } else offersStatus = 'Submitted offers saved. You have unsaved edits.';
  }

  async function saveDelivery() {
    const submitted = JSON.stringify(delivery);
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
    const result = await mutateWorkspace(`/admin/api/delivery?tenant=${encodeURIComponent(tenant)}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }, credentials: 'same-origin', body: JSON.stringify(payload)
    }, message => { deliveryStatus = message; deliveryError = true; });
    if (!result || !isCurrentWorkspace(result.activeLoad)) return;
    const { response, data } = result;
    if (!response.ok) {
      deliveryStatus = data.detail || data.error || 'Could not save delivery settings.';
      deliveryError = true;
      return;
    }
    rememberDraft('delivery',JSON.parse(submitted));
    deliveryStatus = 'Delivery settings saved. New conversations use these rules.';
  }

  function addBranch() {
    const number = branches.length + 1;
    branches = [...branches, { source: {}, id: `branch_${crypto.randomUUID()}`, name: `New branch ${number}`, address: '', postcode: '', phone: '', lat: null, lon: null, hours: emptyHours() }];
  }

  function removeBranch(index: number) {
    branches = branches.filter((_, current) => current !== index);
  }

  async function saveProfile() {
    const submitted = JSON.stringify(profile);
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
    const result = await mutateWorkspace(`/admin/api/profile?tenant=${encodeURIComponent(tenant)}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }, credentials: 'same-origin', body: JSON.stringify(payload)
    }, message => { profileStatus = message; profileError = true; });
    if (!result || !isCurrentWorkspace(result.activeLoad)) return;
    const { response, data } = result;
    if (!response.ok) {
      profileStatus = data.detail || data.error || 'Could not save business profile.';
      profileError = true;
      return;
    }
    rememberDraft('profile',JSON.parse(submitted));
    if (submitted === JSON.stringify(profile)) {
      profile = { ...profile, ...payload };
      rememberDraft('profile',profile);
      profileStatus = 'Business profile saved.';
    } else profileStatus = 'Submitted business profile saved. You have unsaved edits.';
  }

  async function saveBranches() {
    const submitted = JSON.stringify(branches);
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
    const result = await mutateWorkspace(`/admin/api/branches?tenant=${encodeURIComponent(tenant)}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }, credentials: 'same-origin', body: JSON.stringify(payload)
    }, message => { branchesStatus = message; branchesError = true; });
    if (!result || !isCurrentWorkspace(result.activeLoad)) return;
    const { response, data } = result;
    if (!response.ok) {
      branchesStatus = data.detail || data.error || 'Could not save branches.';
      branchesError = true;
      return;
    }
    rememberDraft('branches',JSON.parse(submitted));
    if (submitted === JSON.stringify(branches)) {
      branches = normalizeBranches(payload);
      rememberDraft('branches',branches);
      branchesStatus = 'Branches and opening hours saved.';
    } else branchesStatus = 'Submitted branches saved. You have unsaved edits.';
  }

  async function saveAgentSettings() {
    const submitted = JSON.stringify(agentSettings);
    agentStatus = 'Saving...';
    agentError = false;
    const result = await mutateWorkspace(`/admin/api/agent-settings?tenant=${encodeURIComponent(tenant)}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }, credentials: 'same-origin', body: JSON.stringify(agentSettings)
    }, message => { agentStatus = message; agentError = true; });
    if (!result || !isCurrentWorkspace(result.activeLoad)) return;
    const { response, data } = result;
    if (!response.ok) {
      agentStatus = data.error || 'Could not save agent settings.';
      agentError = true;
      return;
    }
    rememberDraft('agent-settings',JSON.parse(submitted));
    if (submitted === JSON.stringify(agentSettings)) {
      agentSettings = normalizeAgentSettings(data);
      rememberDraft('agent-settings',agentSettings);
      agentStatus = 'Agent playbook saved. New conversations use these settings.';
    } else agentStatus = 'Submitted agent playbook saved. You have unsaved edits.';
  }

  onMount(async () => {
    initialiseLanguage();
    const params = new URLSearchParams(window.location.search);
    signupOpen = params.get('apply') === '1';
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
  onDestroy(() => { providerController?.abort(); workspaceGeneration++; for (const controller of workspaceControllers) controller.abort(); });
</script>

<svelte:head>
  <title>{$t(pageTitle)} · V7</title>
  <meta name="description" content="Manage your business, customer channels and assistant from your secure Vertex Seven workspace." />
  <link rel="icon" type="image/svg+xml" href="/static/img/logo.svg?v=20261019svg" />
  <link rel="icon" type="image/png" sizes="96x96" href="/static/img/favicon-96.png?v=20261019svg" />
  <link rel="shortcut icon" href="/favicon.ico?v=20261019svg" />
  <link rel="apple-touch-icon" sizes="180x180" href="/static/img/apple-touch-icon.png?v=20261019svg" />
</svelte:head>

{#if loading}
  <main class="loading" aria-live="polite">Loading your workspace…</main>
{:else if !user}
  <main class="login-shell">
    <section class="login-intro" aria-labelledby="welcome-title">
      <a class="login-brand" href="/" aria-label="Vertex Seven home"><PlatformLogo horizontal size={180} /></a>
      <p class="eyebrow">{$t('Your business workspace')}</p>
      <h2 id="welcome-title">{$t('Customer conversations, with a clear next step.')}</h2>
      <p>{$t('Products, consultations and customer support.')} {$t('A sales assistant that knows your business.')}</p>
      <div class="intro-features"><span>{$t('Website widget')}</span><span>WhatsApp</span><span>{$t('Sales pipeline')}</span></div>
      <a href="/privacy">{$t('Privacy information')}</a>
    </section>
    <div class="login-content">
    <div class="login-tools"><LanguagePicker /></div>
    {#if passwordResetOpen && !mfa}
      <div>{#await import('./PasswordManagement.svelte')}<p class="component-loading" role="status">Loading…</p>{:then loadedPasswordManagement}<svelte:component this={loadedPasswordManagement.default} recovery {csrf} {tenant} {email} apiPrefix={import.meta.env.DEV ? '/api' : ''} on:done={() => window.location.reload()}/>{:catch}<p class="notice error" role="alert">This view could not be loaded. Reload the page to try again.</p>{/await}<button class="secondary" type="button" on:click={() => window.location.reload()}>{$t('Back to sign in')}</button></div>
    {:else if signupOpen && !mfa}
      <div>{#await import('./Registration.svelte')}<p class="component-loading" role="status">Loading…</p>{:then loadedRegistration}<svelte:component this={loadedRegistration.default} {csrf} apiPrefix={import.meta.env.DEV ? '/api' : ''} on:login={(event) => {tenant = event.detail.tenant; email = event.detail.email; signupOpen = false;}}/>{:catch}<p class="notice error" role="alert">This view could not be loaded. Reload the page to try again.</p>{/await}<button class="secondary" type="button" on:click={() => signupOpen = false}>{$t("Back to sign in")}</button></div>
    {:else}
    <form class="login" aria-busy={signingIn} on:submit|preventDefault={() => mfa ? confirmMfa() : login()}>
      <div class="login-logo"><PlatformLogo horizontal size={180} label="Vertex Seven" /></div>
      <h1>{$t(mfa ? mfa.enrollment ? 'Set up two-factor authentication' : 'Verify your sign-in' : 'Sign in to V7')}</h1>
      {#if referralSaved}<p class="notice">{$t('Referral link detected. Accept it in Subscription before your first checkout.')}</p>{/if}
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
      <label>{$t("Email or username")}<input disabled={signingIn} bind:value={email} type="text" maxlength="254" autocomplete="username" autocapitalize="none" spellcheck="false" required /></label>
      <label>{$t('Password')}<span class="password-field"><input id="login-password" disabled={signingIn} bind:value={password} type={showPassword ? 'text' : 'password'} maxlength="1024" autocomplete="current-password" required /><button disabled={signingIn} type="button" aria-controls="login-password" aria-pressed={showPassword} on:click={() => showPassword = !showPassword}>{$t(showPassword ? 'Hide password' : 'Show password')}</button></span></label>
      <button class="secondary" type="button" disabled={signingIn} on:click={() => {passwordResetOpen = true; password = '';}}>{$t('Forgot password?')}</button>
      {/if}
      <label class="remember-choice"><input type="checkbox" disabled={signingIn} bind:checked={rememberDevice}/><span>{$t('Remember this device for 30 days')}<small>{$t('Use only on your own device. You will still need your password or linked provider account.')}</small></span></label>
      {#if loginError}<div role="alert" class="notice error">{loginError}</div>{/if}
      <button disabled={signingIn} class="primary" type="submit">{$t(signingIn ? 'Please wait…' : mfa ? 'Verify and sign in' : 'Continue')}</button>
      {#if !mfa && providers.length}
        <div class="provider-divider"><span>{$t('Or use a linked account')}</span></div>
        <div class="provider-buttons">{#each providers as provider}<button class="secondary" type="button" disabled={signingIn || !provider.configured} on:click={() => providerLogin(provider.id)}>{provider.name}{!provider.configured?' · Awaiting setup':''}</button>{/each}</div>
        <p class="provider-help">{$t('Link Google in Account & security after signing in. Previously used another provider? Choose Forgot password to add a password securely using your account email.')} {#if providers.some(provider => !provider.configured)}{$t('Some providers are awaiting server setup.')}{/if}</p>
      {/if}
      {#if !mfa}<button disabled={signingIn} class="secondary" type="button" on:click={() => signupOpen = true}>{$t("Create an account or request to join")}</button>{/if}
      <p class="login-policy"><a href="/privacy">{$t('Privacy')}</a> · <a href="/cookies">{$t('Cookies')}</a> · <button class="cookie-login-trigger" type="button" aria-expanded={cookiePreferencesOpen} aria-controls={cookiePreferencesOpen ? 'workspace-cookie-preferences' : undefined} on:click={(event) => cookiePreferences?.showPreferences(event.currentTarget)}>{$t('Cookie preferences')}</button></p>
    </form>
    {/if}
    </div>
  </main>
{:else}
  <DraftGuard dirty={dirtyResources.length>0||widgetDirty} preserveOnSoftNavigation/>
  <ConfirmDialog bind:this={draftConfirmation}/>
  <a class="skip-link" href="#workspace">{$t('Skip to workspace')}</a>
  <div class="app-shell" class:nav-collapsed={navigationCollapsed} class:platform-mode={platformMode}>
    <WorkspaceNav items={primaryWorkspaces} active={platformMode ? (viewDefinition.parent || activeView) : activeWorkspace}
      {tenant} {base} platform={platformMode} administrator={isPlatform} email={user.email}
      bind:collapsed={navigationCollapsed} onSignOut={logout}/>

    <main id="workspace" class="workspace" tabindex="-1">
      <header class="workspace-head">
        <div class="workspace-title">
          <div class="workspace-breadcrumb"><span class="mobile-brand"><PlatformLogo size={26}/></span><span>{businessName}</span><span aria-hidden="true">/</span><span>{$t(workspaceDefinition.label)}</span></div>
          <h1>{$t(viewDefinition.label === 'Overview' ? workspaceDefinition.label : viewDefinition.label)}</h1>
        </div>
        <div class="workspace-actions">
          <SectionSearch items={sectionSearchItems} label={$t('Find anything')} placeholder={$t('Search your workspace…')} empty={$t('No matching sections available to your account.')} />
          <LanguagePicker />
          {#if (isPlatform || isOwner) && tenants.length > 1}
            <label class="tenant-picker">{$t('Business')}<select aria-label={$t('Business')} value={tenant} on:change={async(event)=>{const picker=event.currentTarget;await selectTenant(picker.value);picker.value=tenant;}}>{#each tenants as item}<option value={item.key}>{item.name}</option>{/each}</select></label>
          {/if}
        </div>
      </header>
      {#if activeWorkspace!=='platform' && availableViews.filter(item=>!item.hidden).length > 1}
        <nav class="workspace-tabs" aria-label={$t(workspaceDefinition.label)+' views'}>
          {#each availableViews.filter(item=>!item.hidden) as view}
            <a class:active={view.id===(viewDefinition.parent || activeView)} aria-current={view.id===(viewDefinition.parent || activeView)?'page':undefined} href={workspaceHref(base,activeWorkspace,view.id,tenant)} data-sveltekit-reload={activeWorkspace==='channels'&&(section==='website'||view.section==='website')||undefined}>{$t(view.label)}</a>
          {/each}
        </nav>
      {/if}

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
      {#each (['home','budget','spending','billing-overview'].includes(section)?[]:usageCreditAlerts) as alert}
        <section class="activation-notice" aria-label={$t('AI Budget')}><div><strong>{$t('AI Budget')}</strong><p role="alert">{usageCreditWarning(alert.code)}</p></div>{#if canViewCosts}<a href={sectionHref(base,'budget',tenant)}>{$t('Open AI Budget')} <span aria-hidden="true">↗</span></a>{/if}</section>
      {/each}
      {#if activation && !activation.active && section!=='home'}
        <section class="activation-notice" aria-label="Business activation"><span class="activation-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><rect x="5" y="10" width="14" height="11" rx="3"/><path d="M8 10V7a4 4 0 0 1 8 0v3 M12 14v3"/></svg></span><div><strong>{activation.status==='awaiting_business_approval'?'Business application required':'Business awaiting activation'}</strong><p>{activation.status==='awaiting_business_approval'?'Manual approval is required before payment and agent activation. View your application to check its status or supply business details.':'Business data editing and the agent unlock after Stripe confirms the required subscription and one-time setup payment.'}</p></div><a href={base+'/'+(activation.status==='awaiting_business_approval'?'application':'subscription')+'?tenant='+encodeURIComponent(tenant)}>{activation.status==='awaiting_business_approval'?'View application':'Open subscriptions'} <span aria-hidden="true">↗</span></a></section>
      {/if}

      {#if !mayOpenScreen(section)||!workspaceAllowed(activeWorkspace,isPlatform)}
        <section class="surface"><div class="surface-body"><h2>{$t('Access restricted')}</h2><p>{$t('This account cannot open this workspace section.')}</p><a href={base+'/'+defaultWorkspaceScreen()+'?tenant='+encodeURIComponent(tenant)}>{$t('Open your workspace')}</a></div></section>
      {:else if !isPlatform && activation && !activation.active && !['home','billing-overview','budget','spending','subscription','companies','account','cookies','privacy','application'].includes(section)}
        <section class="surface"><div class="surface-body"><h2>Activate your business</h2><p>Complete payment in Subscription to add business data and manage team access.</p></div></section>
      {:else}
      {#if !canEditCurrent}<p class="notice" role="status">You have view-only access. Ask your business owner for permission to edit this information.</p>{/if}
      {#if dirtyResources.includes(currentDraftKey)}<div class="draft-strip" role="status"><span>{$t('Unsaved changes · Your draft stays here while you move between business views.')}</span><button on:click={discardDraft}>Discard changes</button></div>{/if}
      {#if oidcNotice}<p class="notice" role="status">{$t(oidcNotice)}</p>{/if}
      {#if section === 'home'}{#key tenant}<WorkspaceHome {tenant} name={businessName} {activation} configured={tenants.find(item=>item.key===tenant)?.widget_configured??null} permissions={user.permissions||[]} {insights} activityReady={insightsAvailable} activityLoading={insightsBusy} apiPrefix={import.meta.env.DEV?'/api':''}/>{/key}{/if}
      {#if section === 'billing-overview'}{#key tenant}<BillingOverview {tenant} {canViewCosts} {canViewSubscriptions} apiPrefix={import.meta.env.DEV?'/api':''}/>{/key}{/if}
      {#if section === 'spending' && canViewCosts}{#key tenant}{#await import('./AIBudget.svelte')}<p class="component-loading" role="status">Loading…</p>{:then loadedAIBudget}<svelte:component this={loadedAIBudget.default} {tenant} {csrf} isPlatform={platformMode&&isPlatform} {canViewCosts} canManageBilling={isPlatform||isOwner} presentation="history" apiPrefix={import.meta.env.DEV?'/api':''}/>{:catch}<p class="notice error" role="alert">This view could not be loaded. Reload the page to try again.</p>{/await}{/key}{/if}
      {#if section === 'cookies'}<section class="surface"><div class="surface-body"><h2>Make this workspace yours</h2><p>Essential cookies keep sign-in and security working. You choose whether to save language preferences and allow optional analytics.</p><button class="primary" on:click={(event)=>cookiePreferences?.showPreferences(event.currentTarget)}>Manage cookie preferences</button><p><a href="/cookies">Read the cookie policy</a></p></div></section>{/if}
      {#if section === 'phone' || section === 'email'}{#key tenant+section}{#await import('./BusinessHub.svelte')}<p class="component-loading" role="status">Loading…</p>{:then loadedBusinessHub}<svelte:component this={loadedBusinessHub.default} channel={section} showRules={false} {tenant} {csrf} isPlatform={platformMode&&isPlatform} canManage={Boolean(user.permissions?.includes('business_settings.write'))} apiPrefix={import.meta.env.DEV?'/api':''}/>{:catch}<p class="notice error" role="alert">This view could not be loaded. Reload the page to try again.</p>{/await}{/key}{/if}
      {#if section === 'account'}{#if isOwner||isPlatform}<section class="workspace-business-link"><span>Manage the businesses linked to this account.</span><a href={sectionHref(base,'companies',tenant)}>Your businesses →</a></section>{/if}{#await import('./AccountSecurity.svelte')}<p class="component-loading" role="status">Loading…</p>{:then loadedAccountSecurity}<svelte:component this={loadedAccountSecurity.default} {tenant} {csrf} teamUrl={canManageAccounts ? sectionHref(base,'team',tenant) : ''} apiPrefix={import.meta.env.DEV ? '/api' : ''}/>{:catch}<p class="notice error" role="alert">This view could not be loaded. Reload the page to try again.</p>{/await}{#if isPlatform||isOwner}{#key tenant}{#await import('./Referrals.svelte')}<p class="component-loading" role="status">Loading…</p>{:then loadedReferrals}<svelte:component this={loadedReferrals.default} {tenant} {csrf} isPlatform={platformMode&&isPlatform} apiPrefix={import.meta.env.DEV ? '/api' : ''}/>{:catch}<p class="notice error" role="alert">This view could not be loaded. Reload the page to try again.</p>{/await}{/key}{/if}{/if}
      {#if section === 'privacy'}{#key tenant}{#await import('./PrivacySettings.svelte')}<p class="component-loading" role="status">Loading…</p>{:then loadedPrivacySettings}<svelte:component this={loadedPrivacySettings.default} {tenant} {csrf} canEdit={isPlatform || isOwner} apiPrefix={import.meta.env.DEV ? '/api' : ''}/>{:catch}<p class="notice error" role="alert">This view could not be loaded. Reload the page to try again.</p>{/await}{/key}{/if}
      {#if section === 'application'}{#key tenant}{#await import('./BusinessApplication.svelte')}<p class="component-loading" role="status">Loading…</p>{:then loadedBusinessApplication}<svelte:component this={loadedBusinessApplication.default} {tenant} {csrf} canEdit={isPlatform||isOwner} apiPrefix={import.meta.env.DEV ? '/api' : ''}/>{:catch}<p class="notice error" role="alert">This view could not be loaded. Reload the page to try again.</p>{/await}{/key}{/if}
      {#if section === 'applications' && isPlatform}{#await import('./BusinessApplications.svelte')}<p class="component-loading" role="status">Loading…</p>{:then loadedBusinessApplications}<svelte:component this={loadedBusinessApplications.default} {csrf} apiPrefix={import.meta.env.DEV ? '/api' : ''}/>{:catch}<p class="notice error" role="alert">This view could not be loaded. Reload the page to try again.</p>{/await}{/if}
      {#if section === 'agent'}<details class="advanced-controls"><summary>{$t('Business actions & permissions')}</summary>{#key tenant}{#await import('./AgentModules.svelte')}<p class="component-loading" role="status">Loading…</p>{:then loadedAgentModules}<svelte:component this={loadedAgentModules.default} {tenant} {csrf} isPlatform={platformMode&&isPlatform} canManage={Boolean(user.permissions?.includes('business_settings.write'))} apiPrefix={import.meta.env.DEV?'/api':''}/>{:catch}<p class="notice error" role="alert">This view could not be loaded. Reload the page to try again.</p>{/await}{/key}</details>{/if}
      {#if section === 'agent' && mayReadModelParameters()}<details class="advanced-controls" bind:open={advancedAiOpen}><summary>Advanced AI response settings</summary>{#if advancedAiOpen}{#key tenant}{#await import('./AiParameters.svelte')}<p class="component-loading" role="status">Loading…</p>{:then loadedAiParameters}<svelte:component this={loadedAiParameters.default} {tenant} {csrf} apiPrefix={import.meta.env.DEV ? '/api' : ''}/>{:catch}<p class="notice error" role="alert">This view could not be loaded. Reload the page to try again.</p>{/await}{#await import('./MemorySettings.svelte')}<p class="component-loading" role="status">Loading conversation controls…</p>{:then loadedMemory}<svelte:component this={loadedMemory.default} {tenant} {csrf} canEdit={Boolean(user.permissions?.includes(isPlatform?'models.write':'business_settings.write'))} apiPrefix={import.meta.env.DEV?'/api':''}/>{:catch}<p class="notice error" role="alert">Conversation controls could not be loaded. Reload the page to try again.</p>{/await}{/key}{/if}</details>{/if}
      {#if section === 'operations'}{#key tenant}{#await import('./BusinessHub.svelte')}<p class="component-loading" role="status">Loading…</p>{:then loadedBusinessHub}<svelte:component this={loadedBusinessHub.default} presentation={platformMode?'all':'activity'} {tenant} {csrf} isPlatform={platformMode&&isPlatform} canManage={Boolean(user?.permissions?.includes('business_settings.write'))} apiPrefix={import.meta.env.DEV ? '/api' : ''}/>{:catch}<p class="notice error" role="alert">This view could not be loaded. Reload the page to try again.</p>{/await}{/key}{/if}
      {#if section === 'platform'}
        {#if isPlatform}{#await import('./PlatformOverview.svelte')}<p class="component-loading" role="status">Loading…</p>{:then loadedPlatformOverview}<svelte:component this={loadedPlatformOverview.default} {tenant} apiPrefix={import.meta.env.DEV ? '/api' : ''} on:open={(event)=>openCompanyWorkspace(event.detail.tenant,event.detail.section)}/>{:catch}<p class="notice error" role="alert">This view could not be loaded. Reload the page to try again.</p>{/await}
        {:else}<section class="surface"><div class="surface-body"><p>This page is available only to the platform administrator. Your account manages {tenant}.</p><a href={base+'/pipeline'}>Open your company workspace</a></div></section>{/if}
      {/if}

      {#if section === 'subscription'}
        {#if canViewSubscriptions}{#key tenant}{#await import('./Subscription.svelte')}<p class="component-loading" role="status">Loading…</p>{:then loadedSubscription}<svelte:component this={loadedSubscription.default} showBudget={false} {tenant} {csrf} isPlatform={platformMode&&isPlatform} canManageBilling={isPlatform||isOwner} {canViewCosts} canViewIntegrations={Boolean(user?.permissions?.includes('integrations.read'))} apiPrefix={import.meta.env.DEV ? '/api' : ''} on:company={(event)=>selectTenant(event.detail)} on:creditstatus={(event)=>{if(activation&&event.detail.tenant===tenant)activation={...activation,usage_credit_alerts:event.detail.alerts};}}/>{:catch}<p class="notice error" role="alert">This view could not be loaded. Reload the page to try again.</p>{/await}{/key}
        {:else}<section class="surface"><div class="surface-body"><p>Your business owner must grant permission to view subscriptions.</p></div></section>{/if}
      {/if}

      {#if section === 'conversations'}
        {#if mayOpenScreen('operations')}<div class="message-views" role="group" aria-label="Messages and follow-ups"><button class:active={messagePanel==='history'} aria-pressed={messagePanel==='history'} on:click={()=>messagePanel='history'}>Conversation inbox</button><button class:active={messagePanel==='approvals'} aria-pressed={messagePanel==='approvals'} on:click={()=>{messagePanel='approvals';approvalsOpened=true;}}>Approvals & follow-ups</button></div>{/if}
        <div hidden={messagePanel!=='history'}><Conversations showViewSwitcher={false} {tenant} apiPrefix={import.meta.env.DEV?'/api':''}/></div>
        {#if approvalsOpened&&mayOpenScreen('operations')}<div hidden={messagePanel!=='approvals'}>{#key tenant}{#await import('./BusinessHub.svelte')}<p class="component-loading" role="status">Loading…</p>{:then loadedBusinessHub}<svelte:component this={loadedBusinessHub.default} presentation="activity" showRules={false} {tenant} {csrf} isPlatform={platformMode&&isPlatform} canManage={Boolean(user.permissions?.includes('business_settings.write'))} apiPrefix={import.meta.env.DEV?'/api':''}/>{:catch}<p class="notice error" role="alert">This view could not be loaded. Reload the page to try again.</p>{/await}{/key}</div>{/if}
      {/if}
      {#if section === 'usage'}
        {#if canViewCosts && isPlatform}
          {#key tenant}{#await import('./ApiUsage.svelte')}<p class="component-loading" role="status">Loading…</p>{:then loadedApiUsage}<svelte:component this={loadedApiUsage.default} {tenant} {csrf} {isPlatform} apiPrefix={import.meta.env.DEV ? '/api' : ''} />{:catch}<p class="notice error" role="alert">This view could not be loaded. Reload the page to try again.</p>{/await}{/key}
        {:else}
          <section class="surface"><div class="surface-body"><p>Your business owner must grant permission to view API usage and costs.</p></div></section>
        {/if}
      {/if}
      {#if section === 'budget' && canViewCosts}
        {#key tenant}{#await import('./AIBudget.svelte')}<p class="component-loading" role="status">Loading…</p>{:then loadedAIBudget}<svelte:component this={loadedAIBudget.default} {tenant} {csrf} isPlatform={platformMode&&isPlatform} {canViewCosts} canManageBilling={isPlatform||isOwner} apiPrefix={import.meta.env.DEV ? '/api' : ''}/>{:catch}<p class="notice error" role="alert">This view could not be loaded. Reload the page to try again.</p>{/await}{/key}
      {/if}
      {#if section === 'provider-funding' && isPlatform}
        {#await import('./ProviderFunding.svelte')}<p class="component-loading" role="status">Loading…</p>{:then loadedProviderFunding}<svelte:component this={loadedProviderFunding.default} {csrf} apiPrefix={import.meta.env.DEV ? '/api' : ''}/>{:catch}<p class="notice error" role="alert">This view could not be loaded. Reload the page to try again.</p>{/await}
      {/if}
      {#if isWidgetSection(section)}
        <section class="widget-workspace" aria-label="Website widget workspace">
          <div class="widget-workspace-intro"><div><p class="eyebrow">Customer experience</p><h2>One place to build, test and install</h2><p>Shape your chat for {businessName}, check your agent's answers and connect your website.</p></div><a href={'/chat_ui?tenant='+encodeURIComponent(tenant)} target="_blank" rel="noopener noreferrer">Open saved widget ↗</a></div>
          <div class="widget-workspace-tabs" role="group" aria-label="Widget workspace views">
            <button class:active={widgetView === 'appearance'} aria-pressed={widgetView === 'appearance'} on:click={() => widgetView = 'appearance'}>Appearance</button>
            <button class:active={widgetView === 'test'} aria-pressed={widgetView === 'test'} on:click={() => widgetView = 'test'}>Test conversation</button>
            <button class:active={widgetView === 'install'} aria-pressed={widgetView === 'install'} on:click={() => widgetView = 'install'}>Website installation</button>
            {#if widgetDirty}<span>Unsaved widget changes</span>{/if}
          </div>
          {#if widgetView === 'appearance'}
            {#key tenant}{#await import('./WidgetDesigner.svelte')}<p class="component-loading" role="status">Loading…</p>{:then loadedWidgetDesigner}<svelte:component this={loadedWidgetDesigner.default} {tenant} {previewTheme} bind:widget saving={widgetSaving} canEdit={canEditWidget} dirty={widgetDirty} status={formStatus} error={formError} on:save={saveWidget}/>{:catch}<p class="notice error" role="alert">This view could not be loaded. Reload the page to try again.</p>{/await}{/key}
          {:else if widgetView === 'test'}
            {#if widgetDirty}<p class="widget-save-notice">Your appearance changes are not saved yet. The agent test uses saved business information. <button on:click={() => widgetView = 'appearance'}>Review appearance</button></p>{/if}
            {#key tenant}{#await import('./AgentTest.svelte')}<p class="component-loading" role="status">Loading…</p>{:then loadedAgentTest}<svelte:component this={loadedAgentTest.default} {tenant} {csrf} apiPrefix={import.meta.env.DEV ? '/api' : ''} />{:catch}<p class="notice error" role="alert">This view could not be loaded. Reload the page to try again.</p>{/await}{/key}
            <details class="widget-extra"><summary>Website knowledge</summary>{#key tenant}{#await import('./WebsiteKnowledge.svelte')}<p class="component-loading" role="status">Loading…</p>{:then loadedWebsiteKnowledge}<svelte:component this={loadedWebsiteKnowledge.default} {tenant} {csrf} canEdit={canEditWidget} profileWebsite={profile.website} apiPrefix={import.meta.env.DEV ? '/api' : ''} />{:catch}<p class="notice error" role="alert">This view could not be loaded. Reload the page to try again.</p>{/await}{/key}</details>
            {#if mayReadConversionSettings()}<details class="widget-extra" id="conversion-settings"><summary>Booking, quote and payment paths</summary>{#key tenant}{#await import('./ConversionSettings.svelte')}<p class="component-loading" role="status">Loading…</p>{:then loadedConversionSettings}<svelte:component this={loadedConversionSettings.default} {tenant} {csrf} canEdit={canEditWidget} apiPrefix={import.meta.env.DEV ? '/api' : ''} />{:catch}<p class="notice error" role="alert">This view could not be loaded. Reload the page to try again.</p>{/await}{/key}</details>{/if}
          {:else}
            <div class="widget-install-grid">
              <section class="surface"><div class="surface-head"><div><p class="eyebrow">Website access</p><h2>Approve your websites</h2><p>Only approved website origins can host this company's chat.</p></div></div><form class="settings-form" on:submit|preventDefault={saveWidget}><label>Approved website origins<textarea bind:value={originText} class="origins" rows="5" disabled={!canEditWidget || widgetSaving} spellcheck="false" placeholder="https://www.yourcompany.com&#10;https://shop.yourcompany.com"></textarea><small>One exact origin per line. HTTPS is required except for local development. Include www and other subdomains separately. Leave blank to block external embedding.</small></label><div class="form-footer"><span class:error={formError} class="form-status" role={formError ? 'alert' : 'status'}>{formStatus}</span><button class="primary" type="submit" disabled={!canEditWidget || widgetSaving}>{widgetSaving ? 'Saving…' : 'Save widget & websites'}</button></div></form></section>
              {#if mayOpenScreen('implementation')}{#key tenant}{#await import('./Implementation.svelte')}<p class="component-loading" role="status">Loading…</p>{:then loadedImplementation}<svelte:component this={loadedImplementation.default} {tenant} apiPrefix={import.meta.env.DEV?'/api':''} savedSetup={{widget,embed:{snippet,iframe_snippet:iframeSnippet,chat_url:widgetChatUrl}}} embedded/>{:catch}<p class="notice error" role="alert">This view could not be loaded. Reload the page to try again.</p>{/await}{/key}{:else}<section class="surface"><div class="surface-body"><p>Your business owner can provide website installation access.</p></div></section>{/if}
            </div>
          {/if}
        </section>
      {/if}
      {#if section === 'implementation'}
        {#key tenant}{#await import('./Implementation.svelte')}<p class="component-loading" role="status">Loading…</p>{:then loadedImplementation}<svelte:component this={loadedImplementation.default} {tenant} apiPrefix={import.meta.env.DEV ? '/api' : ''} />{:catch}<p class="notice error" role="alert">This view could not be loaded. Reload the page to try again.</p>{/await}{/key}
      {/if}

      {#if section === 'statistics'}
        {#key tenant}{#await import('./Statistics.svelte')}<p class="component-loading" role="status">Loading…</p>{:then loadedStatistics}<svelte:component this={loadedStatistics.default} {tenant} {businessName} {csrf} canRecordSales={isPlatform || user.roles.includes('business_owner')} apiPrefix={import.meta.env.DEV ? '/api' : ''} />{:catch}<p class="notice error" role="alert">This view could not be loaded. Reload the page to try again.</p>{/await}{/key}        <details class="customer-question-report" bind:open={commonQuestionsOpen}><summary>Frequently asked customer questions</summary>{#if commonQuestionsOpen}<Conversations {tenant} initialView="questions" showViewSwitcher={false} apiPrefix={import.meta.env.DEV?'/api':''}/>{/if}</details>

      {/if}
      {#if section === 'whatsapp-qr'}
        {#key tenant}{#await import('./WhatsAppQr.svelte')}<p class="component-loading" role="status">Loading…</p>{:then loadedWhatsAppQr}<svelte:component this={loadedWhatsAppQr.default} {tenant} {csrf} apiPrefix={import.meta.env.DEV ? '/api' : ''} />{:catch}<p class="notice error" role="alert">This view could not be loaded. Reload the page to try again.</p>{/await}{/key}
      {/if}

      {#if section === 'companies' && (isPlatform || isOwner)}
        <section class="operator-panel" aria-labelledby="tenant-create-heading">
          <div><p class="eyebrow">Business onboarding</p><h2 id="tenant-create-heading">Add a business</h2><p>Add its information and configure the assistant before launch. Approval and verified subscription/setup requirements still apply. It starts with empty business knowledge and no approved websites. Add only information belonging to this business.</p></div>
          <form class="tenant-form" on:submit|preventDefault={createTenant}>
            <label>Business name<input bind:value={newTenantName} placeholder="Northstar Homewares" required /></label>
            <label>Business reference<input bind:value={newTenantKey} placeholder="NORTHSTAR" pattern={'[A-Za-z0-9_-]{1,64}'} required /><small>A unique short reference used in this business’s website installation code.</small></label>
            <button class="primary" type="submit" disabled={createStatus==='Creating tenant...'}>Add business</button>
          </form>
          {#if createStatus}<p class="form-status">{createStatus}</p>{/if}
        </section>
      {/if}

      {#if section === 'pipeline'}
      <section id="activity" class="surface workspace-section activity" aria-labelledby="activity-heading">
        <div class="surface-head pipeline-head"><div><p class="eyebrow">{$t("Sales pipeline")}</p><h2 id="activity-heading">Follow-up queue</h2></div><button class="secondary" type="button" disabled={insightsBusy} on:click={() => loadInsights(tenant)}>{$t("Refresh")}</button></div>
        {#if insightsAvailable}<div class="metric-grid" aria-label="Sales pipeline summary">
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
            <div class="workspace-toolbar"><a class="secondary" href={(import.meta.env.DEV?'/api':'')+'/analytics/export.csv?tenant='+encodeURIComponent(tenant)}>Export leads</a><label>Find a customer<input type="search" bind:value={salesQuery} placeholder="Name or phone…"/></label><label>Stage<select bind:value={salesStage}><option value="all">All stages</option>{#each leadStatuses as status}<option value={status}>{status}</option>{/each}</select></label></div>
            <div class="list-heading"><h3>Customer follow-ups</h3><span>{insights.sales_funnel.contacts_captured} contacts shared in 7d</span></div>
            {#each insights.leads as lead}
              {#if (salesStage==='all'||lead.status===salesStage)&&matches(salesQuery,lead.name,lead.phone)}<div class="lead-row"><div><strong>{lead.name || lead.phone || 'Contact details not supplied'}</strong><span>{lead.name && lead.phone ? lead.phone : 'Customer enquiry'}</span></div><div><select value={lead.status} disabled={insightsBusy||!user.permissions?.includes('customers.read')} aria-label={`Status for ${lead.name || lead.phone || 'lead'}`} on:change={(event) => updateLeadStatus(lead.lead_id, event.currentTarget.value as LeadStatus)}>{#each leadStatuses as status}<option value={status}>{status}</option>{/each}</select><time datetime={lead.updated_utc}>{formatActivityDate(lead.updated_utc)}</time></div></div>{/if}
            {:else}
              <p class="empty-state">New customer conversations will appear here.</p>
            {/each}
            {#if insights.leads.length&&!visibleLeadCount}<p class="empty-state">No matching leads. Try a different search or stage.</p>{/if}
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
        {:else}<div class="workspace-empty"><h3>{insightsBusy?'Loading sales activity…':'Sales activity unavailable'}</h3><p>Use Refresh to load your recorded activity. Unavailable totals are not shown as zero.</p></div>{/if}
        {#if activityStatus}<p class="activity-status" role="status">{activityStatus}</p>{/if}
      </section>
      {/if}

      {#if canManageAccounts}
        {#if section === 'team'}
      {#key tenant}{#await import('./JoinRequests.svelte')}<p class="component-loading" role="status">Loading…</p>{:then loadedJoinRequests}<svelte:component this={loadedJoinRequests.default} {tenant} {csrf} apiPrefix={import.meta.env.DEV ? '/api' : ''}/>{:catch}<p class="notice error" role="alert">This view could not be loaded. Reload the page to try again.</p>{/await}{/key}
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
              {#if isPlatform && accounts.find(account=>account.id===selectedAccountId)?.roles.join(',')==='business_owner'}
                <div class="surface-body"><p>Restore standard owner access grants management of this company's profile, catalogue, conversations, team, integrations and billing. It grants no platform-admin access and signs this login out.</p><button class="secondary" type="button" on:click={restoreOwnerAccount}>Restore standard owner access</button></div>
              {/if}
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
      {#key tenant}{#await import('./ConnectionSettings.svelte')}<p class="component-loading" role="status">Loading…</p>{:then loadedConnectionSettings}<svelte:component this={loadedConnectionSettings.default} {csrf} apiPrefix={import.meta.env.DEV ? '/api' : ''}/>{:catch}<p class="notice error" role="alert">This view could not be loaded. Reload the page to try again.</p>{/await}{/key}
      <section class="surface"><div class="surface-body"><h2>Looking for a customer channel?</h2><p>Set up your website, WhatsApp, email and phone together in Channels. Keep API and business app connections here.</p><a href={sectionHref(base,'website',tenant)}>Open Channels →</a></div></section>
      {/if}
      </div>

      {#if section === 'catalog'}
      <section id="catalog" class="surface workspace-section" aria-labelledby="catalog-heading">
        <div class="surface-head"><div><p class="eyebrow">My Business</p><h2 id="catalog-heading">Products & services</h2><p class="field-note">Keep names, prices and availability clear. Save your changes to update what your assistant recommends.</p></div><button class="secondary" disabled={!canEditCurrent} on:click={addCategory}>Add category</button></div>
        <div class="editor-search"><label>Find a product or service<input type="search" bind:value={catalogQuery} placeholder="Search names, categories or references…"/></label><label class="currency">Currency<input disabled={!canEditCurrent} bind:value={catalog.currency} maxlength="3" aria-label="Catalog currency"/></label><span class="editor-count">{catalog.categories.reduce((sum,category)=>sum+category.items.length,0)} offerings</span></div>
        <fieldset class="editor-permission" disabled={!canEditCurrent}>
        {#each catalog.categories as category,categoryIndex}
          {#if !catalogQuery.trim()||category.items.some(item=>matches(catalogQuery,category.name,item.name,item.sku,...item.tags))||matches(catalogQuery,category.name)}
          <details class="catalog-category" open={catalog.categories.length<=3||Boolean(catalogQuery.trim())}>
            <summary><span>{category.name||'New category'}</span><small>{category.items.length} offerings</small></summary>
            <div class="category-settings"><label>Category name<input bind:value={category.name} required/></label><details class="editor-advanced"><summary>Category reference</summary><label>Category key<input bind:value={category.id} required/></label><p class="field-note">Keep existing references unchanged when other systems use them.</p></details><button class="icon-button danger" on:click={()=>removeCategory(categoryIndex)} aria-label={'Remove '+(category.name||'category')}>Remove category</button></div>
            <div class="offering-cards">
            {#each category.items as item,itemIndex}
              {#if matches(catalogQuery,category.name,item.name,item.sku,...item.tags)}
              <article class="offering-card">
                <div class="offering-main"><label class="offering-name">Name<input bind:value={item.name} aria-label="Offering name" required placeholder="Product, service or package name"/></label><label>Price<input bind:value={item.price} type="number" min="0" step="0.01" aria-label="Offering price" required/></label><label>Per<input bind:value={item.unit} aria-label="Offering unit" required placeholder="each, hour, vehicle…"/></label><label class="stock-toggle"><input checked={item.stock_quantity==null?item.in_stock:item.stock_quantity>0} on:change={(event)=>item.in_stock=event.currentTarget.checked} disabled={item.stock_quantity!=null} type="checkbox"/><span>{(item.stock_quantity==null?item.in_stock:item.stock_quantity>0)?(agentSettings.playbook.offering_type==='products'?'In stock':'Available'):'Unavailable'}</span></label></div>
                <details class="editor-advanced"><summary>{agentSettings.playbook.offering_type==='products'||item.stock_quantity!=null?'References, topics & inventory':'References, topics & optional inventory'}</summary><div class="offering-advanced"><label>Reference<input bind:value={item.sku} aria-label="Offering reference" required/></label><label>Topics<input value={item.tags.join(', ')} on:input={(event)=>item.tags=event.currentTarget.value.split(',').map(tag=>tag.trim()).filter(Boolean)} aria-label="Offering tags" placeholder="Comma-separated topics"/></label><label>Stock quantity<input bind:value={item.stock_quantity} type="number" min="0" max="1000000000" step="any" placeholder="Not counted"/></label><label>Low-stock alert at<input bind:value={item.low_stock_threshold} type="number" min="0" max="1000000000" step="any" placeholder="5"/></label></div><p class="field-note">Leave quantity blank for untracked products and services. A saved quantity of zero marks this offering unavailable.</p></details>
                <div class="offering-footer"><small>{item.stock_quantity!=null?`${item.stock_quantity} ${item.unit||'units'} available`:'Availability managed manually'}</small><button class="icon-button danger" title="Remove offering" aria-label={'Remove '+(item.name||'offering')} on:click={()=>removeProduct(categoryIndex,itemIndex)}>Remove</button></div>
              </article>
              {/if}
            {/each}
            </div><button class="add-row" on:click={()=>{catalogQuery='';addProduct(categoryIndex);}}>Add product or service</button>
          </details>
          {/if}
        {:else}<div class="workspace-empty"><h3>What can customers buy from you?</h3><p>Add a category, then your products, services or packages and their prices.</p><button class="secondary" disabled={!canEditCurrent} on:click={addCategory}>Add your first category</button></div>{/each}
        {#if catalogQuery.trim()&&!catalog.categories.some(category=>matches(catalogQuery,category.name)||category.items.some(item=>matches(catalogQuery,item.name,item.sku,...item.tags)))}<div class="workspace-empty"><p>No matching products or services.</p><button class="secondary" on:click={()=>catalogQuery=''}>Clear search</button></div>{/if}
        <div class="section-footer"><span class:error={catalogError} class="form-status" role={catalogError?'alert':'status'}>{catalogStatus||'Changes apply after saving.'}</span><button class="primary" type="button" on:click={saveCatalog} disabled={!canEditCurrent||catalogStatus==='Saving...'}>Save products & services</button></div>
        </fieldset>
      </section>
      {/if}

      {#if section === 'offers'}
      {#if isPlatform}{#key tenant}{#await import('./PlatformOffers.svelte')}<p role="status">Loading platform offers…</p>{:then platformOffers}<svelte:component this={platformOffers.default} {tenant} {csrf} canManage={canEditCurrent} apiPrefix={import.meta.env.DEV?'/api':''}/>{:catch}<p role="alert">Platform offers could not be loaded. Refresh the page to try again.</p>{/await}{/key}{/if}
      <section id="offers" class="surface workspace-section" aria-labelledby="offers-heading">
        <div class="surface-head"><div><p class="eyebrow">Sales conversion</p><h2 id="offers-heading">Catalogue offers</h2></div><button class="secondary" type="button" disabled={!canEditCurrent} on:click={addOffer}>Add offer</button></div>
        <fieldset class="editor-permission" disabled={!canEditCurrent}>
        <div class="offers-list">
          {#each offers as offer, index}
            {#if !previousOffer(offer)}
            <section class="offer-editor" aria-label={`Offer ${offer.title || index + 1}`}>
              <div class="offer-heading"><h3>{offer.title || `Offer ${index + 1}`}</h3><button class="icon-button danger" type="button" title="Archive offer" aria-label={`Archive ${offer.title || 'offer'}`} on:click={() => removeOffer(index)}>Archive</button></div>
              <div class="offer-fields"><label>Offer title<input bind:value={offer.title} maxlength="120" required /></label><details class="editor-advanced"><summary>Offer reference</summary><label>Offer key<input bind:value={offer.id} maxlength="64" required /></label></details><label>Offer code<input bind:value={offer.code} maxlength="64" placeholder="WELCOME10" /></label><label class="offer-toggle"><input bind:checked={offer.active} type="checkbox" /><span>Offer is active</span></label><label>Starts on<input bind:value={offer.starts_on} type="date" /></label><label>Ends on<input bind:value={offer.ends_on} type="date" /></label><label>Deal type<select bind:value={offer.deal_type} on:change={(event) => changeOfferType(offer, event.currentTarget.value as Offer['deal_type'])}><option value="custom">Custom promotion</option><option value="buy_one_get_one">Buy 1 get 1 free</option><option value="minimum_spend">Minimum-spend deal</option><option value="signup_discount">{$t("Signup discount")}</option></select></label>
                {#if offer.deal_type === 'buy_one_get_one'}<p class="wide-field">Buy one eligible item and receive one of the same item free. Select the eligible catalogue references below.</p>{/if}
                {#if offer.deal_type === 'minimum_spend'}<label>Minimum spend (GBP)<input type="number" min="0.01" max="1000000" step="0.01" bind:value={offer.minimum_spend}/></label><label>Reward<select bind:value={offer.discount_type}><option value="percentage">Percentage off</option><option value="fixed">GBP off</option></select></label><label>Discount value<input type="number" min="0.01" max={offer.discount_type === 'percentage' ? 100 : offer.minimum_spend} step="0.01" bind:value={offer.discount_value}/></label><p class="wide-field">The minimum spend and discount apply to the eligible items, or the whole order when no references are selected.</p>{/if}
                {#if offer.deal_type === 'signup_discount'}
                  <label>Reward<select bind:value={offer.discount_type}><option value="percentage">Percentage off</option><option value="fixed">GBP off</option></select></label>
                  <label>Discount value<input type="number" min="0.01" max={offer.discount_type === 'percentage' ? 100 : 1000000} step="0.01" bind:value={offer.discount_value}/></label>
                  <p class="wide-field">{$t("Optional: turn on Offer is active when you are ready to promote this signup discount.")}</p>
                  <p class="wide-field">{$t("Explain how customers sign up with your business, who qualifies and how they redeem the discount. The assistant explains these terms; it does not create accounts, verify signup or apply checkout discounts.")}</p>
                {/if}
                <div class="wide-field"><h4>Eligible products & services</h4><OfferingPicker options={catalog.categories.flatMap(category=>category.items.map(item=>({sku:item.sku,name:item.name})))} bind:selected={offer.product_skus}/></div><label class="wide-field">{offer.deal_type === 'signup_discount' ? $t("Signup steps and eligibility") : 'Customer-facing details'}<textarea bind:value={offer.description} maxlength="600" required></textarea></label></div>
            </section>
            {/if}
          {:else}
            <div class="surface-body"><p class="empty-state">No catalogue offers have been added. Add one when you are ready to run a promotion.</p></div>
          {/each}
        </div>
        <div class="surface-body"><h3>Previous offers</h3><p>Expired and archived promotions stay here. Archive and save an offer to keep its details. To run it again, create a new offer with a new key.</p>
          {#each offers.filter(previousOffer) as offer}<article class="offer-editor"><h4>{offer.title} · {offer.archived ? 'Archived' : 'Expired'}</h4><p>{offer.description}</p><p>{offer.deal_type === 'buy_one_get_one' ? 'Buy 1 get 1 free (same item)' : offer.deal_type === 'minimum_spend' ? `Spend GBP ${offer.minimum_spend}: ${offer.discount_value}${offer.discount_type === 'percentage' ? '%' : ' GBP'} off` : offer.deal_type === 'signup_discount' ? `${$t("Signup discount")}: ${offer.discount_value}${offer.discount_type === 'percentage' ? '%' : ' GBP'}` : 'Custom promotion'}</p><p>{offer.starts_on || 'No start date'} – {offer.ends_on || 'No end date'} · {offer.code || 'No code'} · {offer.product_skus.map(reference=>catalog.categories.flatMap(category=>category.items).find(item=>item.sku===reference)?.name||reference).join(', ') || 'All offerings'}</p><button class="secondary" type="button" on:click={() => reuseOffer(offer)}>Reuse as new offer</button>{#if !offer.archived}<button class="secondary" type="button" on:click={() => removeOffer(offers.indexOf(offer))}>Archive expired offer</button>{/if}</article>{:else}<p>No previous offers saved.</p>{/each}
        </div>
        <div class="section-footer"><span class:error={offersError} class="form-status">{offersStatus}</span><button class="primary" type="button" on:click={saveOffers} disabled={!canEditCurrent||offersStatus==='Saving...'}>{$t("Save offers")}</button></div>
        </fieldset>
      </section>
      {/if}

      <div class="management-grid">
        {#if section === 'faqs'}
      <section id="faqs" class="surface workspace-section" aria-labelledby="faq-heading">
          <div class="surface-head"><div><p class="eyebrow">Sales knowledge</p><h2 id="faq-heading">Frequently asked questions</h2></div><button class="secondary" type="button" disabled={!canEditCurrent} on:click={addFaq}>Add FAQ</button></div>
          <div class="editor-search"><label>Find an answer<input type="search" bind:value={faqQuery} placeholder="Search questions, answers or topics…"/></label><span class="editor-count">{faqs.length} answers</span></div>
        <fieldset class="editor-permission" disabled={!canEditCurrent}>
          <div class="faq-list">
            {#each faqs as faq, index}
              {#if matches(faqQuery,faq.q,faq.a,...faq.tags)}<details class="faq-editor" open={faqs.length<4||Boolean(faqQuery)||!faq.q}><summary>{faq.q||'New answer'}</summary><div class="faq-fields">
                <label>Question<input bind:value={faq.q} required /></label>
                <label>Answer<textarea bind:value={faq.a} required></textarea></label>
                <div class="row-actions"><label>Topics<input value={faq.tags.join(', ')} on:input={(event) => (faq.tags = event.currentTarget.value.split(',').map((tag) => tag.trim()).filter(Boolean))} placeholder="delivery, opening hours" /></label><button class="icon-button danger" type="button" title="Remove FAQ" aria-label={`Remove FAQ ${index + 1}`} on:click={() => removeFaq(index)}>{$t("Remove")}</button></div>
              </div></details>{/if}
            {:else}
              <p class="empty-state">No FAQs yet. Add the answers customers ask for most.</p>
            {/each}
          </div>
          <div class="section-footer"><span class:error={faqError} class="form-status">{faqStatus}</span><button class="primary" type="button" on:click={saveFaqs} disabled={!canEditCurrent||faqStatus==='Saving...'}>{$t("Save FAQs")}</button></div>
        </fieldset>
        </section>
      {/if}

        {#if section === 'delivery'}
      <section id="delivery" class="surface workspace-section" aria-labelledby="delivery-heading">
          <div class="surface-head"><div><p class="eyebrow">Sales fulfillment</p><h2 id="delivery-heading">Delivery settings</h2></div><button class="secondary" type="button" disabled={!canEditCurrent} on:click={addDeliveryRule}>Add delivery area</button></div>
        <fieldset class="editor-permission" disabled={!canEditCurrent}>
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
          <div class="section-footer"><span class:error={deliveryError} class="form-status">{deliveryStatus}</span><button class="primary" type="button" on:click={saveDelivery} disabled={!canEditCurrent||deliveryStatus==='Saving...'}>Save delivery settings</button></div>
          </fieldset>
      </section>
      {/if}
      </div>

      <div class="management-grid business-grid">
        {#if section === 'profile'}
      <section id="profile" class="surface workspace-section" aria-labelledby="profile-heading">
          <div class="surface-head"><div><p class="eyebrow">Business knowledge</p><h2 id="profile-heading">{$t("Business profile")}</h2></div></div>
          <form class="profile-form" on:submit|preventDefault={saveProfile}><fieldset class="editor-permission" disabled={!canEditCurrent}>
            <fieldset class="profile-group"><legend>About your business</legend><label class="profile-wide">Business name<input bind:value={profile.name} maxlength="120" required /></label>
            <label class="profile-wide">About the business<textarea bind:value={profile.about} maxlength="1200" placeholder="What does your business do, and how do you help customers?"></textarea></label>
            </fieldset><fieldset class="profile-group"><legend>Customer contact details</legend><p class="field-note">Use the details your assistant can share with customers.</p><div class="two-fields"><label>Customer email<input bind:value={profile.email} type="email" /></label><label>{$t("Phone")}<input bind:value={profile.phone} type="tel" /></label></div>
            <label>{$t("Website")}<input bind:value={profile.website} type="url" placeholder="https://www.yourcompany.com" /><small>Save this URL, then import its public pages in Website widget → Test conversation. Add prices, availability and other critical facts to your offerings and business settings.</small></label>
            </fieldset><details class="profile-group profile-disclosure"><summary>Social profiles & certifications</summary><p class="field-note">Optional public links and qualifications your assistant can share.</p><label>Certifications<input value={profile.certifications.join(', ')} on:input={(event) => (profile.certifications = event.currentTarget.value.split(',').map((item) => item.trim()).filter(Boolean))} placeholder="B Corp, ISO 9001" /></label>
            <div class="two-fields"><label>Instagram<input bind:value={profile.social.instagram} type="url" placeholder="https://instagram.com/yourcompany" /></label><label>Facebook<input bind:value={profile.social.facebook} type="url" placeholder="https://facebook.com/yourcompany" /></label></div>
            <div class="two-fields"><label>TikTok<input bind:value={profile.social.tiktok} type="url" placeholder="https://www.tiktok.com/@yourcompany" /></label><label>Linktree<input bind:value={profile.social.linktree} type="url" placeholder="https://linktr.ee/yourcompany" /></label></div>
            </details><div class="section-footer profile-footer"><span class:error={profileError} class="form-status">{profileStatus}</span><button class="primary" type="submit" disabled={!canEditCurrent||profileStatus==='Saving...'}>{$t("Save profile")}</button></div>
          </fieldset></form>
        </section>
      {/if}

        {#if section === 'agent'}
          {#if user?.permissions?.includes('offerings.read')}
            {#key tenant}
              {#await import('./KnowledgeReview.svelte')}<p class="component-loading" role="status">Loading…</p>{:then loadedKnowledgeReview}<svelte:component this={loadedKnowledgeReview.default} endpoint={apiPath(`/admin/api/knowledge-review?tenant=${encodeURIComponent(tenant)}`)} {tenant} consoleBase={base} accessibleSections={Object.keys(sections).filter(mayOpenScreen)} />{:catch}<p class="notice error" role="alert">This view could not be loaded. Reload the page to try again.</p>{/await}
            {/key}
          {/if}
      <section id="agent" class="surface workspace-section" aria-labelledby="agent-heading">
          <div class="surface-head"><div><p class="eyebrow">Agent behavior</p><h2 id="agent-heading">Sales playbook</h2></div></div>
          <form class="agent-form" on:submit|preventDefault={saveAgentSettings}><fieldset class="editor-permission" disabled={!canEditCurrent}>
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
            <div class="section-footer profile-footer"><span class:error={agentError} class="form-status">{agentStatus}</span><button class="primary" type="submit" disabled={!canEditCurrent||agentStatus==='Saving...'}>Save playbook</button></div>
          </fieldset></form>
        </section>
      {/if}
      </div>

      {#if section === 'branches'}
      <section id="branches" class="surface workspace-section" aria-labelledby="branches-heading">
        <div class="surface-head"><div><p class="eyebrow">Locations and handoff</p><h2 id="branches-heading">Locations & opening hours</h2><p class="field-note">Keep customer locations and local opening hours clear. Mobile or online-only? Explain your service areas and availability in Business Profile and Q&A; location entries require a postcode.</p></div><button class="secondary" type="button" disabled={!canEditCurrent} on:click={addBranch}>Add branch</button></div>
        <fieldset class="editor-permission" disabled={!canEditCurrent}>
        <div class="branches-list">
          {#each branches as branch, branchIndex}
            <section class="branch-editor" aria-label={`Branch ${branch.name || branchIndex + 1}`}>
              <div class="branch-heading"><h3>{branch.name || `Branch ${branchIndex + 1}`}</h3><button class="icon-button danger" type="button" title="Remove branch" aria-label={`Remove ${branch.name || 'branch'}`} on:click={() => removeBranch(branchIndex)}>{$t("Remove")}</button></div>
              <div class="branch-fields"><label>Branch name<input bind:value={branch.name} required /></label><label>Postcode<input bind:value={branch.postcode} required /></label><label>{$t("Phone")}<input bind:value={branch.phone} type="tel" /></label><label class="wide-field">Street address<input bind:value={branch.address} /></label></div>
              <details class="editor-advanced"><summary>Location reference & map coordinates</summary><div class="two-fields"><label>Branch key<input bind:value={branch.id} required /></label><label>Latitude (optional)<input bind:value={branch.lat} type="number" min="-90" max="90" step="0.0001" /></label><label>Longitude (optional)<input bind:value={branch.lon} type="number" min="-180" max="180" step="0.0001" /></label></div></details>
              <div class="hours-grid"><h4>{$t("Opening hours")}</h4>{#each ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as day}<label>{day.toUpperCase()}<input bind:value={branch.hours[day as keyof BranchHours]} placeholder="09:00–18:00, Closed or By appointment" /></label>{/each}</div>
            </section>
          {:else}
            <p class="empty-state branches-empty">No branches yet. Add a location so the assistant can direct customers to the right place.</p>
          {/each}
        </div>
        <div class="section-footer"><span class:error={branchesError} class="form-status">{branchesStatus}</span><button class="primary" type="button" on:click={saveBranches} disabled={!canEditCurrent||branchesStatus==='Saving...'}>{$t("Save branches")}</button></div>
        </fieldset>
      </section>
      {/if}

      {#if section === 'companies' && (isPlatform || isOwner)}
        <section class="surface workspace-section"><div class="surface-head"><div><h2>Your businesses</h2><p class="field-note">Switch between the businesses this account is authorised to manage.</p></div></div><div class="editor-search"><label>Find a business<input type="search" bind:value={companyQuery} placeholder="Search business names…"/></label></div>
          {#each tenants.filter(company=>matches(companyQuery,company.name,platformMode?company.key:'')) as company}<div class="company-row"><strong>{company.name}</strong><span>{company.activation?.active?'Active':'Activation pending'}</span><button class="secondary" type="button" on:click={() => openCompanyWorkspace(company.key,'profile')}>Open business</button>{#if platformMode}<button class="secondary" on:click={()=>openCompanyWorkspace(company.key,'operations')}>Channel permissions</button>{/if}</div>{:else}<p class="empty-state">No businesses match your search.</p>{/each}
        </section>
      {/if}
      {#if section === 'errors'}
        {#await import('./ErrorsHealth.svelte')}<p class="component-loading" role="status">Loading…</p>{:then loadedErrorsHealth}<svelte:component this={loadedErrorsHealth.default} {tenant} apiPrefix={import.meta.env.DEV ? '/api' : ''}/>{:catch}<p class="notice error" role="alert">This view could not be loaded. Reload the page to try again.</p>{/await}
      {/if}
      {/if}
      </fieldset>
    </main>
  </div>
{/if}

<CookiePreferences bind:this={cookiePreferences} bind:open={cookiePreferencesOpen} />

<style>
  .login-intro {--v7-focus:var(--v7-tint-line)}
  .mfa-qr{display:block;width:240px;max-width:100%;height:auto;margin:auto;background:var(--v7-surface)}.mfa-key{display:block;overflow-wrap:anywhere;margin:12px 0}
  .activation-notice {display:flex;align-items:center;gap:14px;padding:16px 20px;margin-bottom:20px;border:1px solid var(--v7-tint-line);border-radius:var(--v7-radius-panel);background:var(--v7-tint);color:var(--v7-brand)}
  .activation-notice>div {flex:1;min-width:0}.activation-notice strong {font-size:var(--v7-text-xs);font-weight:700}.activation-notice p {margin:5px 0 0;font-size:var(--v7-text-xs);line-height:1.6;color:var(--v7-muted)}
  .activation-icon {display:grid;place-items:center;width:35px;height:35px;border:1px solid var(--v7-tint-line);border-radius:var(--v7-radius-panel);background:var(--v7-tint);flex:none}.activation-icon svg {width:19px;height:19px;fill:none;stroke:var(--v7-brand);stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}
  .activation-notice a {display:flex;align-items:center;gap:10px;padding:10px 12px;min-height:44px;border:1px solid var(--v7-tint-line);border-radius:var(--v7-radius-panel);font-size:var(--v7-text-xs);font-weight:700;color:var(--v7-brand);text-decoration:none;flex:none;background:var(--v7-surface)}.activation-notice a:hover {background:var(--v7-tint)}.activation-notice a:focus-visible {outline:3px solid var(--v7-focus);outline-offset:3px}
  @media(max-width:650px){.activation-notice{flex-wrap:wrap;align-items:flex-start;padding:15px}.activation-notice>div{flex-basis:calc(100% - 50px)}.activation-notice a{margin-inline-start:49px;min-height:40px}}
  .cookie-login-trigger {min-height:44px;padding:0;border:0;background:transparent;color:var(--v7-accent);font:inherit;cursor:pointer}
  .cookie-login-trigger:hover {text-decoration:underline;text-underline-offset:3px}
  .cookie-login-trigger:focus-visible {outline:3px solid var(--v7-focus);outline-offset:3px}
  .workspace-content { min-width:0; padding:0; margin:0; border:0; }
  .workspace-progress,.workspace-retry { display:flex; align-items:center; justify-content:space-between; gap:14px; margin-bottom:20px; padding:14px 18px; border:1px solid var(--v7-line); border-radius:var(--v7-radius-panel); }
  .workspace-progress { justify-content:flex-start; color:var(--v7-brand); background:var(--v7-soft); font-size:var(--v7-text-sm); }
  .workspace-retry p { margin:0; font-size:var(--v7-text-sm); line-height:1.6; }
  .workspace-retry button { flex-shrink:0; }
  .loading-indicator { width:16px; height:16px; flex-shrink:0; border:2px solid var(--v7-tint-line); border-top-color:var(--v7-accent); border-radius:50%; animation:workspace-spin .8s linear infinite; }
  .sr-only { position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip-path:inset(50%); white-space:nowrap; border:0; }
  @keyframes workspace-spin { to { transform:rotate(360deg); } }

  :global(body) { background: var(--v7-canvas); }
  .loading, .login-shell { min-height: 100vh; display: grid; place-items: center; color: var(--v7-muted); }
  .login-shell { padding: 24px; }
  .login { width: min(100%, 390px); display: grid; gap: 16px; padding: 32px; background: var(--v7-surface); border: 1px solid var(--v7-line); border-radius: var(--v7-radius-control); box-shadow: 0 16px 40px #2f353917; }
  h1, h2, h3, p { margin-top: 0; }
  .login h1 { margin-bottom: -8px; font-size: var(--v7-text-2xl); letter-spacing: 0; }
  .login p { color: var(--v7-muted); line-height: 1.5; }
  label { display: grid; min-width: 0; gap: 7px; color: var(--v7-ink); font-size: var(--v7-text-sm); font-weight: 700; }
  label span { color: var(--v7-muted); font-weight: 500; }
  input, textarea, select { width: 100%; min-width: 0; max-width: 100%; min-height: 40px; padding: 9px 10px; border: 1px solid var(--v7-control-line); border-radius: var(--v7-radius-control); color: var(--v7-ink); background: var(--v7-surface); font-weight: 400; }
  textarea { min-height: 84px; resize: vertical; line-height: 1.45; }
  input:focus, textarea:focus, select:focus { outline: 3px solid var(--v7-focus-ring); border-color: var(--v7-accent); }
  .primary, .secondary { min-height: 38px; border-radius: var(--v7-radius-control); padding: 0 14px; font-weight: 700; font-size: var(--v7-text-sm); }
  .primary { border: 1px solid var(--v7-accent); background: var(--v7-accent); color: #fff; }
  .primary:hover { background: var(--v7-accent-hover); }
  .secondary { border: 1px solid var(--v7-control-line); background: var(--v7-surface); color: var(--v7-ink); }
  .secondary:hover { background: var(--v7-soft); }
  .notice { padding: 10px 12px; border-radius: var(--v7-radius-control); font-size: var(--v7-text-sm); }
  .error { color: var(--v7-danger); background: var(--v7-danger-soft); }
  .app-shell { min-height: 100vh; display: grid; grid-template-columns: 248px minmax(0, 1fr); }
  .workspace { min-width: 0; width: 100%; padding: 28px clamp(16px, 3vw, 48px) 48px; }
  .workspace-head { display: flex; flex-wrap: wrap; align-items: end; justify-content: space-between; gap: 20px; margin-bottom: 24px; }
  .workspace-head h1 { margin-bottom: 0; font-size: var(--v7-text-figure); letter-spacing: 0; }
  .workspace-actions { display: flex; flex-wrap: wrap; max-width: 100%; align-items: end; gap: 10px; }
  .eyebrow { margin-bottom: 7px; color: var(--v7-accent); font-size: var(--v7-text-xs); font-weight: 800; letter-spacing: .06em; text-transform: uppercase; }
  .tenant-picker { min-width: 220px; }
  .operator-panel { display: grid; grid-template-columns: minmax(0, 1fr) minmax(360px, .9fr); gap: 24px; padding: 20px; margin-bottom: 20px; background: var(--v7-tint); border: 1px solid var(--v7-tint-line); border-radius: var(--v7-radius-control); }
  .operator-panel h2 { margin-bottom: 8px; font-size: var(--v7-text-lg); }
  .operator-panel p:not(.eyebrow) { margin-bottom: 0; color: var(--v7-muted); line-height: 1.45; }
  .tenant-form { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); align-items: end; gap: 12px; }
  .team-form, .account-control-form { display: grid; grid-template-columns: minmax(220px, 1.2fr) minmax(150px, .7fr) minmax(220px, 1fr) auto; align-items: end; gap: 12px; padding: 20px; border-bottom: 1px solid var(--v7-line); }
  .account-control-form { grid-template-columns: minmax(220px, 1.2fr) minmax(220px, 1fr) minmax(130px, .6fr) auto; background: var(--v7-canvas); }
  .account-active { display: flex; grid-template-columns: auto 1fr; align-items: center; align-self: end; min-height: 40px; gap: 8px; white-space: nowrap; }
  .account-active input { width: 16px; min-height: 16px; accent-color: var(--v7-accent); }
  .account-list { display: grid; }
  .account-row { display: grid; grid-template-columns: minmax(0, 1fr) 160px 90px; gap: 12px; align-items: center; padding: 14px 20px; border-bottom: 1px solid var(--v7-line); color: var(--v7-muted); font-size: var(--v7-text-sm); }
  .account-row strong { color: var(--v7-ink); overflow-wrap: anywhere; }
  .account-inactive { color: var(--v7-danger); }
  .team-status { display: block; margin: 14px 20px 20px; }
  .content-grid { display: grid; grid-template-columns: minmax(0, 1fr); gap: 20px; align-items: start; }
  .surface { min-width: 0; background: var(--v7-surface); border: 1px solid var(--v7-line); border-radius: var(--v7-radius-control); overflow-wrap: anywhere; }
  .surface-head { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 16px; padding: 20px; border-bottom: 1px solid var(--v7-line); }
  .surface-head h2 { margin-bottom: 0; font-size: var(--v7-text-lg); }
  .settings-form { display: grid; gap: 18px; padding: 20px; }
  small { color: var(--v7-muted); font-size: var(--v7-text-xs); font-weight: 500; line-height: 1.4; }
  .origins { min-height: 120px; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: var(--v7-text-xs); }
  .form-footer { display: flex; align-items: center; justify-content: space-between; gap: 14px; min-height: 38px; }
  .form-status { color: var(--v7-muted); font-size: var(--v7-text-sm); line-height: 1.4; }
  .form-status.error { color: var(--v7-danger); }
  .workspace-section { scroll-margin-top: 18px; }
  .pipeline-head { background: var(--v7-canvas); }
  .metric-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); border-bottom: 1px solid var(--v7-line); }
  .metric-grid > div { display: grid; gap: 6px; min-height: 116px; align-content: center; padding: 20px; }
  .metric-grid > div + div { border-left: 1px solid var(--v7-line); }
  .metric-grid span, .lead-row span, .lead-row time { color: var(--v7-muted); font-size: var(--v7-text-xs); }
  .metric-grid strong { color: var(--v7-ink); font-size: var(--v7-text-figure); line-height: 1; }
  .metric-grid small { color: var(--v7-muted); font-size: var(--v7-text-xs); font-weight: 600; }
  .funnel-strip { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); padding: 14px 20px; background: var(--v7-soft); border-bottom: 1px solid var(--v7-line); }
  .funnel-strip > div { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; padding: 5px 12px; }
  .funnel-strip > div + div { border-left: 1px solid var(--v7-line); }
  .funnel-strip span { color: var(--v7-muted); font-size: var(--v7-text-xs); }
  .funnel-strip strong { color: var(--v7-ink); font-size: var(--v7-text-lg); }
  .activity-details { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(260px, .9fr); }
  .activity-list { min-width: 0; padding: 20px; }
  .activity-list + .activity-list { border-left: 1px solid var(--v7-line); }
  .list-heading { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
  .list-heading h3 { margin: 0; color: var(--v7-ink); font-size: var(--v7-text-sm); }
  .list-heading span { color: var(--v7-muted); font-size: var(--v7-text-xs); font-weight: 700; }
  .lead-row { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 13px 0; border-top: 1px solid var(--v7-line); }
  .lead-row > div { display: grid; gap: 4px; min-width: 0; }
  .lead-row > div:last-child { text-align: right; }
  .lead-row select { min-width: 116px; min-height: 32px; font-size: var(--v7-text-xs); }
  .lead-row strong { color: var(--v7-ink); font-size: var(--v7-text-sm); overflow-wrap: anywhere; }
  .intent-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 13px 0; border-top: 1px solid var(--v7-line); color: var(--v7-muted); font-size: var(--v7-text-sm); text-transform: capitalize; }
  .intent-row strong { color: var(--v7-ink); }
  .activity-status { margin: 0; padding: 0 20px 20px; color: var(--v7-muted); font-size: var(--v7-text-sm); }
  .count-label { padding: 5px 8px; color: var(--v7-muted); background: var(--v7-soft); border: 1px solid var(--v7-line); border-radius: var(--v7-radius-pill); font-size: var(--v7-text-xs); font-weight: 700; white-space: nowrap; }
  .currency { text-transform: uppercase; }
  .stock-toggle, .collection-toggle { display: flex; grid-template-columns: auto 1fr; align-items: center; gap: 7px; color: var(--v7-ink); font-size: var(--v7-text-xs); white-space: nowrap; }
  .stock-toggle input, .collection-toggle input { width: 16px; min-height: 16px; accent-color: var(--v7-accent); }
  .icon-button { min-height: 34px; padding: 0 8px; border: 1px solid var(--v7-control-line); border-radius: var(--v7-radius-control); background: var(--v7-surface); color: var(--v7-muted); font-size: var(--v7-text-xs); font-weight: 700; }
  .icon-button:hover { background: var(--v7-canvas); }
  .icon-button.danger { color: var(--v7-danger); border-color: #f0b5af; }
  .icon-button.danger:hover { background: var(--v7-danger-soft); }
  .add-row { min-height: 34px; margin-top: 12px; padding: 0; border: 0; color: var(--v7-accent-hover); background: transparent; font-size: var(--v7-text-sm); font-weight: 800; }
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
  .offer-heading h3 { margin: 0; font-size: var(--v7-text-md); }
  .offer-fields { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
  .offer-toggle { display: flex; grid-template-columns: auto 1fr; align-items: center; align-self: end; min-height: 40px; gap: 7px; color: var(--v7-ink); font-size: var(--v7-text-xs); white-space: nowrap; }
  .offer-toggle input { width: 16px; min-height: 16px; accent-color: var(--v7-accent); }
  .surface-body { padding: 20px; }
  .surface-body > :last-child { margin-bottom: 0; }
  .surface-body > .empty-state { padding: 0; }
  .row-actions { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: end; gap: 12px; }
  .empty-state { margin: 0; padding: 14px 0; color: var(--v7-muted); font-size: var(--v7-text-sm); line-height: 1.5; }
  .delivery-content { display: grid; grid-template-columns: minmax(0, 1fr); gap: 16px; }
  .field-note { margin: -4px 0 2px; color: var(--v7-muted); font-size: var(--v7-text-xs); line-height: 1.45; }
  .delivery-rule { display: grid; grid-template-columns: minmax(0, .85fr) minmax(0, .7fr) minmax(0, .8fr) minmax(0, 1.2fr) auto; align-items: end; gap: 12px; padding: 16px 0; border-top: 1px solid var(--v7-line); }
  .exception-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-top: 4px; border-top: 1px solid var(--v7-line); }
  .exception-heading h3 { margin: 12px 0 0; font-size: var(--v7-text-sm); }
  .exception-row { display: grid; grid-template-columns: minmax(130px, .55fr) minmax(0, 1.45fr) auto; align-items: end; gap: 10px; }
  .profile-form, .agent-form { display: grid; gap: 16px; padding: 20px; }
  .profile-form { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .profile-wide, .profile-footer { grid-column: 1 / -1; }
  .agent-settings-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
  .agent-starter { display: grid; gap: 12px; padding: 18px; border: 1px solid var(--v7-tint-line); border-radius: var(--v7-radius-panel); background: var(--v7-tint); }
  .agent-starter h3 { margin: 0; color: var(--v7-brand); font-size: var(--v7-text-md); }
  .agent-starter p { margin: 6px 0 0; color: var(--v7-muted); font-size: var(--v7-text-sm); line-height: 1.5; }
  .agent-starter-controls { display: flex; align-items: end; gap: 12px; }
  .agent-starter-controls label { flex: 1; min-width: 0; }
  .agent-starter-controls button { flex-shrink: 0; }
  .agent-starter small { color: var(--v7-muted); }
  @media (max-width: 720px) { .agent-starter-controls { align-items: stretch; flex-direction: column; } }
  .agent-wide { grid-column: 1 / -1; }
  .qualification-editor { display: grid; gap: 12px; padding-top: 16px; border-top: 1px solid var(--v7-line); }
  .qualification-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
  .qualification-heading h3 { margin: 0; color: var(--v7-ink); font-size: var(--v7-text-sm); }
  .qualification-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: end; gap: 12px; }
  .two-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
  .profile-footer { padding: 2px 0 0; }
  .branches-list { display: grid; }
  .branch-editor { padding: 20px; border-bottom: 1px solid var(--v7-line); }
  .branch-heading { display: flex; align-items: center; justify-content: space-between; gap: 14px; margin-bottom: 16px; }
  .branch-heading h3 { margin: 0; font-size: var(--v7-text-md); }
  .branch-fields { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
  .wide-field { grid-column: span 2; }
  .hours-grid { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 9px; margin-top: 18px; padding-top: 18px; border-top: 1px solid var(--v7-line); }
  .hours-grid h4 { grid-column: 1 / -1; margin: 0 0 2px; color: var(--v7-ink); font-size: var(--v7-text-sm); }
  .hours-grid label { font-size: var(--v7-text-xs); text-transform: uppercase; }
  .hours-grid input { font-size: var(--v7-text-xs); text-transform: none; }
  .branches-empty { padding: 20px; }
  @media (max-width: 1050px) { .management-grid { grid-template-columns: 1fr; } .delivery-rule { grid-template-columns: repeat(2, minmax(0, 1fr)); } .delivery-rule .icon-button { width: fit-content; } }
  @media (max-width: 900px) { .content-grid, .operator-panel, .activity-details { grid-template-columns: 1fr; } .tenant-form, .team-form, .account-control-form { grid-template-columns: 1fr; } .activity-list + .activity-list { border-top: 1px solid var(--v7-line); border-left: 0; } }
  @media (max-width: 720px) { .app-shell { grid-template-columns: 1fr; } .workspace { padding: 24px 16px 40px; } .workspace-head { align-items: start; flex-direction: column; } .workspace-actions { width: 100%; align-items: end; } .tenant-picker { flex: 1; min-width: 0; width: auto; } .form-footer, .section-footer, .qualification-heading { align-items: stretch; flex-direction: column; } .form-footer .primary, .section-footer .primary { width: 100%; } .row-actions, .exception-row, .two-fields, .branch-fields, .offer-fields, .account-row, .agent-settings-grid, .qualification-row { grid-template-columns: 1fr; } .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .metric-grid > div:nth-child(3) { border-left: 0; border-top: 1px solid var(--v7-line); } .metric-grid > div:nth-child(4) { border-top: 1px solid var(--v7-line); } .funnel-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); padding: 10px; } .funnel-strip > div:nth-child(odd) { border-left: 0; } .funnel-strip > div:last-child { grid-column: span 2; } .lead-row { align-items: start; flex-direction: column; } .lead-row > div:last-child { text-align: left; } .wide-field { grid-column: auto; } .hours-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .row-actions .icon-button, .exception-row .icon-button, .branch-heading .icon-button, .offer-heading .icon-button, .qualification-row .icon-button { width: fit-content; } }
  @media (max-width: 1180px) {
    .team-form, .account-control-form { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .hours-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  }
  @media (max-width: 720px) {
    .app-shell { grid-template-rows: auto 1fr; }
    .profile-form, .team-form, .account-control-form { grid-template-columns: minmax(0, 1fr); }
    .hours-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .surface-head, .exception-heading, .branch-heading, .offer-heading { flex-wrap: wrap; }
    .collection-toggle, .offer-toggle { white-space: normal; }
    .form-footer { flex-wrap: wrap; }
  }
  @media (max-width: 420px) { .delivery-rule { grid-template-columns: minmax(0, 1fr); } }
  .widget-workspace {display:grid;gap:20px;min-width:0}
  .widget-workspace-intro {display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:16px;padding:20px 22px;border:1px solid var(--v7-line);border-radius:var(--v7-radius-panel);background:var(--v7-surface)}
  .widget-workspace-intro h2 {margin:6px 0 8px;font-size:var(--v7-text-xl);letter-spacing:-.025em}
  .widget-workspace-intro p {margin:0;font-size:var(--v7-text-xs);color:var(--v7-muted);line-height:1.6}
  .widget-workspace-intro .eyebrow {font-size:var(--v7-text-xs);color:var(--v7-accent);font-weight:700;text-transform:uppercase;letter-spacing:.08em}
  .widget-workspace-intro a {display:inline-flex;align-items:center;min-height:44px;font-size:var(--v7-text-xs);color:var(--v7-accent);text-underline-offset:3px}
  .widget-workspace-tabs {display:flex;align-items:center;gap:6px;flex-wrap:wrap;padding:5px;border:1px solid var(--v7-line);border-radius:var(--v7-radius-panel);background:var(--v7-surface)}
  .widget-workspace-tabs button {min-height:44px;border:1px solid transparent;border-radius:var(--v7-radius-control);background:transparent;padding:10px 15px;font-size:var(--v7-text-xs);font-weight:600;color:var(--v7-muted)}
  .widget-workspace-tabs button.active {color:var(--v7-accent);background:var(--v7-soft);border-color:var(--v7-line)}
  .widget-workspace-tabs>span {margin-inline-start:auto;padding:8px 12px;font-size:var(--v7-text-xs);color:var(--v7-muted)}
  .widget-extra {padding:6px 16px;border:1px solid var(--v7-line);border-radius:var(--v7-radius-panel);background:var(--v7-surface)}
  .widget-extra summary {min-height:44px;align-content:center;font-size:var(--v7-text-sm);font-weight:600;cursor:pointer}
  .widget-extra :global(section) {margin-bottom:10px}
  .widget-install-grid {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px;align-items:start;min-width:0}
  .widget-install-grid .surface {min-width:0}.widget-install-grid .surface-head p:last-child {margin:7px 0 0;font-size:var(--v7-text-xs);color:var(--v7-muted);line-height:1.6}
  .widget-save-notice {display:flex;align-items:center;flex-wrap:wrap;gap:12px;margin:0;padding:12px 16px;border:1px solid var(--v7-line);border-radius:var(--v7-radius-control);background:var(--v7-soft);font-size:var(--v7-text-xs);line-height:1.6}
  .widget-save-notice button {padding:8px 10px;min-height:44px;border:1px solid var(--v7-control-line);background:var(--v7-surface);border-radius:var(--v7-radius-control);font-size:var(--v7-text-xs)}
  @media(max-width:900px){.widget-install-grid {grid-template-columns:1fr}}
  @media(max-width:600px){.widget-workspace-intro {padding:16px}.widget-workspace-tabs>span {width:100%;margin-inline-start:0}.widget-workspace-tabs button {padding:10px;font-size:var(--v7-text-xs)}.widget-install-grid .form-footer {align-items:start;flex-direction:column}.widget-install-grid .form-footer button {width:100%}}
  .company-row { display:flex; flex-wrap:wrap; gap:16px; align-items:center; padding:16px; border-bottom:1px solid var(--v7-line); }
  .login-shell {grid-template-columns:minmax(0,1fr) minmax(380px,1fr);place-items:stretch;padding:0;background:var(--v7-canvas)}
  .login-intro {display:flex;flex-direction:column;justify-content:center;padding:40px clamp(24px,4vw,64px);background:linear-gradient(90deg,#143c30ed,#143c30c9),url('/static/img/vertex-seven-banner.svg?v=20261019svg');background-size:cover,auto 135%;background-position:center,right center;background-repeat:no-repeat;color:#fff;min-width:0}
  .login-brand,.login-logo {display:flex;align-items:center;gap:10px;font-size:var(--v7-text-lg);line-height:1.2;letter-spacing:-.025em}
  .login-brand {margin-bottom:40px;text-decoration:none;color:#fff;width:fit-content}
  .login-logo {color:var(--v7-ink)}
  .login-intro .eyebrow {color:var(--v7-tint-line);margin-bottom:20px}
  .login-intro h2 {font-size:clamp(32px,3.5vw,50px);line-height:1.15;letter-spacing:-.035em;max-width:520px;margin-bottom:24px;color:#fff}
  .login-intro p:not(.eyebrow) {font-size:var(--v7-text-md);line-height:1.7;color:var(--v7-line);max-width:480px}
  .login-intro > a:last-child {font-size:var(--v7-text-sm);color:var(--v7-line);margin-top:32px}
  .intro-features {display:flex;gap:10px;flex-wrap:wrap;margin-top:16px;font-size:var(--v7-text-xs)}
  .intro-features span {padding:9px 12px;border:1px solid var(--v7-control-line);border-radius:var(--v7-radius-pill)}
  .login-content {width:100%;max-width:620px;justify-self:center;align-self:center;padding:36px clamp(24px,5vw,64px)}
  .login-tools {display:flex;justify-content:flex-end;margin-bottom:20px}
  .login {width:100%;padding:32px;border-color:var(--v7-line);border-radius:var(--v7-radius-panel);box-shadow:0 16px 60px #2f35390a;gap:16px}
  .login h1 {font-size:var(--v7-text-2xl);line-height:1.25;letter-spacing:-.025em;margin-bottom:0}
  .login p {font-size:var(--v7-text-sm);margin-bottom:0;line-height:1.6;color:var(--v7-muted)}
  .password-field {display:flex;position:relative}
  .password-field input {padding-inline-end:124px}
  .password-field button {position:absolute;inset-inline-end:6px;top:6px;bottom:6px;min-height:30px;padding:4px 8px;border:0;border-radius:var(--v7-radius-control);background:var(--v7-soft);color:var(--v7-accent);font-size:var(--v7-text-xs);max-width:118px}
  .remember-choice {display:flex;align-items:flex-start;gap:10px;font-size:var(--v7-text-sm);line-height:1.5;font-weight:600}
  .remember-choice input {width:17px;min-height:17px;margin:2px 0 0;flex-shrink:0}
  .remember-choice span {color:var(--v7-ink)}
  .remember-choice small {display:block;margin-top:4px;font-size:var(--v7-text-xs);font-weight:400;color:var(--v7-muted)}
  .provider-divider {display:flex;align-items:center;gap:10px;font-size:var(--v7-text-xs);color:var(--v7-muted);margin:2px 0}
  .provider-divider::before,.provider-divider::after {content:'';height:1px;flex:1;background:var(--v7-line)}
  .provider-buttons {display:grid;grid-template-columns:1fr 1fr;gap:10px}
  .login .provider-help,.login .login-policy {font-size:var(--v7-text-xs);line-height:1.5}
  .login-policy a {color:var(--v7-accent)}
  .app-shell {grid-template-columns:238px minmax(0,1fr)}
  .workspace {padding:28px clamp(20px,2.6vw,40px) 48px;background:var(--v7-canvas);min-width:0}
  .workspace-head {align-items:center;padding-bottom:22px;border-bottom:1px solid var(--v7-line);margin-bottom:24px;gap:18px}
  .workspace-title {min-width:0;flex:1 1 340px}
  .workspace-head h1 {font-size:var(--v7-text-2xl);line-height:1.2;letter-spacing:-.035em;color:var(--v7-ink);font-weight:650}
  .workspace-actions {flex-wrap:wrap;justify-content:flex-end;align-items:center;gap:12px}
  .workspace-actions :global(.language-picker) {display:grid;gap:5px;align-items:start;color:var(--v7-muted);font-size:var(--v7-text-xs);line-height:1.5;font-weight:600}
  .workspace-actions :global(.language-picker select) {border-color:var(--v7-control-line);border-radius:var(--v7-radius-control);min-height:40px;font-size:var(--v7-text-xs);color:var(--v7-ink);padding:8px 10px}
  .tenant-picker {min-width:160px;font-size:var(--v7-text-xs);color:var(--v7-muted);gap:5px;font-weight:600}
  .tenant-picker select {min-height:40px;font-size:var(--v7-text-xs)}
  .surface {border-color:var(--v7-line);border-radius:var(--v7-radius);box-shadow:var(--v7-card-shadow);margin-bottom:20px}
  .workspace :global(.panel) {border-color:var(--v7-line);border-radius:var(--v7-radius);box-shadow:var(--v7-card-shadow)}
  .surface-head {background:var(--v7-surface);padding:20px 22px;border-color:var(--v7-line);border-radius:var(--v7-radius) var(--v7-radius) 0 0}
  .surface-head h2 {color:var(--v7-ink);font-size:var(--v7-text-lg);letter-spacing:-.02em;font-weight:650}
  .surface-head .eyebrow {font-size:var(--v7-text-xs);font-weight:650;letter-spacing:.08em;margin-bottom:5px}
  .primary {background:var(--v7-accent);border-color:var(--v7-accent);min-height:44px;border-radius:var(--v7-radius-control);font-weight:600;font-size:var(--v7-text-sm)}
  .primary:hover {background:var(--v7-accent-hover);border-color:var(--v7-accent-hover)}
  .secondary {color:var(--v7-ink);border-color:var(--v7-control-line);min-height:44px;border-radius:var(--v7-radius-control);font-weight:600;font-size:var(--v7-text-sm)}
  .secondary:hover {background:var(--v7-soft)}
  input,textarea,select {color:var(--v7-ink);border-color:var(--v7-control-line);border-radius:var(--v7-radius-control);min-height:44px;font-size:var(--v7-text-sm)}
  input:focus,textarea:focus,select:focus {border-color:var(--v7-accent);outline:2px solid var(--v7-focus-ring);outline-offset:1px}
  label {font-size:var(--v7-text-xs);font-weight:600;color:var(--v7-ink)}
  small,.field-note,.form-status {color:var(--v7-muted);line-height:1.6}
  .eyebrow {color:var(--v7-accent)}
  .notice {background:var(--v7-soft);color:var(--v7-brand);border:1px solid var(--v7-tint-line);padding:12px;border-radius:var(--v7-radius-control)}
  .notice.error {background:var(--v7-danger-soft);color:var(--v7-danger);border-color:#f1c5c6}
  .skip-link {position:fixed;inset-inline-start:16px;top:12px;z-index:100;transform:translateY(-200%);padding:12px 18px;background:var(--v7-soft);color:var(--v7-brand);border:1px solid var(--v7-control-line);border-radius:var(--v7-radius-control);font-weight:600}
  .skip-link:focus {transform:translateY(0)}
  .metric-grid {padding:0;gap:0;border-bottom:1px solid var(--v7-line)}
  .metric-grid > div {min-height:120px;padding:22px;border:0;border-radius:0;background:var(--v7-surface);gap:8px}
  .metric-grid > div + div {border-left:1px solid var(--v7-line)}
  .metric-grid strong {font-size:var(--v7-text-figure);color:var(--v7-ink);font-variant-numeric:tabular-nums;letter-spacing:-.04em;font-weight:650}
  .metric-grid small,.list-heading span {color:var(--v7-muted)}
  .funnel-strip {margin:18px 22px 0;padding:10px 8px;border:1px solid var(--v7-line);border-radius:var(--v7-radius-control);background:var(--v7-canvas)}
  .count-label {padding:6px 10px;background:var(--v7-soft);border-color:var(--v7-line);color:var(--v7-brand)}
  .operator-panel {padding:22px;border-radius:var(--v7-radius);background:var(--v7-surface);border-color:var(--v7-line)}
  .operator-panel p:not(.eyebrow) {color:var(--v7-muted);line-height:1.6}
  .account-row strong {color:var(--v7-ink)}
  .account-row:nth-child(even),.company-row:nth-child(odd) {background:var(--v7-soft)}
  .company-row {padding:18px 22px}
  .company-row:last-child {border-bottom:0;border-radius:0 0 var(--v7-radius) var(--v7-radius)}
  .company-row strong {flex:1 1 180px}
  .company-row span {color:var(--v7-muted);font-size:var(--v7-text-sm)}
  .offer-editor,.branch-editor {padding:22px}
  .icon-button,.add-row {min-height:44px}
  .section-footer {padding:18px 22px;background:var(--v7-soft);border-radius:0 0 var(--v7-radius) var(--v7-radius)}
  .profile-footer {padding:0;background:transparent}
  .empty-state {padding:22px 16px;line-height:1.6;border:1px dashed var(--v7-line);border-radius:var(--v7-radius-control);background:var(--v7-soft);font-size:var(--v7-text-sm)}
  .settings-form,.profile-form,.agent-form,.team-form,.account-control-form {gap:18px}
  .activity-list {padding:22px}
  .lead-row select {min-height:40px}
  .agent-starter {padding:18px;border-radius:var(--v7-radius-panel);background:var(--v7-soft);border-color:var(--v7-tint-line)}
  .activation-notice {padding:14px 16px;gap:12px;border-color:var(--v7-line);border-radius:var(--v7-radius-panel);background:var(--v7-surface)}
  .activation-icon {border:0;border-radius:var(--v7-radius-control);background:var(--v7-soft)}
  .activation-icon svg {stroke:var(--v7-accent)}
  .activation-notice strong {font-size:var(--v7-text-xs);color:var(--v7-ink);font-weight:650}
  .activation-notice p {font-size:var(--v7-text-xs);line-height:1.5;margin-top:3px}
  .activation-notice a {font-size:var(--v7-text-xs);font-weight:600;border-color:var(--v7-control-line);border-radius:var(--v7-radius-control);color:var(--v7-accent);padding:8px 12px}
  .activation-notice a:hover {background:var(--v7-soft)}
  .login {border-color:var(--v7-line);border-radius:var(--v7-radius);box-shadow:0 6px 24px #2f353906}
  .password-field button,.login-policy a {color:var(--v7-accent)}
  .login-intro .eyebrow {color:var(--v7-tint-line)}
  :global(body) {background:var(--v7-canvas)}
  @media(max-width:900px){.login-shell{grid-template-columns:1fr}.login-intro{order:2;padding:28px}.login-brand{margin-bottom:40px}.login-intro h2{font-size:var(--v7-text-2xl);max-width:650px}.login-intro> a:last-child{display:none}.login-content{order:1;padding:28px;max-width:600px}}
  @media(max-width:1100px){.workspace-title{flex-basis:100%}.workspace-actions{justify-content:flex-start}}
  @media(max-width:720px){.app-shell{grid-template-columns:1fr}.workspace{padding:22px 16px 40px}.workspace-head{gap:16px;padding-bottom:20px}.workspace-title{flex-basis:auto}.workspace-head h1{font-size:var(--v7-text-2xl)}.workspace-actions{justify-content:flex-start;align-items:end;gap:12px}.tenant-picker{min-width:0;flex:1 1 130px}.login{padding:24px}}
  @media(max-width:720px){.surface-head,.offer-editor,.branch-editor,.activity-list,.operator-panel{padding:18px}.metric-grid{padding:0;gap:0}.metric-grid>div{min-height:112px;padding:18px}.metric-grid strong{font-size:var(--v7-text-2xl)}.metric-grid>div:nth-child(3){border-inline-start:0;border-top:1px solid var(--v7-line)}.metric-grid>div:nth-child(4){border-top:1px solid var(--v7-line)}.funnel-strip{margin:16px 18px 0}.section-footer{padding:18px}.account-active{white-space:normal}.provider-buttons{grid-template-columns:1fr}}
  @media(max-width:720px){.workspace-retry{align-items:flex-start;flex-direction:column}}

  /* Six-workspace shell. Editors retain their existing scoped layout. */
  .app-shell{grid-template-columns:240px minmax(0,1fr);min-height:100dvh;align-items:start}
  .app-shell.nav-collapsed{grid-template-columns:80px minmax(0,1fr)}
  .workspace{padding:30px clamp(24px,3.2vw,56px) 64px;min-width:0;max-width:1800px;margin-inline:auto}
  .workspace-head{align-items:center;gap:24px;margin-bottom:24px;padding-bottom:24px}
  .workspace-title{flex:1 1 220px;min-width:0}.workspace-head h1{font-size:var(--v7-text-2xl);font-weight:600;letter-spacing:-.04em;margin:9px 0 0;line-height:1.25}
  .workspace-breadcrumb{display:flex;align-items:center;gap:10px;font-size:var(--v7-text-xs);line-height:1.6;color:var(--v7-muted)}
  .workspace-breadcrumb>span:first-of-type:not(.mobile-brand){max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.mobile-brand{display:none}
  .workspace-actions{gap:14px;flex:0 1 auto}.tenant-picker{min-width:150px;max-width:220px;font-size:var(--v7-text-xs)}
  .workspace-tabs{display:flex;flex:none;align-items:center;overflow-x:auto;scrollbar-width:thin;gap:8px;border-bottom:1px solid var(--v7-line);padding:0 0 12px;margin-bottom:28px;max-width:100%}
  .workspace-tabs a{display:flex;align-items:center;justify-content:center;flex:none;width:auto;min-height:42px;padding:10px 13px;border-radius:var(--v7-radius-control);border:1px solid transparent;color:var(--v7-muted);background:none;box-shadow:none;font-size:var(--v7-text-xs);font-weight:500;white-space:nowrap;text-decoration:none}
  .workspace-tabs a:hover{color:var(--v7-ink);background:#eaf0e8}.workspace-tabs a.active{color:var(--v7-accent);background:var(--v7-surface);border-color:var(--v7-line);font-weight:650;box-shadow:0 1px 2px #153a2b05}
  .primary,.secondary{min-height:44px;border-radius:var(--v7-radius-control);font-weight:600}.surface{border-radius:var(--v7-radius-panel)}.surface-head{padding:24px}.surface-body{padding:24px}.section-footer{padding:18px 24px;gap:14px;position:sticky;bottom:0;background:#fffffff5;z-index:5;border-radius:0 0 14px 14px}.workspace-retry{border-radius:var(--v7-radius-panel)}.provider-buttons{grid-template-columns:1fr}
  .editor-search{padding:0 24px 20px;display:flex;align-items:center;flex-wrap:wrap;gap:12px}.editor-search label{flex:1;min-width:180px}.editor-search input{max-width:520px}.editor-advanced{margin:10px 0;border:1px solid var(--v7-line);padding:12px 15px;border-radius:var(--v7-radius-control)}.editor-advanced summary{cursor:pointer;font-size:var(--v7-text-xs);min-height:25px;line-height:25px;color:var(--v7-muted)}.editor-advanced[open]>summary{margin-bottom:14px}.draft-strip{display:flex;align-items:center;justify-content:space-between;gap:14px;border:1px solid #decfa9;background:#fffaf0;padding:13px 17px;border-radius:var(--v7-radius-panel);margin-bottom:20px;font-size:var(--v7-text-xs);color:#64501e}.draft-strip button{min-height:44px;border:1px solid #d9cdaa;padding:8px 13px;background:var(--v7-surface);border-radius:var(--v7-radius-control);font:inherit;color:inherit}.editor-count{color:var(--v7-muted);font-size:var(--v7-text-xs)}
  @media(max-width:1100px){.workspace-actions{flex-basis:100%;justify-content:flex-start}.workspace-head{gap:18px}.workspace-actions :global(.section-search){flex:1;max-width:480px}}
  @media(max-width:850px){.app-shell,.app-shell.nav-collapsed{display:block}.workspace{padding:22px 20px calc(100px + env(safe-area-inset-bottom));max-width:100%}.workspace-head{padding-bottom:20px;margin-bottom:22px}.workspace-head h1{font-size:var(--v7-text-2xl)}.workspace-title{flex-basis:100%}.mobile-brand{display:flex;align-items:center;margin-inline-end:2px}.workspace-actions{gap:12px;width:100%;align-items:flex-end}.workspace-actions :global(.section-search){flex:1 1 180px;min-width:0}.workspace-tabs{gap:5px;margin-bottom:22px;padding-bottom:10px}.workspace-tabs a{min-height:44px;font-size:var(--v7-text-xs);padding:10px 12px}.section-footer{bottom:calc(69px + env(safe-area-inset-bottom))}.surface-head,.surface-body{padding:20px}.editor-search{padding:0 20px 20px}.tenant-picker{min-width:125px;flex:1 1 125px}.draft-strip{align-items:flex-start}}

 .catalog-category{margin:0 24px 20px;border:1px solid var(--v7-line);border-radius:var(--v7-radius-panel);background:var(--v7-canvas);overflow:hidden}.catalog-category>summary{display:flex;align-items:center;justify-content:space-between;gap:15px;padding:17px 19px;min-height:54px;cursor:pointer;font-size:var(--v7-text-sm);font-weight:600;list-style:none}.catalog-category>summary::after{content:'⌄';font-size:var(--v7-text-lg);color:var(--v7-muted)}.catalog-category>summary small{margin-inline-start:auto;font-size:var(--v7-text-xs);color:var(--v7-muted);font-weight:400}.category-settings{padding:0 18px 18px;display:flex;align-items:flex-start;flex-wrap:wrap;gap:16px}.category-settings>label{flex:1;min-width:180px}.category-settings>.editor-advanced{flex:1;min-width:180px;margin:0;background:var(--v7-surface)}.category-settings>.danger{min-height:44px}.offering-cards{display:grid;grid-template-columns:1fr;gap:12px;padding:0 18px}.offering-card{background:var(--v7-surface);padding:20px;border:1px solid var(--v7-line);border-radius:var(--v7-radius-panel)}.offering-main{display:grid;grid-template-columns:minmax(0,2fr) minmax(100px,.6fr) minmax(90px,.7fr) auto;gap:14px;align-items:end}.offering-main .stock-toggle{min-height:44px;padding:8px}.offering-advanced{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:15px}.offering-footer{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-top:10px}.offering-footer small{font-size:var(--v7-text-xs);color:var(--v7-muted)}.catalog-category>.add-row{margin:12px 18px 18px;width:calc(100% - 36px)}.catalog-category .editor-advanced{background:var(--v7-canvas)}.workspace-toolbar{display:flex;align-items:end;gap:12px;flex-wrap:wrap;margin-bottom:20px}.workspace-toolbar>label:first-child{flex:1;min-width:160px}.workspace-toolbar select{min-width:120px}
 @media(max-width:1100px){.offering-main{grid-template-columns:repeat(2,minmax(0,1fr))}.offering-name{grid-column:1/-1}.offering-main .stock-toggle{grid-column:1/-1;justify-self:start}}
 @media(max-width:600px){.catalog-category{margin:0 16px 16px}.category-settings{padding:0 14px 14px}.offering-cards{padding:0 12px}.offering-card{padding:16px}.offering-advanced{grid-template-columns:1fr}.category-settings>.editor-advanced{flex-basis:100%}}
.message-views{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:20px}.message-views button{min-height:44px;border:1px solid var(--v7-line);background:var(--v7-surface);color:var(--v7-muted);padding:10px 14px;border-radius:var(--v7-radius-control);font:inherit;font-size:var(--v7-text-xs)}.message-views button.active{background:var(--v7-tint);border-color:var(--v7-tint-line);color:var(--v7-accent)}

 .login-shell{min-height:100dvh;grid-template-columns:minmax(330px,.9fr) minmax(0,1.1fr);background:var(--v7-canvas)}.login-intro{background:var(--v7-brand);border-radius:0;padding:70px clamp(35px,5vw,90px);display:flex;flex-direction:column;justify-content:center}.login-intro h2{font-size:clamp(34px,3.5vw,50px);line-height:1.15;letter-spacing:-.05em;font-weight:550;max-width:430px}.login-intro>p:not(.eyebrow){font-size:var(--v7-text-sm);line-height:1.85;max-width:390px;color:#c5d9cb}.intro-features{display:flex;flex-direction:column;align-items:flex-start;gap:16px;margin-top:35px}.intro-features>span{border:0;background:none;padding:0;font-size:var(--v7-text-xs);color:#d0e0d2}.intro-features>span::before{content:'✓';margin-inline-end:13px;color:#a9c5ad}.login-content{padding:35px clamp(25px,5vw,80px);min-width:0;display:flex;flex-direction:column;justify-content:center}.login{max-width:450px;border:1px solid var(--v7-line);box-shadow:none;border-radius:var(--v7-radius-panel);padding:36px;background:var(--v7-surface)}.login h1{font-size:var(--v7-text-2xl);font-weight:600;letter-spacing:-.04em}.login label{font-size:var(--v7-text-xs)}.login input{min-height:47px;border-radius:var(--v7-radius-control)}.login .primary{min-height:47px}.login .remember-choice input{min-height:17px}.login-logo{margin-bottom:12px}.login-tools{margin-bottom:25px}.login .provider-help{font-size:var(--v7-text-xs);line-height:1.8}.login-intro>a{margin-top:40px;color:#b6d0bd}.login :global(.password-management){max-width:100%}
 @media(max-width:850px){.login-shell{display:flex;flex-direction:column}.login-intro{padding:30px 26px;display:block;min-height:0}.login-intro h2{font-size:var(--v7-text-2xl);max-width:500px}.login-intro>p:not(.eyebrow){font-size:var(--v7-text-xs);margin-top:12px}.intro-features{display:none}.login-intro>a{display:none}.login-content{padding:25px 20px 40px;align-items:center}.login-tools{align-self:flex-end;margin-bottom:18px}.login{padding:27px 23px;width:100%;max-width:460px}.login h1{font-size:var(--v7-text-2xl)}}

 .profile-group{border:0;border-bottom:1px solid var(--v7-line);margin:0;padding:0 0 26px;display:grid;gap:20px;min-width:0}.profile-group legend{font-size:var(--v7-text-md);font-weight:600;margin:0 0 20px;padding:0;color:var(--v7-ink)}.profile-disclosure{padding:0;border:0}.profile-disclosure>summary{font-size:var(--v7-text-sm);min-height:44px;cursor:pointer;line-height:44px;color:var(--v7-accent);font-weight:600}.profile-disclosure[open]{padding-bottom:22px;border-bottom:1px solid var(--v7-line)}.profile-disclosure[open]>label,.profile-disclosure[open]>.two-fields{margin-top:18px}.profile-group .field-note{margin:0}.faq-editor{display:block}.faq-editor>summary{min-height:44px;line-height:1.7;display:flex;align-items:center;cursor:pointer;font-size:var(--v7-text-sm);font-weight:550;gap:16px}.faq-editor>summary::after{content:'⌄';margin-inline-start:auto;color:var(--v7-muted)}.faq-fields{display:grid;gap:16px;padding-top:18px}.advanced-controls{border:1px solid var(--v7-line);background:var(--v7-surface);padding:18px 22px;border-radius:var(--v7-radius-panel);margin-bottom:22px}.advanced-controls>summary{cursor:pointer;font-size:var(--v7-text-sm);line-height:1.5;min-height:30px;align-content:center;color:var(--v7-accent);font-weight:600}.advanced-controls[open]>summary{margin-bottom:20px}.workspace-business-link{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:12px;padding:17px 20px;border:1px solid var(--v7-line);border-radius:var(--v7-radius-panel);background:var(--v7-surface);font-size:var(--v7-text-xs);margin-bottom:20px}.workspace-business-link a{color:var(--v7-accent);font-weight:600;text-decoration:none;min-height:44px;display:flex;align-items:center}.component-loading{border:1px solid var(--v7-line);border-radius:var(--v7-radius-panel);background:var(--v7-surface);padding:24px;color:var(--v7-muted);font-size:var(--v7-text-sm)}
.profile-form{grid-template-columns:minmax(0,1fr)}.profile-group{grid-column:1/-1}.editor-permission{border:0;margin:0;padding:0;min-width:0;display:contents}.editor-permission:disabled{opacity:.85}
.customer-question-report{margin-top:24px;border:1px solid var(--v7-line);border-radius:var(--v7-radius-panel);background:var(--v7-surface);padding:18px}.customer-question-report>summary{min-height:44px;display:flex;align-items:center;cursor:pointer;font-size:var(--v7-text-sm);font-weight:600;color:var(--v7-accent)}.customer-question-report[open]>summary{margin-bottom:18px}.workspace-toolbar>a{display:flex;align-items:center;text-decoration:none;font-size:var(--v7-text-xs)}
</style>
