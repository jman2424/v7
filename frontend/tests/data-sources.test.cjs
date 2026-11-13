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
