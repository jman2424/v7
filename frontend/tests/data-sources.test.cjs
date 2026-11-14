const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const ts=require('../node_modules/typescript');
const test=require('node:test');
const source=fs.readFileSync(path.join(__dirname,'../src/lib/dataSourceText.ts'),'utf8');
const scope={exports:{},Date,Math,Object};
vm.runInNewContext(ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText,scope);
const text=scope.exports;
const page=fs.readFileSync(path.join(__dirname,'../src/lib/DataSources.svelte'),'utf8');
const navigation=JSON.parse(fs.readFileSync(path.join(__dirname,'../../service/console_navigation.json'),'utf8'));
const store={kind:'woocommerce',status:'connected',problem:'',stale:false,ownership:{names:'source',prices:'source',categories:'v7',availability:'source'}};

test('Data Sources & Sync sits under My Business and keeps six workspaces',()=>{
  assert.equal(navigation.workspaces.length,6);
  const business=navigation.workspaces.find(item=>item.id==='business');
  assert.deepEqual(business.views.at(-1),{id:'sync',label:'Data Sources & Sync',section:'data-sources'});
});
test('status wording is plain and never shows a technical code',()=>{
  assert.equal(text.sourceTitle(store),'Connected to WooCommerce');
  assert.equal(text.syncingText(store),'Products, prices and availability');
  assert.equal(text.agoText(1000-600,1000),'10 minutes ago');
  assert.equal(text.agoText(null),'Not yet');
  assert.match(text.sourceProblem({...store,status:'reconnect'}),/^Your store connection needs attention\./);
  assert.match(text.sourceProblem({...store,status:'attention',problem:'source_unreachable'}),/^Your store connection needs attention\./);
  assert.match(text.sourceProblem({...store,problem:'some_items_skipped'}),/^Some product updates couldn’t be imported/);
  assert.match(text.sourceProblem({...store,stale:true}),/has not updated for a while/);
  for(const message of [text.sourceProblem({...store,status:'attention',problem:'source_unreachable'}),text.importError('some_new_server_code'),text.reasonText('unknown'),text.issueText('unknown')])
    assert.doesNotMatch(message,/_|source_unreachable|webhook|payload|HTTP/);
});
test('the page sends the CSRF token, asks for authorisation and never stores secrets in the browser',()=>{
  assert.match(page,/'X-CSRF-Token': csrf/);
  assert.match(page,/bind:checked=\{authorised\} required/);
  assert.match(page,/disabled=\{busy \|\| !authorised/);
  assert.doesNotMatch(page,/localStorage|sessionStorage/);
  assert.match(page,/Sync Now/);assert.match(page,/Change Settings/);assert.match(page,/Disconnect/);
  // Payloads and logs stay behind the operator-only disclosure.
  assert.match(page,/\{#if isPlatform\}\s*<details class="diagnostics">/);
});
test('a website is read only after the owner ticks its own permission statement, and the record is shown',()=>{
  assert.match(page,/begin\('website'\)/);
  assert.match(page,/adding === 'website' \? listing\.website_statement : listing\.authorisation_statement/);
  assert.match(page,/kind: 'website', authorised, auto_sync: automatic/);
  assert.match(page,/Withdraw permission/);assert.match(page,/Permission records/);
  const site={...store,kind:'website'};
  assert.equal(text.sourceTitle(site),'Reading your website with your permission');
  assert.equal(text.syncingText(site),'Public pages of your website (up to 20)');
  assert.match(text.sourceProblem({...site,status:'attention',problem:'website_changed'}),/covered the old address only/);
  assert.match(text.importError('website_permission_required'),/^Give permission/);
  const row={kind:'website',domain:'shop.example',statement:'',terms_version:'t',account:'owner@shop.example',granted:10,ended:0,end_reason:'',ended_by:''};
  const when=seconds=>'day '+seconds;
  assert.equal(text.permissionText(row,when),'Read the public pages of shop.example. Given on day 10 by owner@shop.example. Still in force.');
  assert.match(text.permissionText({...row,ended:20,end_reason:'withdrawn',ended_by:'owner@shop.example'},when),/Withdrawn on day 20 by owner@shop\.example\.$/);
  assert.match(text.permissionText({...row,ended:20,end_reason:'renewed'},when),/Replaced by a newer permission on day 20\.$/);
});
