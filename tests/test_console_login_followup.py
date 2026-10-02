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
  restoreSession, login, confirmMfa, logout, loadInsights, loadTenantWorkspace, loadAccounts, loadTenants,
  identity: (value) => { user = value; tenant = value.tenant; },
  credentials: () => { email = 'synthetic@example.test'; password = 'Synthetic-fixture-password-123'; csrf = 'stale'; totp = '123456';
    catalog = {version:1,categories:[{id:'old',name:'old',items:[]}]}; profile.name = 'Old company'; accounts = [{id:'old',email:'old@synthetic.test',roles:['business_owner'],active:true,permissions:[]}];
    tenants = [{key:'OLD',name:'Old company',valid:true,widget_configured:false,activation:{active:true,status:'active'}}];
    insights.leads = [{lead_id:'old',name:null,phone:null,status:'Open',updated_utc:''}]; },
  state: () => ({user, csrf, tenant, mfa, loginError, passwordCleared: password === '', catalog,
    profile, accounts, insights, tenants,
    workspaceError: typeof workspaceError === 'undefined' ? '' : workspaceError}),
};`;
const identity = {email:'synthetic@example.test', roles:['business_staff'], tenant:'SHOP', permissions:[]};
if (scenario === 'owner-workspace') {
  identity.roles = ['business_owner'];
  identity.permissions = ['business_settings.read','offerings.read','offers.read','analytics.read','users.read'];
}
const calls = [];
let sessionReads = 0;
let releaseOld, announceOld;
const oldStarted = new Promise(resolve => { announceOld = resolve; });
const oldResponse = new Promise(resolve => { releaseOld = resolve; });
const json = (status, value) => ({ok:status >= 200 && status < 300, status, json:async () => value});
const context = vm.createContext({
  URLSearchParams, URL, Object, Intl, Date, onMount:()=>{}, initialiseLanguage:()=>{}, base:'/console', goto:async()=>{},
  window:{location:{search:scenario === 'invalid-tenant-deep-link' ? '?tenant=../SHOP' : '?tenant=SHOP', pathname:'/console/', href:'http://localhost/console/?tenant=SHOP'}, history:{replaceState:()=>{}}},
  fetch:async (path, options={}) => {
    calls.push({path, options});
    if (path === '/auth/session') {
      sessionReads++;
      if (['revoked-cookie', 'revoked-tenant-deep-link'].includes(scenario) && sessionReads === 1) return json(401, {error:'unauthorized'});
      return json(200, {user:null, csrf_token:'fresh', mfa:null});
    }
    if (path === '/auth/login') {
      if (scenario === 'login-network-error') throw Error('private-provider-detail');
      if (scenario === 'trusted-login' || scenario.startsWith('stale-')) return json(200, {user:identity, csrf_token:'signed-in'});
      return json(202, {mfa_required:true, mfa:{enrollment:true,email:identity.email,setup_key:'synthetic'}, csrf_token:'challenge'});
    }
    if (path === '/auth/mfa/confirm') {
      return json(200, {user:identity, csrf_token:'signed-in'});
    }
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
  if (['tenant-deep-link', 'revoked-tenant-deep-link', 'invalid-tenant-deep-link'].includes(scenario)) {
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
])
def test_console_authentication_flow(scenario):
    result = subprocess.run(
        [NODE, '-e', SCRIPT, scenario], cwd=ROOT, text=True, capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
