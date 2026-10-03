"""Execute the console's actual TypeScript authentication flow with isolated HTTP."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')
TYPESCRIPT = ROOT / 'frontend/node_modules/typescript/lib/typescript.js'

pytestmark = pytest.mark.skipif(
    not NODE or not TYPESCRIPT.exists(), reason='Node and frontend npm dependencies are required',
)

SCRIPT = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const ts = require('./frontend/node_modules/typescript/lib/typescript.js');
const scenario = process.argv[1];
let source = fs.readFileSync('frontend/src/lib/Console.svelte', 'utf8').match(/<script lang="ts">([\s\S]*?)<\/script>/)[1];
const ast = ts.createSourceFile('Console.ts', source, ts.ScriptTarget.Latest, true);
for (const statement of [...ast.statements].reverse()) {
  if (ts.isImportDeclaration(statement) || (ts.isLabeledStatement(statement) && statement.label.text === '$')) {
    source = source.slice(0, statement.pos) + source.slice(statement.end);
  }
}
source = source.replace('export let section', 'let section').replaceAll('import.meta.env.DEV', 'false');
source += `
globalThis.harness = {
  restoreSession, login, confirmMfa, providerLogin, logout, loadInsights, loadTenantWorkspace, loadAccounts, loadTenants,
  mayOpenScreen, defaultWorkspaceScreen, mayReadModelParameters, mayReadConversionSettings, openDefaultWorkspace,
  identity: (value) => { user = value; tenant = value.tenant; },
  credentials: () => { email = 'synthetic@example.test'; password = 'Synthetic-fixture-password-123'; csrf = 'stale'; totp = '123456';
    catalog = {version:1,categories:[{id:'old',name:'old',items:[]}]}; profile.name = 'Old company'; accounts = [{id:'old',email:'old@synthetic.test',roles:['business_owner'],active:true,permissions:[]}];
    tenants = [{key:'OLD',name:'Old company',valid:true,widget_configured:false,activation:{active:true,status:'active'}}];
    insights.leads = [{lead_id:'old',name:null,phone:null,status:'Open',updated_utc:''}]; },
  state: () => ({user, csrf, tenant, mfa, loginError, signingIn, loading, passwordCleared: password === '', catalog,
    profile, accounts, insights, tenants,
    workspaceError: typeof workspaceError === 'undefined' ? '' : workspaceError}),
};`;
const identity = {email:'synthetic@example.test', roles:['business_staff'], tenant:'SHOP', permissions:[]};
if (scenario === 'owner-workspace') {
  identity.roles = ['business_owner'];
  identity.permissions = ['business_settings.read','offerings.read','offers.read','analytics.read','users.read'];
}
const calls = [];
const navigations = [];
let sessionReads = 0;
let mount;
const failures = {
  'password-invalid':{status:401,error:'invalid_credentials',expected:'Check your company key, email and password'},
  'password-company':{status:404,error:'unknown_tenant',expected:'Check the company key'},
  'password-csrf':{status:403,error:'csrf_failed',expected:'Reload the page, allow cookies'},
  'password-rate-limit':{status:429,error:'try_again_later',retry_after:900,expected:'900 seconds'},
  'password-global-rate-limit':{status:429,error:'too_many_requests',expected:'60 seconds'},
  'password-private-error':{status:503,error:'private-provider-detail',message:'private-provider-detail',expected:'temporarily unavailable'},
  'mfa-expired':{status:401,error:'sign_in_again',expected:'Start again'},
  'mfa-reused':{status:401,error:'authenticator_code_reused',expected:'Wait for the next code'},
  'mfa-csrf':{status:403,error:'forbidden',expected:'Reload the page, allow cookies'},
  'mfa-rate-limit':{status:429,error:'try_again_later',retry_after:900,expected:'900 seconds'},
  'mfa-invalid-rate-limit':{status:429,error:'try_again_later',retry_after:'private-provider-detail',expected:'60 seconds'},
  'mfa-private-error':{status:503,error:'private-provider-detail',expected:'temporarily unavailable'},
  'provider-unconfigured':{status:400,error:'provider_not_configured',expected:'awaiting server setup'},
  'provider-company':{status:400,error:'unknown_tenant',expected:'Check the company key'},
  'provider-rate-limit':{status:429,error:'try_again_later',expected:'60 seconds'},
};
const failure = failures[scenario];
let releaseOld, announceOld;
const oldStarted = new Promise(resolve => { announceOld = resolve; });
const oldResponse = new Promise(resolve => { releaseOld = resolve; });
const json = (status, value) => ({ok:status >= 200 && status < 300, status, json:async () => value});
const context = vm.createContext({
  URLSearchParams, URL, Object, Intl, Date, onMount:(callback)=>{mount=callback;}, initialiseLanguage:()=>{}, base:'/console', goto:async(path)=>{navigations.push(path);},
  window:{location:{search:scenario === 'invalid-tenant-deep-link' ? '?tenant=../SHOP' : '?tenant=SHOP', pathname:'/console/', href:'http://localhost/console/?tenant=SHOP'}, history:{replaceState:()=>{}}},
  fetch:async (path, options={}) => {
    calls.push({path, options});
    if (path === '/auth/session') {
      sessionReads++;
      if (scenario === 'mount-session-network-error') throw Error('private-provider-detail');
      if (scenario === 'mount-session-service-error') return json(503,{error:'private-provider-detail'});
      if (['revoked-cookie', 'revoked-tenant-deep-link'].includes(scenario) && sessionReads === 1) return json(401, {error:'unauthorized'});
      return json(200, {user:null, csrf_token:'fresh', mfa:null});
    }
    if (path === '/auth/login') {
      if (scenario.startsWith('password-') && failure) return json(failure.status,failure);
      if (scenario === 'login-network-error') throw Error('private-provider-detail');
      if (scenario === 'trusted-login' || scenario.startsWith('stale-')) return json(200, {user:identity, csrf_token:'signed-in'});
      return json(202, {mfa_required:true, mfa:{enrollment:true,email:identity.email,setup_key:'synthetic'}, csrf_token:'challenge'});
    }
    if (path === '/auth/mfa/confirm') {
      if (scenario.startsWith('mfa-') && failure) return json(failure.status,failure);
      return json(200, {user:identity, csrf_token:'signed-in'});
    }
    if (path === '/auth/oidc/google/start') return json(failure.status,failure);
    if (path === '/auth/logout') return json(200, {ok:true});
    const oldTarget = {
      'stale-workspace-response':'/admin/api/widget?tenant=OLD',
      'stale-activation-response':'/admin/api/activation?tenant=OLD',
      'stale-accounts-response':'/admin/api/accounts?tenant=OLD',
      'stale-insights-response':'/admin/api/insights?tenant=OLD&minutes=10080&limit=10',
      'stale-directory-response':'/admin/api/tenants',
    }[scenario];
    if (path === oldTarget) { announceOld(); return oldResponse; }
    if (path.startsWith('/admin/api/activation?')) return json(200, {active:true,status:'active'});
    if (scenario === 'owner-workspace' || (scenario.startsWith('stale-') && path.includes('tenant=OLD'))) {
      if (path.includes('/widget?')) return json(200, {tenant:'SHOP',widget:{allowed_origins:[]}});
      if (path.includes('/catalog?')) return json(200, {version:1,categories:[{id:'catalogue',name:'Catalogue',items:[]}]});
      if (path.includes('/profile?')) return json(200, {name:'SHOP company'});
      return json(200, {});
    }
    if (scenario === 'workspace-network-error') throw Error('private-provider-detail');
    // A limited staff account has no settings/catalog/offer/analytics reads.
    return json(403, {error:'permission_required'});
  },
});
for (const [name, role] of [['isPlatform','platform_admin'],['isOwner','business_owner']]) {
  Object.defineProperty(context, name, {get:() => vm.runInContext(`Boolean(user?.roles.includes('${role}'))`, context)});
}
vm.runInContext(ts.transpileModule(source, {compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText, context);
(async () => {
  const h = context.harness;
  h.credentials();
  if (scenario.startsWith('navigation-')) {
    const subsets = {
      'navigation-staff-no-grants':{roles:['business_staff'],permissions:[],allowed:['account'],fallback:'account'},
      'navigation-staff-reads':{roles:['business_staff'],permissions:['analytics.read','conversations.read','offerings.read','offers.read','integrations.read'],allowed:['pipeline','statistics','conversations','catalog','offers','whatsapp-qr','account'],fallback:'pipeline'},
      'navigation-owner-subset':{roles:['business_owner'],permissions:['business_settings.read'],allowed:['companies','test','agent','website','faqs','delivery','profile','branches','privacy','account'],fallback:'website',models:true},
      'navigation-operator-subset':{roles:['platform_admin'],permissions:['view_costs'],allowed:['companies','usage','account'],fallback:'usage'},
      'navigation-composite':{roles:['business_owner'],permissions:['business_settings.read','customers.read','integrations.read','analytics.read','errors.read','users.read'],allowed:['companies','team','pipeline','statistics','test','agent','website','faqs','delivery','profile','branches','privacy','integrations','implementation','whatsapp-qr','errors','account'],fallback:'pipeline',models:true,conversion:true},
      'navigation-mixed-owner':{roles:['business_owner','business_staff'],permissions:['business_settings.read'],allowed:['companies','test','agent','website','faqs','delivery','profile','branches','privacy','account'],fallback:'website'},
      'navigation-next-denied':{roles:['business_staff'],permissions:['conversations.read'],allowed:['conversations','account'],fallback:'conversations'},
      'navigation-next-granted':{roles:['business_staff'],permissions:['analytics.read'],allowed:['pipeline','statistics','account'],fallback:'pipeline'},
    };
    const subset=subsets[scenario];
    h.identity({...identity,roles:subset.roles,permissions:subset.permissions});
    const sectionNames=['subscription','platform','pipeline','statistics','test','implementation','whatsapp-qr','usage','conversations','agent','website','integrations','catalog','offers','faqs','delivery','profile','branches','team','companies','errors','account','privacy'];
    assert.deepEqual(sectionNames.filter(h.mayOpenScreen).sort(),subset.allowed.sort());
    assert.equal(h.mayOpenScreen('unknown-section'),false);
    assert.equal(h.defaultWorkspaceScreen(),subset.fallback);
    assert.equal(h.mayReadModelParameters(),Boolean(subset.models));
    assert.equal(h.mayReadConversionSettings(),Boolean(subset.conversion));
    if (scenario === 'navigation-next-denied' || scenario === 'navigation-next-granted') {
      context.window.location.search='?tenant=SHOP&next='+(scenario === 'navigation-next-denied' ? 'platform' : 'statistics');
      await h.openDefaultWorkspace();
      assert.deepEqual(navigations,['/console/'+(scenario === 'navigation-next-denied' ? 'conversations' : 'statistics')+'?tenant=SHOP']);
    }
    assert.equal(calls.length,0);
  } else if (scenario.startsWith('mount-session-')) {
    await mount();
    assert.equal(h.state().loading, false);
    assert.equal(h.state().user, null);
    assert.ok(h.state().loginError.includes('Could not load your sign-in session'));
    assert.ok(!h.state().loginError.includes('private-provider-detail'));
  } else if (failure) {
    if (scenario.startsWith('mfa-')) {await h.login();await h.confirmMfa();}
    else if (scenario.startsWith('provider-')) await h.providerLogin('google');
    else await h.login();
    assert.equal(h.state().user, null);
    assert.equal(h.state().signingIn, false);
    assert.ok(h.state().loginError.includes(failure.expected),h.state().loginError);
    assert.ok(!h.state().loginError.includes('private-provider-detail'));
    if (scenario.startsWith('mfa-')) assert.ok(h.state().mfa);
  } else if (['tenant-deep-link', 'revoked-tenant-deep-link', 'invalid-tenant-deep-link'].includes(scenario)) {
    await h.restoreSession();
    assert.equal(h.state().tenant, scenario === 'invalid-tenant-deep-link' ? 'EXAMPLE' : 'SHOP');
  } else if (scenario.startsWith('stale-')) {
    h.identity({email:'old@synthetic.test',roles:['business_owner'],tenant:'OLD',permissions:['business_settings.read','offerings.read','offers.read']});
    const pending = scenario === 'stale-accounts-response' ? h.loadAccounts('OLD')
      : scenario === 'stale-insights-response' ? h.loadInsights('OLD')
      : scenario === 'stale-directory-response' ? h.loadTenants() : h.loadTenantWorkspace('OLD');
    await oldStarted;
    await h.logout();
    await h.login();
    releaseOld(json(200, {tenant:'OLD',widget:{allowed_origins:[]},
      accounts:[{id:'old',email:'old@synthetic.test',roles:['business_owner'],active:true,permissions:[]}],
      leads:[{lead_id:'old'}],tenants:[{key:'OLD',name:'Old company'}]}));
    await pending;
    assert.equal(h.state().user.tenant, 'SHOP');
    assert.equal(h.state().tenant, 'SHOP');
    assert.equal(h.state().catalog.categories.length, 0);
    assert.equal(h.state().accounts.length, 0);
    assert.equal(h.state().insights.leads.length, 0);
    assert.equal(h.state().tenants.length, 0);
  } else if (scenario === 'owner-workspace') {
    await h.login(); await h.confirmMfa();
    assert.ok(h.state().user);
    assert.equal(h.state().workspaceError, '');
    assert.equal(h.state().catalog.categories.length, 1);
    assert.equal(h.state().profile.name, 'SHOP company');
    assert.ok(calls.some(call => call.path === '/admin/api/catalog?tenant=SHOP'));
  } else if (scenario === 'logout-clears-workspace') {
    await h.logout();
    assert.equal(h.state().catalog.categories.length, 0);
    assert.equal(h.state().profile.name, '');
    assert.equal(h.state().accounts.length, 0);
    assert.equal(h.state().insights.leads.length, 0);
    assert.equal(h.state().tenants.length, 0);
  } else if (scenario === 'insights-failure-clears-leads') {
    await h.loadInsights();
    assert.equal(h.state().insights.leads.length, 0);
  } else if (scenario === 'restricted-mfa' || scenario === 'workspace-network-error') {
    if (scenario === 'workspace-network-error') identity.permissions = ['business_settings.read'];
    await h.login();
    await h.confirmMfa();
    assert.ok(h.state().user);
    assert.equal(h.state().loginError, '');
    assert.equal(h.state().catalog.categories.length, 0);
    assert.equal(h.state().profile.name, '');
    assert.equal(h.state().accounts.length, 0);
    assert.equal(h.state().insights.leads.length, 0);
    if (scenario === 'restricted-mfa') {
      assert.equal(h.state().tenants.length, 0);
      assert.equal(h.state().workspaceError, '');
      assert.ok(!calls.some(call => /\/(widget|catalog|offers|insights)\?/.test(call.path)));
      assert.equal(h.state().tenant, 'SHOP');
      assert.deepEqual(navigations,['/console/account?tenant=SHOP']);
    } else {
      assert.equal(h.state().tenants.length, 0);
      assert.ok(h.state().workspaceError);
      assert.ok(!h.state().workspaceError.includes('private-provider-detail'));
    }
  } else {
    await h.login();
    if (scenario === 'login-network-error') {
      assert.equal(h.state().user, null);
      assert.ok(h.state().loginError);
      assert.ok(!h.state().loginError.includes('private-provider-detail'));
    } else if (scenario === 'trusted-login') {
      assert.ok(h.state().user);
      assert.equal(h.state().loginError, '');
      assert.deepEqual(navigations,['/console/account?tenant=SHOP']);
    } else {
      assert.equal(h.state().user, null);
      assert.ok(h.state().mfa?.enrollment);
      assert.ok(h.state().passwordCleared);
      assert.equal(h.state().csrf, 'challenge');
      assert.equal(calls.filter(call => call.path === '/auth/login').length, 1);
      const attempt = calls.find(call => call.path === '/auth/login');
      assert.equal(attempt.options.headers['X-CSRF-Token'], 'fresh');
      assert.equal(attempt.options.credentials, 'same-origin');
      if (scenario === 'revoked-cookie') assert.equal(sessionReads, 2);
    }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
"""


@pytest.mark.parametrize('scenario', [
    'tenant-deep-link', 'revoked-tenant-deep-link', 'invalid-tenant-deep-link',
    'password-challenge', 'revoked-cookie', 'restricted-mfa',
    'trusted-login', 'workspace-network-error', 'login-network-error',
    'logout-clears-workspace', 'insights-failure-clears-leads',
    'owner-workspace', 'stale-workspace-response', 'stale-activation-response',
    'stale-accounts-response', 'stale-insights-response', 'stale-directory-response',
    'password-invalid', 'password-company', 'password-csrf', 'password-rate-limit',
    'password-global-rate-limit', 'password-private-error', 'mfa-expired', 'mfa-reused',
    'mfa-csrf', 'mfa-rate-limit', 'mfa-invalid-rate-limit', 'mfa-private-error',
    'provider-unconfigured', 'provider-company', 'provider-rate-limit',
    'mount-session-network-error', 'mount-session-service-error',
    'navigation-staff-no-grants', 'navigation-staff-reads', 'navigation-owner-subset',
    'navigation-operator-subset', 'navigation-composite', 'navigation-mixed-owner',
    'navigation-next-denied', 'navigation-next-granted',
])
def test_console_authentication_flow(scenario):
    result = subprocess.run(
        [NODE, '-e', SCRIPT, scenario], cwd=ROOT, text=True, capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
