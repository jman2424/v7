const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const ts = require('../node_modules/typescript');
const component = fs.readFileSync(path.join(__dirname, '../src/lib/UsageCredits.svelte'), 'utf8');
const script = component.match(/<script lang="ts">([\s\S]*?)<\/script>/)[1];
const tree = ts.createSourceFile('UsageCredits.svelte.ts', script, ts.ScriptTarget.Latest, true);
function functions(names) {
  const nodes = tree.statements.filter(node => ts.isFunctionDeclaration(node) && names.includes(node.name?.text));
  assert.equal(nodes.length,names.length);
  return ts.transpileModule(nodes.map(node=>node.getText(tree)).join('\n'),{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
}
function deferred() {let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};}
function harness() {
  const requests=[],redirects=[],events=[],storage=new Map();let ids=0;
  const context=vm.createContext({AbortController,setTimeout,clearTimeout,URL,
    crypto:{randomUUID(){return '00000000-0000-4000-8000-'+String(++ids).padStart(12,'0');}},
    sessionStorage:{getItem(key){return storage.get(key)||null;},setItem(key,value){storage.set(key,value);},removeItem(key){storage.delete(key);}},
    window:{location:{assign(url){redirects.push(url);}}},
    dispatch(type,data){events.push({type,data});},
    read(path,body,signal){const pending=deferred();requests.push({path,body,signal,pending});return pending.promise;}
  });
  vm.runInContext(`let tenant='FIRST',csrf='test-csrf',apiPrefix='',controller,companyController,companyBusy=false,disposed=false,busy=false,error='',message='',page=1,selectedPack='gbp_5',companies=[],companyPage=1,companyTotal=0,companyHasNext=false,companySearch='',isPlatform=true,canManageBilling=true,canTopUp=true,canViewCosts=true;
    let pack={id:'gbp_5'},data={configured:true},adjustmentAmount='',adjustmentReason='',adjustmentConfirmed=false,adjustmentRequest='';
    const checkoutRequests=new Map();
    ${functions(['errorMessages','safeError','failureText','refresh','topUp','listCompanies','syncCheckoutRequests','checkoutId','adjust'])}
    globalThis.subject={refresh,topUp,listCompanies,syncCheckoutRequests,checkoutId,errorMessages,
      dispose(){disposed=true;controller?.abort();companyController?.abort();},
      setSearch(value){companySearch=value;},setPermission(value){canManageBilling=value;},
      state(){return {error,busy,data,companies,companyTotal};}};`,context);
  return {subject:context.subject,requests,redirects,storage,events};
}
function report(checkouts=[]) {return {tenant:'FIRST',configured:true,packs:[{id:'gbp_5'}],wallet:{available_pence:500},checkout_requests:checkouts,pending_checkouts:checkouts.filter(row=>row.status==='pending')};}

test('a duplicate top-up click creates only one checkout request',async()=>{
  const {subject,requests,redirects}=harness();const topup=subject.topUp();await subject.topUp();
  assert.equal(requests.length,1);assert.deepEqual(JSON.parse(JSON.stringify(requests[0].body)),{pack_id:'gbp_5',request_id:'00000000-0000-4000-8000-000000000001'});
  requests[0].pending.resolve({url:'https://checkout.stripe.com/test-only'});await topup;assert.deepEqual(redirects,['https://checkout.stripe.com/test-only']);
});
test('an uncertain checkout retry uses the same idempotency request id',async()=>{
  const {subject,requests}=harness();const first=subject.topUp();requests[0].pending.reject(new Error('Private provider exception'));await first;
  assert.doesNotMatch(subject.state().error,/Private provider/);const retry=subject.topUp();assert.equal(requests[1].body.request_id,requests[0].body.request_id);
  requests[1].pending.resolve({url:'https://checkout.stripe.com/test-only'});await retry;
});
test('leaving a company aborts pending credit checkout and prevents a late redirect',async()=>{
  const {subject,requests,redirects}=harness();const topup=subject.topUp();subject.dispose();assert.equal(requests[0].signal.aborted,true);
  requests[0].pending.resolve({url:'https://checkout.stripe.com/test-only'});await topup;assert.deepEqual(redirects,[]);
});
test('credit checkout does not follow arbitrary provider URLs or bypass owner permission',async()=>{
  const {subject,requests,redirects}=harness();subject.setPermission(false);await subject.topUp();assert.equal(requests.length,0);
  subject.setPermission(true);const topup=subject.topUp();requests[0].pending.resolve({url:'https://untrusted.example.test/pay'});await topup;assert.deepEqual(redirects,[]);assert.match(subject.state().error,/could not be confirmed/);
});
test('only the latest credit balance refresh can update the screen',async()=>{
  const {subject,requests,events}=harness();const previous=subject.refresh();const current=subject.refresh();assert.equal(requests[0].signal.aborted,true);
  requests[1].pending.resolve(report());await current;requests[0].pending.resolve({...report(),wallet:{available_pence:1}});await previous;
  assert.equal(subject.state().data.wallet.available_pence,500);
  assert.equal(events.length,1);assert.equal(events[0].type,'creditstatus');assert.equal(events[0].data.tenant,'FIRST');
});
test('confirmed paid checkout clears its stored purchase id, pending checkout resumes the same id',()=>{
  const {subject,storage}=harness();const first=subject.checkoutId('gbp_5');assert.equal(storage.get('v7-usage-checkout:FIRST:gbp_5'),first);
  subject.syncCheckoutRequests(report([{pack_id:'gbp_5',request_id:first,status:'pending'}]));assert.equal(subject.checkoutId('gbp_5'),first);
  subject.syncCheckoutRequests(report([{pack_id:'gbp_5',request_id:first,status:'paid'}]));assert.equal(storage.has('v7-usage-checkout:FIRST:gbp_5'),false);assert.notEqual(subject.checkoutId('gbp_5'),first);
});
test('replaced company credit search cannot display another search result',async()=>{
  const {subject,requests}=harness();subject.setSearch('old');const old=subject.listCompanies();subject.setSearch('new');const current=subject.listCompanies();assert.equal(requests[0].signal.aborted,true);
  requests[1].pending.resolve({companies:[{key:'NEW'}],total:12,matched:1,has_next:false});await current;requests[0].pending.resolve({companies:[{key:'OLD'}],total:100,has_next:true});await old;
  assert.equal(subject.state().companies[0].key,'NEW');assert.equal(subject.state().companyTotal,1);
});
test('every mapped usage-credit error is translated without exposing an API code',()=>{
  const dictionary=require('../../dashboard/static/i18n/subscription.json');
  const {subject}=harness();
  for(const message of Object.values(subject.errorMessages())) {
    for(const language of ['en','es','fr','ar'])assert.ok(dictionary[language][message],language+' missing '+message);
  }
});
test('a completed purchase response clears its UUID and refreshes without creating a second payment',async()=>{
  const {subject,requests,redirects,storage}=harness();const buying=subject.topUp();
  requests[0].pending.resolve({status:'paid',url:null});await new Promise(resolve=>setImmediate(resolve));
  assert.equal(requests.length,2);assert.equal(requests[1].path,'?page=1');assert.equal(storage.has('v7-usage-checkout:FIRST:gbp_5'),false);
  requests[1].pending.resolve(report());await buying;assert.deepEqual(redirects,[]);
});
test('a processing purchase response neither redirects nor generates fresh idempotency',async()=>{
  const {subject,requests,redirects}=harness();const buying=subject.topUp();requests[0].pending.resolve({status:'processing',url:null});await buying;
  assert.deepEqual(redirects,[]);assert.equal(subject.checkoutId('gbp_5'),requests[0].body.request_id);assert.equal(requests.length,1);
});
test('credit checkout sends only server-owned pack id and idempotency id with CSRF and tenant scope',async()=>{
  const requests=[];const context=vm.createContext({fetch:async(url,options)=>{requests.push({url,options});return {ok:true,json:async()=>({})};}});
  vm.runInContext(`let tenant='MY COMPANY',csrf='test-only-csrf',apiPrefix='/api';${functions(['read','errorMessages','safeError'])};globalThis.subject={read};`,context);
  await context.subject.read('/checkout',{pack_id:'gbp_5',request_id:'test-id'});
  assert.equal(requests[0].url,'/api/billing/usage-credit/checkout?tenant=MY%20COMPANY');assert.equal(requests[0].options.credentials,'same-origin');assert.equal(requests[0].options.headers['X-CSRF-Token'],'test-only-csrf');
  assert.deepEqual(JSON.parse(requests[0].options.body),{pack_id:'gbp_5',request_id:'test-id'});assert.doesNotMatch(requests[0].options.body,/amount|tenant|balance/);
});
