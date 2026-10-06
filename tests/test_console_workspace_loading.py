"""Execute console loading: bounded reads, tenant isolation and safe editor retries."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')
pytestmark = pytest.mark.skipif(
    not NODE or not (ROOT / 'frontend/node_modules/typescript/lib/typescript.js').exists(),
    reason='Node and frontend npm dependencies are required',
)

SCRIPT = r"""
const fs=require('node:fs'), vm=require('node:vm'), assert=require('node:assert/strict');
const ts=require('./frontend/node_modules/typescript/lib/typescript.js');
const scenario=process.argv[1];
let source=fs.readFileSync('frontend/src/lib/Console.svelte','utf8').match(/<script lang="ts">([\s\S]*?)<\/script>/)[1];
const ast=ts.createSourceFile('Console.ts',source,ts.ScriptTarget.Latest,true);
for(const statement of [...ast.statements].reverse()) {
  if(ts.isImportDeclaration(statement)||ts.isLabeledStatement(statement)) source=source.slice(0,statement.pos)+source.slice(statement.end);
}
source=source.replace('export let section','let section').replaceAll('import.meta.env.DEV','false');
source+=`globalThis.h={loadSignedInWorkspace,loadWorkspaceSection,selectTenant,retryWorkspace,retryTenantDirectory,saveWidget,openCompanyWorkspace,openDefaultWorkspace,logout,
 identity:(value)=>{user=value;tenant=value.tenant;csrf='synthetic-csrf';},
 screen:(value)=>{section=value;}, permissions:(value)=>{user={...user,permissions:value};},
 edit:()=>{catalog.categories[0].name='Unsaved category';},
 editWidget:()=>{widget={...widget,assistant_name:'Unsaved assistant',accent_color:'#15324F',background_color:'#FFFFFF'};originText='https://shop.synthetic.test';},
 state:()=>({tenant,workspaceBusy,workspaceError,tenantDirectoryBusy,tenantDirectoryError,catalog,profile,insights,accounts,widget,originText,snippet,iframeSnippet,widgetChatUrl,savedWidgetFingerprint,widgetSaving,formStatus,formError,hasUser:Boolean(user)})};`;
const calls=[], navigation=[], timers=new Map(); let timerId=0, destroy, fail=true;
let heldResolve;
const held=new Promise(resolve=>{heldResolve=resolve;});
const response=(data,status=200)=>({ok:status===200,status,json:async()=>data});
const widgetPayload=company=>({widget:{assistant_name:company+' assistant',chat_title:'Business support',greeting:'How can we help?',avatar:'',company_logo_url:'',style:'midnight',accent_color:'#3EEA8C',background_color:'',surface_color:'',text_color:'',bubble_color:'',allowed_origins:['https://'+company.toLowerCase()+'.synthetic.test']},embed:{snippet:'script-'+company,iframe_snippet:'panel-'+company,chat_url:'/chat_ui?tenant='+company}});
const location={search:'?tenant=OLD',pathname:'/console/pipeline',href:'http://localhost/console/pipeline?tenant=OLD',
 assign:target=>navigation.push({method:'assign',target}),replace:target=>navigation.push({method:'replace',target})};
const context=vm.createContext({AbortController,URL,URLSearchParams,Date,Intl,
 onMount:()=>{},onDestroy:callback=>{destroy=callback;},initialiseLanguage:()=>{},base:'/console',goto:async target=>{navigation.push({method:'goto',target});},
 window:{location,history:{replaceState:()=>{}}},
 setTimeout:(callback,delay)=>{const id=++timerId;timers.set(id,{callback,delay});return id;},clearTimeout:id=>timers.delete(id),
 fetch:async(path,options)=>{
   const {signal}=options;calls.push({path,signal,options});
   if(path.includes('/widget?')&&options.method==='PUT') {
     if(['widget-save-tenant','widget-save-destroy','widget-save-duplicate'].includes(scenario)) return held;
     if(scenario==='widget-save-timeout') return new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(Error('Private provider text')),{once:true}));
     if(scenario==='widget-save-failure'&&fail) throw Error('Private provider text');
     return response({widget:JSON.parse(options.body),embed:widgetPayload('OLD').embed});
   }
   if(['directory-independent','directory-restart'].includes(scenario)&&path==='/admin/api/tenants') return new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(Error('aborted')),{once:true}));
   if(['timeout','body-timeout'].includes(scenario)&&path.includes('/catalog?')) {
     const stalled=new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(Error('Private provider text')),{once:true}));
     return scenario==='timeout'?stalled:{ok:true,status:200,json:()=>stalled};
   }
   if(['tenant-change','destroy'].includes(scenario)&&path.includes('/catalog?tenant=OLD')) return held;
   if(['retry-catalog','retry-insights','retry-accounts'].includes(scenario)&&fail&&path.includes('/'+scenario.slice(6)+'?')) return response({},503);
   if(scenario==='malformed-body'&&fail&&path.includes('/catalog?')) return {ok:true,status:200,json:async()=>{throw Error('Malformed private response');}};
   if(path.includes('/catalog?')) return response({version:1,categories:[{id:'one',name:path.includes('NEW')?'New company category':'Saved category',items:[]}]});
   if(path.includes('/profile?')) return response({name:'Loaded profile'});
   if(path.includes('/widget?')) return response(widgetPayload(new URLSearchParams(path.split('?')[1]).get('tenant')));
   if(path.includes('/activation?')) return response({active:true,status:'active'});
   if(path.includes('/insights?')) return response({leads:[{lead_id:'one',status:'Open'}]});
   if(path.includes('/accounts?')) return response({accounts:[]});
   if(path==='/admin/api/tenants') return response({tenants:[]});
   return response({});
 }
});
Object.defineProperty(context,'isOwner',{get:()=>scenario==='role-reactivity'?false:vm.runInContext("Boolean(user?.roles.includes('business_owner'))",context)});
Object.defineProperty(context,'isPlatform',{get:()=>false});
vm.runInContext(ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText,context);
const h=context.h;
const identity={email:'owner@synthetic.test',roles:['business_owner'],tenant:'OLD',permissions:['analytics.read','offerings.read','business_settings.read','business_settings.write','users.read']};
h.identity(identity);
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 if(scenario==='pipeline-only'||scenario==='role-reactivity') {
   await h.loadSignedInWorkspace(); await flush();
   assert.equal(calls.length,3);
   assert.ok(calls.some(c=>c.path.includes('/insights?')));
   assert.ok(!calls.some(c=>/\/(catalog|widget|profile|accounts|faq|offers)\?/.test(c.path)));
 } else if(scenario==='cached-edits') {
   await h.loadWorkspaceSection('catalog');h.edit();
   await h.loadWorkspaceSection('profile');await h.loadWorkspaceSection('catalog');
   assert.equal(h.state().catalog.categories[0].name,'Unsaved category');
   assert.equal(calls.filter(c=>c.path.includes('/catalog?')).length,1);
   assert.equal(calls.filter(c=>c.path.includes('/activation?')).length,1);
 } else if(scenario==='directory-independent'||scenario==='directory-restart') {
   await h.loadSignedInWorkspace();
   assert.equal(h.state().workspaceBusy,false);assert.equal(h.state().tenantDirectoryBusy,true);
   assert.equal(h.state().workspaceError,'');
   if(scenario==='directory-restart') {
     await h.selectTenant('NEW');
     const directoryCalls=calls.filter(c=>c.path==='/admin/api/tenants');
     assert.equal(directoryCalls.length,2);assert.ok(directoryCalls[0].signal.aborted);
     assert.equal(h.state().tenantDirectoryBusy,true);
   }
   destroy();await flush();
 } else if(scenario.startsWith('retry-')||scenario==='malformed-body') {
   const screen={'retry-catalog':'catalog','retry-insights':'pipeline','retry-accounts':'team','malformed-body':'catalog'}[scenario];
   await h.loadWorkspaceSection(screen);
   assert.ok(h.state().workspaceError);assert.equal(h.state().workspaceBusy,false);
   fail=false; await h.loadWorkspaceSection(screen);
   assert.equal(h.state().workspaceError,'');
   assert.equal(calls.filter(c=>c.path.includes('/activation?')).length,1);
   assert.equal(calls.filter(c=>c.path.includes('/'+(scenario==='malformed-body'?'catalog':scenario.slice(6))+'?')).length,2);
 } else if(scenario==='timeout'||scenario==='body-timeout') {
   const load=h.loadWorkspaceSection('catalog');await flush();
   assert.equal(h.state().workspaceBusy,true);
   for(const [id,timer] of [...timers]) {assert.equal(timer.delay,20000);timers.delete(id);timer.callback();}
   await load;assert.equal(h.state().workspaceBusy,false);assert.ok(h.state().workspaceError);
   assert.ok(!h.state().workspaceError.includes('Private provider'));
   assert.ok(calls.find(c=>c.path.includes('/catalog?')).signal.aborted);
 } else if(scenario==='tenant-change') {
   const old=h.loadWorkspaceSection('catalog');await flush();
   await h.selectTenant('NEW');
   heldResolve(response({version:1,categories:[{id:'old',name:'Private old company',items:[]}]}));await old;
   assert.ok(calls.find(c=>c.path.includes('/catalog?tenant=OLD')).signal.aborted);
   assert.equal(h.state().tenant,'NEW');assert.equal(h.state().catalog.categories.length,0);
   await h.loadWorkspaceSection('catalog');assert.equal(h.state().catalog.categories[0].name,'New company category');
 } else if(scenario==='widget-cached-edits') {
   await h.loadWorkspaceSection('website');h.editWidget();
   await h.loadWorkspaceSection('test');await h.loadWorkspaceSection('website');
   assert.equal(h.state().widget.assistant_name,'Unsaved assistant');assert.equal(h.state().originText,'https://shop.synthetic.test');
   for(const resource of ['widget','profile','activation']) assert.equal(calls.filter(c=>c.path.includes('/'+resource+'?')).length,1);
 } else if(scenario==='widget-save-tenant'||scenario==='widget-save-destroy') {
   h.screen('website');await h.loadWorkspaceSection('website');h.editWidget();
   const saving=h.saveWidget();await flush();const save=calls.find(c=>c.options.method==='PUT');
   assert.equal(h.state().widgetSaving,true);assert.ok(save.path.endsWith('?tenant=OLD'));
   if(scenario==='widget-save-tenant')await h.selectTenant('NEW');else destroy();
   const before=JSON.stringify(h.state());heldResolve(response(widgetPayload('OLD')));await saving;
   assert.equal(JSON.stringify(h.state()),before,'An obsolete save must not replace current widget settings or messages');
   assert.ok(save.signal.aborted);
   if(scenario==='widget-save-tenant') {
     assert.equal(h.state().tenant,'NEW');assert.equal(h.state().widget.assistant_name,'NEW assistant');
     assert.equal(h.state().snippet,'script-NEW');assert.equal(h.state().iframeSnippet,'panel-NEW');
   }
 } else if(scenario==='widget-save-duplicate') {
   await h.loadWorkspaceSection('website');h.editWidget();
   const first=h.saveWidget();await flush();const duplicate=h.saveWidget();
   assert.equal(calls.filter(c=>c.options.method==='PUT').length,1,'Double submit must make only one write');
   const save=calls.find(c=>c.options.method==='PUT');
   assert.equal(save.options.headers['X-CSRF-Token'],'synthetic-csrf');assert.equal(save.options.credentials,'same-origin');
   const payload=JSON.parse(save.options.body);assert.equal(payload.allowed_origins[0],'https://shop.synthetic.test');assert.equal(payload.accent_color,'#15324F');
   heldResolve(response({widget:payload,embed:widgetPayload('OLD').embed}));await first;await duplicate;
   assert.equal(h.state().widgetSaving,false);assert.equal(h.state().formError,false);
   assert.equal(JSON.stringify(h.state().widget),h.state().savedWidgetFingerprint);
 } else if(scenario==='widget-save-failure'||scenario==='widget-save-timeout') {
   await h.loadWorkspaceSection('website');h.editWidget();const edited=JSON.stringify(h.state().widget);
   const saving=h.saveWidget();await flush();
   if(scenario==='widget-save-timeout')for(const [id,timer] of [...timers]){assert.equal(timer.delay,20000);timers.delete(id);timer.callback();}
   await saving;assert.equal(h.state().widgetSaving,false);assert.equal(h.state().formError,true);
   assert.equal(JSON.stringify(h.state().widget),edited);assert.equal(h.state().originText,'https://shop.synthetic.test');
   assert.ok(!h.state().formStatus.includes('Private provider'));
   if(scenario==='widget-save-failure'){fail=false;await h.saveWidget();assert.equal(h.state().widgetSaving,false);assert.equal(h.state().formError,false);}
 } else if(scenario==='widget-read-only') {
   h.permissions(['business_settings.read']);await h.loadWorkspaceSection('website');h.editWidget();await h.saveWidget();
   assert.equal(calls.filter(c=>c.options.method==='PUT').length,0);assert.equal(h.state().widgetSaving,false);
 } else if(scenario==='widget-navigation-enter') {
   for(const screen of ['website','test']) {
     h.screen('pipeline');await h.openCompanyWorkspace('NEW',screen);
     assert.equal(navigation.at(-1).method,'assign');assert.equal(navigation.at(-1).target,'/console/'+screen+'?tenant=NEW');
   }
   assert.ok(!navigation.some(item=>item.method==='goto'));
 } else if(scenario==='widget-navigation-leave') {
   for(const screen of ['website','test']) {
     h.screen(screen);await h.openCompanyWorkspace('NEW','profile');
     assert.equal(navigation.at(-1).method,'assign');assert.equal(navigation.at(-1).target,'/console/profile?tenant=NEW');
   }
   assert.ok(!navigation.some(item=>item.method==='goto'));
 } else if(scenario==='widget-login-next') {
   for(const screen of ['website','test']) {
     h.screen('pipeline');location.search='?tenant=OLD&next='+screen;await h.openDefaultWorkspace();
     assert.equal(navigation.at(-1).method,'replace');assert.equal(navigation.at(-1).target,'/console/'+screen+'?tenant=OLD');
   }
   assert.ok(!navigation.some(item=>item.method==='goto'));assert.equal(calls.length,0);
 } else if(scenario==='widget-logout') {
   for(const screen of ['website','test']) {
     h.identity(identity);h.screen(screen);await h.logout();
     assert.equal(h.state().hasUser,false);assert.equal(navigation.at(-1).method,'replace');assert.equal(navigation.at(-1).target,'/console/');
   }
   assert.ok(!navigation.some(item=>item.method==='goto'));
 } else if(scenario==='ordinary-navigation') {
   h.screen('pipeline');await h.openCompanyWorkspace('NEW','profile');
   assert.equal(navigation.at(-1).method,'goto');assert.equal(navigation.at(-1).target,'/console/profile?tenant=NEW');
 } else {
   const old=h.loadWorkspaceSection('catalog');await flush();const before=JSON.stringify(h.state());destroy();
   heldResolve(response({version:1,categories:[{id:'old',name:'Private old company',items:[]}]}));await old;
   assert.equal(JSON.stringify(h.state()),before);assert.ok(calls.find(c=>c.path.includes('/catalog?')).signal.aborted);
 }
 await flush();assert.equal(timers.size,0);
})().catch(error=>{console.error(error);process.exitCode=1;});
"""


@pytest.mark.parametrize('scenario', [
    'pipeline-only', 'role-reactivity', 'cached-edits', 'directory-independent', 'directory-restart', 'retry-catalog',
    'retry-insights', 'retry-accounts', 'malformed-body', 'timeout', 'body-timeout', 'tenant-change', 'destroy',
    'widget-cached-edits', 'widget-save-tenant', 'widget-save-destroy', 'widget-save-duplicate',
    'widget-save-failure', 'widget-save-timeout', 'widget-read-only', 'widget-navigation-enter',
    'widget-navigation-leave', 'widget-login-next', 'widget-logout', 'ordinary-navigation',
])
def test_console_workspace_loads_only_current_authorized_resources(scenario):
    result = subprocess.run([NODE, '-e', SCRIPT, scenario], cwd=ROOT, capture_output=True,
                            text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
