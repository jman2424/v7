const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const test=require('node:test');
const ts=require('../node_modules/typescript');
const source=fs.readFileSync(path.join(__dirname,'../src/lib/AIBudget.svelte'),'utf8');
const tree=ts.createSourceFile('Budget.ts',source.match(/<script lang="ts">([\s\S]*?)<\/script>/)[1],ts.ScriptTarget.Latest,true);
const functions=ts.transpileModule(tree.statements.filter(node=>ts.isFunctionDeclaration(node)).map(node=>node.getText(tree)).join('\n'),{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
function harness(storage=new Map()){
  const requests=[],redirects=[],events=[];
  const context=vm.createContext({AbortController,URL,setTimeout,clearTimeout,crypto:{randomUUID:()=> '00000000-0000-4000-8000-000000000001'},
    window:{location:{assign:url=>redirects.push(url)}},sessionStorage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},dispatch:(kind,value)=>events.push({kind,value}),
    fetch(url,options){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});requests.push({url,options,resolve:value=>resolve({ok:true,json:async()=>value}),reject});return promise;}});
  vm.runInContext(`let tenant='FIRST',csrf='csrf-synthetic',apiPrefix='',canManageBilling=true,canViewCosts=true,data=null,busy=false,error='',message='',page=1,disposed=false,controller,alertsEnabled=true,emailEnabled=false,alertThreshold=200,cap=2500,initialPack='',reviewRecharge=false,accepted=false;const requestIds=new Map();
    ${functions}
    globalThis.subject={action,refresh,requestId,syncRequests,dispose(){disposed=true;controller?.abort();},setOwner(value){canManageBilling=value;},state(){return {data,busy,error};}};`,context);
  return {subject:context.subject,requests,redirects,storage,events};
}
function report(){return {initial_pack:'',processing_available:true,internal:false,review_required:false,paused:false,available_pence:850,packs:[{id:'gbp_25',total_pence:2500}],checkout_requests:[],alerts:{enabled:true,email_enabled:false,threshold_pence:200},automatic_recharge:{cap_pence:2500,cap_choices:[2500,5000,10000]}};}

test('double purchase clicks share one request, tenant and CSRF; fixed amounts are not submitted',async()=>{
  const {subject,requests,redirects}=harness();const id=subject.requestId('funds:gbp_25');
  const first=subject.action('/checkout',{pack_id:'gbp_25',request_id:id});await subject.action('/checkout',{pack_id:'gbp_25',request_id:id});
  assert.equal(requests.length,1);assert.match(requests[0].url,/tenant=FIRST$/);assert.equal(requests[0].options.headers['X-CSRF-Token'],'csrf-synthetic');
  assert.deepEqual(JSON.parse(requests[0].options.body),{pack_id:'gbp_25',request_id:id});
  requests[0].resolve({url:'https://checkout.stripe.com/c/pay/synthetic'});await first;assert.equal(redirects.length,1);
});

test('reload after uncertain checkout preserves the same purchase id',async()=>{
  const {subject,requests,storage}=harness();const id=subject.requestId('funds:gbp_25');const first=subject.action('/checkout',{pack_id:'gbp_25',request_id:id});requests[0].reject(new Error('PRIVATE provider key'));await first;
  assert.doesNotMatch(subject.state().error,/PRIVATE/);assert.equal(harness(storage).subject.requestId('funds:gbp_25'),id);
});

test('server pending checkout is resumed across views instead of another purchase',()=>{
  const {subject}=harness();subject.syncRequests({...report(),checkout_requests:[{pack_id:'gbp_25',request_id:'legacy_request_123',status:'pending'}]});
  assert.equal(subject.requestId('funds:gbp_25'),'legacy_request_123');
});

test('leaving a tenant prevents a late payment redirect or stale balance',async()=>{
  const {subject,requests,redirects}=harness();const work=subject.action('/checkout',{pack_id:'gbp_25',request_id:'request_001'});subject.dispose();assert.equal(requests[0].options.signal.aborted,true);requests[0].resolve({url:'https://checkout.stripe.com/c/pay/synthetic'});await work;assert.equal(redirects.length,0);
});

test('latest balance refresh wins and only simple budget events are emitted',async()=>{
  const {subject,requests,events}=harness();const older=subject.refresh();const latest=subject.refresh();assert.equal(requests[0].options.signal.aborted,true);
  requests[1].resolve(report());await latest;requests[0].resolve({...report(),available_pence:0});await older;assert.equal(subject.state().data.available_pence,850);assert.equal(events.filter(event=>event.kind==='creditstatus').length,1);
});

test('nonowners cannot mutate settings and unapproved redirect hosts are rejected',async()=>{
  const {subject,requests,redirects}=harness();subject.setOwner(false);await subject.action('/preferences',{email_alerts:true});assert.equal(requests.length,0);
  subject.setOwner(true);const work=subject.action('/checkout',{});requests[0].resolve({url:'https://untrusted.example.test/pay'});await work;assert.equal(redirects.length,0);assert.match(subject.state().error,/could not be updated/);
});

test('new customer budget has all four translations, including dynamic errors and transaction labels',()=>{
  const {parse}=require('../node_modules/svelte/compiler');const dictionary=require('../../dashboard/static/i18n/subscription.json');const keys=new Set(['Funds added','AI usage','Refund','Refund reversed','Balance adjustment','Payment reversal','Usage adjustment']);
  function texts(node){if(!node)return[];if(node.type==='Literal'&&typeof node.value==='string')return[node.value];if(node.type==='ConditionalExpression')return[...texts(node.consequent),...texts(node.alternate)];return[];}
  function walk(node,script=false){if(!node||typeof node!=='object')return;if(node.type==='CallExpression'&&node.callee?.name==='$t')texts(node.arguments[0]).forEach(key=>keys.add(key));if(script&&node.type==='Literal'&&typeof node.value==='string'&&/^[A-Z£].*[.!?]$/.test(node.value)&&node.value.includes(' '))keys.add(node.value);for(const value of Object.values(node)){if(Array.isArray(value))value.forEach(child=>walk(child,script));else if(value&&typeof value==='object')walk(value,script);}}
  const ast=parse(source);walk(ast);walk(ast.instance,true);assert.ok(keys.size>70);
  for(const lang of ['en','es','fr','ar'])for(const key of keys)assert.ok(dictionary[lang][key]?.trim(),lang+' missing '+key);
});
